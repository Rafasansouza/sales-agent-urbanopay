"""Tools de Quote, Order e Approval (SPEC-003; SPEC-004 §7, §9.1).

Aqui mora a fronteira mais delicada da jornada: é onde a intenção do cliente
vira compromisso comercial. Três invariantes governam este arquivo:

1. **o modelo não escolhe qual Order confirmar** — o identificador vem do
   contexto de confirmação (§9.1);
2. **a idempotency key nunca é argumento** — ela é derivada de identificadores
   já persistidos;
3. **o perfil tarifário é do cartão** — a declaração do cliente só produz o
   sinal de divergência (A-11), nunca substitui a autoridade.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

from urbanopay.modules.agent.application import presenters
from urbanopay.modules.agent.domain.errors import (
    ConfirmationContextMismatchError,
    NoPendingConfirmationError,
)
from urbanopay.modules.agent.domain.idempotency_keys import IdempotencyKeyPolicy
from urbanopay.modules.agent.domain.results import NextAction, ResultType, ToolResult
from urbanopay.modules.cards.domain.enums import FareProfile
from urbanopay.modules.fare.domain.errors import InvalidFareProfileError
from urbanopay.modules.orders.domain.enums import OrderStatus
from urbanopay.modules.orders.domain.errors import (
    InvalidRechargeAmountError,
    QuoteNotAccessibleError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from urbanopay.modules.agent.application.schemas import (
        ConfirmOrderInput,
        CreateOrderInput,
        CreateRechargeQuoteInput,
        OrderInput,
    )
    from urbanopay.modules.agent.application.tools import ToolContext

_ORDER_NEXT: Final[Mapping[OrderStatus, NextAction]] = {
    OrderStatus.DRAFT: NextAction.CONFIRM_ORDER,
    OrderStatus.REQUIRES_APPROVAL: NextAction.AWAIT_HUMAN_APPROVAL,
    OrderStatus.CONFIRMED: NextAction.CONTINUE,
    OrderStatus.PAYMENT_PENDING: NextAction.AWAIT_PAYMENT,
    OrderStatus.PAID: NextAction.CHECK_FULFILLMENT,
    OrderStatus.FULFILLING: NextAction.WAIT,
    OrderStatus.COMPLETED: NextAction.CONTINUE,
    OrderStatus.FULFILLMENT_FAILED: NextAction.HUMAN_REVIEW,
    OrderStatus.CANCELLED: NextAction.STOP,
    OrderStatus.EXPIRED: NextAction.RECREATE_ORDER,
}


def _parse_amount(raw: str) -> Decimal:
    """Converte a string decimal do contrato em `Decimal`.

    `Decimal(str)` e não `float`: ponto flutuante é proibido em qualquer ponto
    do caminho do dinheiro (ADR-012). A validação de faixa e de escala pertence
    ao domínio — `LineItem.for_recharge` —, e não é reimplementada aqui.
    """
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise InvalidRechargeAmountError from exc


def _parse_declared_profile(raw: str | None) -> FareProfile | None:
    if raw is None:
        return None
    try:
        return FareProfile(raw.strip().upper())
    except ValueError as exc:
        raise InvalidFareProfileError from exc


async def create_recharge_quote(ctx: ToolContext, payload: CreateRechargeQuoteInput) -> ToolResult:
    """Orçamento de recarga de valor livre (SPEC-003 §1.1, §4).

    A resolução do perfil oficial vem **antes** da Quote, e não por estilo:
    `QuoteService` recebe `card_id` já validado e `fare_profile` já resolvido,
    então é aqui que titularidade, estado do cartão e autoridade do perfil são
    exercidos. Sem esse passo, um cartão bloqueado ou de terceiro chegaria
    intacto à criação do orçamento.

    O valor é do cliente (A-06: o agente não o sugere) e o Fare Engine não
    participa — em `RECHARGE`, `fare_profile` é snapshot de auditoria.
    """
    customer_id = ctx.require_customer()
    amount = _parse_amount(payload.amount)
    declared = _parse_declared_profile(payload.declared_fare_profile)

    resolution = await ctx.services.cards.resolve_official_fare_profile(
        customer_id, payload.card_id, declared
    )
    quote = await ctx.services.quotes.create_recharge_quote(
        customer_id=customer_id,
        card_id=payload.card_id,
        fare_profile=resolution.official_profile.value,
        amount=amount,
    )
    return ToolResult.success(
        ResultType.QUOTE,
        presenters.quote(
            quote,
            profile_signal=resolution.signal.value if resolution.signal is not None else None,
        ),
        next_action=NextAction.CONTINUE,
    )


async def create_order(ctx: ToolContext, payload: CreateOrderInput) -> ToolResult:
    """Cria o Order em `DRAFT` a partir da Quote em curso (SPEC-003 §5).

    A Quote vem do contexto. Um `quote_id` informado que divirja do contexto é
    recusado: orçar uma coisa e pedir outra é o começo de toda confirmação
    errada.

    A key é `create_order:{quote_id}` — a Quote **é** a identidade da intenção
    comercial, e uma Quote produz no máximo um Order (§4).
    """
    customer_id = ctx.require_customer()
    quote_id = ctx.state.current_quote_id

    if payload.quote_id is not None:
        if quote_id is not None and payload.quote_id != quote_id:
            raise ConfirmationContextMismatchError
        quote_id = payload.quote_id
    if quote_id is None:
        raise QuoteNotAccessibleError

    order = await ctx.services.orders.create_order(
        customer_id=customer_id,
        quote_id=quote_id,
        idempotency_key=IdempotencyKeyPolicy.create_order(quote_id),
    )
    return ToolResult.success(
        ResultType.ORDER,
        presenters.order(order),
        next_action=_ORDER_NEXT[order.status],
    )


async def confirm_order(ctx: ToolContext, payload: ConfirmOrderInput) -> ToolResult:
    """Confirmação explícita do cliente (SPEC-003 §8, SPEC-004 §9.1).

    A Order confirmada é **sempre** `pending_confirmation.order_id`. O modelo
    pode classificar um "sim" como confirmação; escolher o que se confirma não
    é dele.

    Um "sim" fora de contexto não encontra nada a confirmar; um "sim" apontando
    para outra Order é recusado. E um segundo "sim" sobre a mesma Order é
    replay da mesma key — não segundo efeito.

    Se `requires_approval` estiver congelado como verdadeiro, o destino é
    `REQUIRES_APPROVAL` e a jornada financeira **para** aqui: nada nesta camada
    aprova, e nenhuma frase do cliente é decisão humana (A-07).
    """
    customer_id = ctx.require_customer()
    pending = ctx.state.pending_confirmation
    if pending is None:
        raise NoPendingConfirmationError
    if payload.order_id is not None and not pending.binds(payload.order_id):
        raise ConfirmationContextMismatchError

    order = await ctx.services.orders.confirm_order(
        customer_id=customer_id,
        order_id=pending.order_id,
        idempotency_key=IdempotencyKeyPolicy.confirm_order(pending.order_id),
    )
    return ToolResult.success(
        ResultType.ORDER,
        presenters.order(order),
        next_action=_ORDER_NEXT[order.status],
    )


async def get_order(ctx: ToolContext, payload: OrderInput) -> ToolResult:
    """Consulta de Order do próprio cliente, sempre relida do backend."""
    order = await ctx.services.orders.get_order(
        customer_id=ctx.require_customer(), order_id=payload.order_id
    )
    return ToolResult.success(
        ResultType.ORDER,
        presenters.order(order),
        next_action=_ORDER_NEXT[order.status],
    )


async def get_approval_status(ctx: ToolContext, payload: OrderInput) -> ToolResult:
    """Estado da aprovação humana (SPEC-003 §7).

    Somente leitura. O Sales Agent consulta; nunca aprova nem rejeita — e não
    existe tool que o permita, sob nome algum.
    """
    decision = await ctx.services.orders.get_approval_status(
        customer_id=ctx.require_customer(), order_id=payload.order_id
    )
    return ToolResult.success(
        ResultType.APPROVAL_STATUS,
        presenters.approval(decision),
        next_action=(
            NextAction.AWAIT_HUMAN_APPROVAL if decision.is_pending else NextAction.CONTINUE
        ),
    )
