"""Tools de pagamento (SPEC-003 §9, §10, §13; SPEC-004 §7, §9.1).

É a superfície mais próxima do dinheiro, e por isso a de menor autonomia.
Nenhuma tool daqui aceita valor, status, `payment_id` ou idempotency key: o
valor vem de `order.total`, o status vem do provider, e a key é derivada de
evidência persistida.

Regra que este arquivo materializa: **estado externo desconhecido nunca
autoriza nova cobrança.** A resolução é reconciliação — que é comando de
backend e não tem tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from urbanopay.modules.agent.application import presenters
from urbanopay.modules.agent.domain.errors import (
    ConfirmationContextMismatchError,
    NoPendingConfirmationError,
)
from urbanopay.modules.agent.domain.idempotency_keys import IdempotencyKeyPolicy
from urbanopay.modules.agent.domain.results import NextAction, ResultType, ToolResult
from urbanopay.modules.payments.domain.errors import (
    PaymentAlreadyApprovedError,
    PaymentStatusUnknownError,
)
from urbanopay.modules.payments.domain.results import PaymentCreationResult

if TYPE_CHECKING:
    from urbanopay.modules.agent.application.schemas import CreatePaymentInput, OrderInput
    from urbanopay.modules.agent.application.tools import ToolContext


async def create_payment(ctx: ToolContext, payload: CreatePaymentInput) -> ToolResult:
    """Cria a cobrança Pix do Order confirmado em curso (SPEC-003 §9, §10).

    O Order vem do contexto comercial, não do modelo. Antes de qualquer
    criação, o **estado persistido** é relido — é ele, e não o estado
    conversacional, que decide se existe uma tentativa a preservar:

    - Payment `APPROVED` ⇒ já foi pago; nada a criar;
    - tentativa `CREATED` ⇒ desfecho externo desconhecido (§9.1). Devolve
      `PAYMENT_STATUS_UNKNOWN` e **para**: nenhum POST novo, nenhuma key nova,
      nenhum laço de cobrança;
    - tentativa `PENDING` ⇒ a cobrança existe e está válida; devolve a
      existente em vez de criar uma segunda;
    - terminal não aprovado ⇒ nova tentativa comercial é legítima (§13.2), e
      sua identidade deriva do `payment_id` terminal anterior.

    A key nunca vem do modelo e nunca é trocada para "tentar de novo": trocá-la
    é exatamente o que transformaria um timeout em cobrança dupla.
    """
    customer_id = ctx.require_customer()
    order_id = ctx.state.current_order_id
    if order_id is None:
        raise NoPendingConfirmationError
    if payload.order_id is not None and payload.order_id != order_id:
        raise ConfirmationContextMismatchError

    status = await ctx.services.payments.get_payment_status_for_order(
        customer_id=customer_id, order_id=order_id
    )
    if status.is_approved:
        raise PaymentAlreadyApprovedError
    if status.outcome_is_unknown:
        raise PaymentStatusUnknownError
    if status.has_active_attempt and status.latest is not None:
        # Cobrança já confirmada pelo provider: criar outra seria segunda
        # cobrança do mesmo Order.
        return ToolResult.success(
            ResultType.PAYMENT,
            presenters.payment_creation(
                PaymentCreationResult(payment=status.latest, qr_code=None, already_existed=True)
            ),
            next_action=NextAction.AWAIT_PAYMENT,
        )

    result = await ctx.services.payments.create_payment(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=IdempotencyKeyPolicy.create_payment(
            order_id, previous_terminal_payment_id=status.previous_terminal_payment_id
        ),
    )
    return ToolResult.success(
        ResultType.PAYMENT,
        presenters.payment_creation(result),
        next_action=NextAction.AWAIT_PAYMENT,
    )


async def get_payment_status(ctx: ToolContext, payload: OrderInput) -> ToolResult:
    """Situação de pagamento de um Order (SPEC-004 §7).

    Leitura pura: **não** consulta o provider e **não** escreve nada. A
    consulta ativa é `reconcile_payment`, que tem efeito, é comando de backend
    e não é alcançável daqui — uma pergunta do cliente não pode disparar
    tráfego externo nem registrar evento.

    É esta a tool que responde a "eu já paguei": ela devolve o que o backend
    sabe, e a afirmação do cliente não altera nada.
    """
    status = await ctx.services.payments.get_payment_status_for_order(
        customer_id=ctx.require_customer(), order_id=payload.order_id
    )
    next_action = NextAction.AWAIT_PAYMENT
    if status.is_approved:
        next_action = NextAction.CHECK_FULFILLMENT
    elif status.outcome_is_unknown:
        next_action = NextAction.WAIT_RECONCILIATION
    elif status.latest is None:
        next_action = NextAction.CONTINUE

    return ToolResult.success(
        ResultType.PAYMENT_STATUS,
        presenters.payment_status(status),
        next_action=next_action,
    )
