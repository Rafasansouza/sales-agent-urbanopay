"""Serviços de aplicação de Orders (SPEC-003 §4, §5, §7, §8, §11, §14).

Orquestram os ports dentro da fronteira transacional (`OrdersUnitOfWork`);
commit sempre explícito; nenhum acesso a `AsyncSession`.

Regras transversais:

- o instante `now` é resolvido UMA vez por operação e usado em toda
  verificação de expiração e em toda escrita;
- **ordem de lock: `Order` → `Approval`** (ADR-012, ordem global
  `Order → Approval → Payment`);
- todas as operações daqui são **exclusivamente locais**, portanto usam a
  idempotência de fase única (§11.2): reivindicar a key, aplicar o efeito e
  marcar `COMPLETED` na mesma transação. Não existe `IN_PROGRESS` órfão
  observável, porque uma falha desfaz reivindicação e efeito juntos;
- nenhuma regra de negócio determinística depende de texto do usuário.

Fronteira de responsabilidade: estes serviços recebem um `customer_id` **já
autenticado** e um `card_id` **já validado** (titularidade e estado) pelos
módulos `identity` e `cards`, que são a autoridade dessas verificações
(SPEC-002 §5, §9). A autorização que pertence a este módulo — titularidade do
Quote e do Order — é aplicada aqui, sempre em query única.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from urbanopay.core.idempotency import (
    IdempotencyRecord,
    IdempotencyStatus,
    ensure_same_request,
    request_fingerprint,
)
from urbanopay.modules.approvals.domain.entities import Approval
from urbanopay.modules.approvals.domain.enums import ApprovalStatus
from urbanopay.modules.approvals.domain.errors import ApprovalNotFoundError
from urbanopay.modules.orders.domain.entities import LineItem, Order, Quote
from urbanopay.modules.orders.domain.enums import (
    CURRENCY_BRL,
    OperationType,
    OrderStatus,
)
from urbanopay.modules.orders.domain.errors import (
    InvalidOrderStateError,
    OrderNotAccessibleError,
    OrderNotFoundError,
    QuoteAlreadyConsumedError,
    QuoteNotAccessibleError,
)
from urbanopay.modules.orders.domain.state_machine import (
    apply_approval_granted,
    apply_approval_rejected,
    cancel_by_customer,
    confirm,
    expire,
)

if TYPE_CHECKING:
    from urbanopay.modules.orders.domain.policies import ApprovalPolicy
    from urbanopay.modules.orders.domain.ports import OrdersUnitOfWork

# Recarga não possui desconto (§1.1): `discount_amount` é sempre zero, com a
# mesma escala dos demais valores monetários.
_NO_DISCOUNT = Decimal("0.00")

# Nomes de operação do escopo de idempotência `(operation, key)` (§11).
OPERATION_CREATE_ORDER = "create_order"
OPERATION_CONFIRM_ORDER = "confirm_order"
OPERATION_APPROVE_ORDER = "approve_order"
OPERATION_REJECT_ORDER = "reject_order"


def _now(at: datetime | None) -> datetime:
    reference = at if at is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        raise ValueError("O instante de referência deve ser timezone-aware.")
    return reference


class QuoteService:
    """Criação de orçamentos (SPEC-003 §4).

    `create_quote` **não** está na lista de operações idempotentes da §11, e
    isso é coerente: uma Quote não reserva dinheiro nem transiciona estado, e
    duas Quotes idênticas não produzem efeito financeiro duplicado.
    """

    def __init__(self, uow: OrdersUnitOfWork, *, quote_ttl: timedelta) -> None:
        self._uow = uow
        self._ttl = quote_ttl

    async def create_recharge_quote(
        self,
        *,
        customer_id: uuid.UUID,
        card_id: uuid.UUID,
        fare_profile: str,
        amount: Decimal,
        at: datetime | None = None,
    ) -> Quote:
        """Orçamento de recarga de valor livre (§1.1).

        O valor é escolhido pelo cliente: `subtotal == total` e
        `discount_amount == 0`. O Fare Engine não participa — `fare_profile`
        entra apenas como snapshot de auditoria do perfil oficial vigente.

        `LineItem.for_recharge` valida o valor (positivo, duas casas), e nada
        aqui arredonda.
        """
        now = _now(at)
        item = LineItem.for_recharge(amount)
        quote = Quote(
            id=uuid.uuid4(),
            customer_id=customer_id,
            card_id=card_id,
            operation_type=OperationType.RECHARGE,
            fare_profile=fare_profile,
            items=(item,),
            subtotal=item.total_amount,
            discount_amount=_NO_DISCOUNT,
            total=item.total_amount,
            currency=CURRENCY_BRL,
            expires_at=now + self._ttl,
            created_at=now,
        )
        async with self._uow:
            await self._uow.quotes.add(quote)
            await self._uow.commit()
        return quote


class OrderService:
    """Ciclo de vida do Order (SPEC-003 §5, §7, §8, §14)."""

    def __init__(
        self,
        uow: OrdersUnitOfWork,
        policy: ApprovalPolicy,
        *,
        draft_ttl: timedelta,
    ) -> None:
        self._uow = uow
        self._policy = policy
        self._draft_ttl = draft_ttl

    # --- idempotência de fase única (§11.2) ------------------------------

    async def _claim(
        self, *, operation: str, key: str, payload: dict[str, str], now: datetime
    ) -> IdempotencyRecord | None:
        """Reivindica a key. Devolve `None` quando esta execução é a dona.

        Quando devolve um registro, é replay: o efeito já foi aplicado e
        confirmado por outra execução. Payload divergente na mesma key produz
        `IDEMPOTENCY_CONFLICT` antes de qualquer leitura de recurso.
        """
        fingerprint = request_fingerprint(payload)
        claim = await self._uow.idempotency.claim(
            operation=operation, key=key, fingerprint=fingerprint, at=now
        )
        if claim.acquired:
            return None

        existing = claim.existing
        if existing is None:  # pragma: no cover - garantido pelo port
            raise InvalidOrderStateError
        ensure_same_request(existing, fingerprint)

        # Em operação local, `FAILED` nunca é gravado: uma falha desfaz a
        # própria reivindicação junto com o efeito. `IN_PROGRESS` também não é
        # observável, porque a transação dona ainda não comitou e o
        # `INSERT ... ON CONFLICT` aguarda o desfecho dela. Sobra `COMPLETED`.
        if existing.status is not IdempotencyStatus.COMPLETED:  # pragma: no cover
            raise InvalidOrderStateError
        return existing

    async def _complete(
        self, *, operation: str, key: str, resource_id: uuid.UUID, now: datetime
    ) -> None:
        await self._uow.idempotency.complete(
            operation=operation,
            key=key,
            resource_id=resource_id,
            response_reference=None,
            at=now,
        )

    # --- comandos ---------------------------------------------------------

    async def create_order(
        self,
        *,
        customer_id: uuid.UUID,
        quote_id: uuid.UUID,
        idempotency_key: str,
        at: datetime | None = None,
    ) -> Order:
        """Cria o Order em `DRAFT` a partir de uma Quote válida (§5).

        Congela produto, quantidade, perfil, desconto e total, e congela
        `requires_approval` pela `ApprovalPolicy`. Recalcular a aprovação
        depois permitiria contorná-la alterando o total.
        """
        now = _now(at)
        payload = {"customer_id": str(customer_id), "quote_id": str(quote_id)}
        async with self._uow:
            replay = await self._claim(
                operation=OPERATION_CREATE_ORDER,
                key=idempotency_key,
                payload=payload,
                now=now,
            )
            if replay is not None and replay.resource_id is not None:
                return await self._require_owned(
                    customer_id=customer_id, order_id=replay.resource_id
                )

            quote = await self._uow.quotes.get_owned(customer_id=customer_id, quote_id=quote_id)
            if quote is None:
                raise QuoteNotAccessibleError
            quote.ensure_usable(now)
            quote.operation_type.require_supported()

            if await self._uow.orders.has_quote_been_consumed(quote_id):
                raise QuoteAlreadyConsumedError

            order = Order(
                id=uuid.uuid4(),
                customer_id=quote.customer_id,
                card_id=quote.card_id,
                quote_id=quote.id,
                operation_type=quote.operation_type,
                status=OrderStatus.DRAFT,
                items=quote.items,
                subtotal=quote.subtotal,
                discount_amount=quote.discount_amount,
                total=quote.total,
                currency=quote.currency,
                requires_approval=self._policy.requires_approval(
                    operation_type=quote.operation_type, total=quote.total
                ),
                expires_at=now + self._draft_ttl,
                cancellation_reason=None,
                created_at=now,
                updated_at=now,
            )
            await self._uow.orders.add(order)
            await self._complete(
                operation=OPERATION_CREATE_ORDER,
                key=idempotency_key,
                resource_id=order.id,
                now=now,
            )
            await self._uow.commit()
        return order

    async def confirm_order(
        self,
        *,
        customer_id: uuid.UUID,
        order_id: uuid.UUID,
        idempotency_key: str,
        at: datetime | None = None,
    ) -> Order:
        """Confirmação explícita do cliente (§8) — primeiro consentimento.

        `requires_approval = false` ⇒ `CONFIRMED`; `true` ⇒
        `REQUIRES_APPROVAL`, **criando a `Approval` em `PENDING` na mesma
        transação**, para que não exista Order aguardando aprovação sem
        aprovação correspondente.

        Uma mensagem ambígua ou negativa nunca chega aqui: a classificação da
        intenção do cliente pertence à SPEC-004, e somente uma confirmação
        explícita invoca este comando. `DRAFT` expirado produz
        `ORDER_EXPIRED`.
        """
        now = _now(at)
        payload = {"customer_id": str(customer_id), "order_id": str(order_id)}
        async with self._uow:
            replay = await self._claim(
                operation=OPERATION_CONFIRM_ORDER,
                key=idempotency_key,
                payload=payload,
                now=now,
            )
            if replay is not None:
                return await self._require_owned(customer_id=customer_id, order_id=order_id)

            order = await self._uow.orders.get_owned_for_update(
                customer_id=customer_id, order_id=order_id
            )
            if order is None:
                raise OrderNotAccessibleError

            confirmed = confirm(order, now)
            await self._uow.orders.update(confirmed)

            if confirmed.status is OrderStatus.REQUIRES_APPROVAL:
                await self._uow.approvals.add(
                    Approval(
                        id=uuid.uuid4(),
                        order_id=confirmed.id,
                        status=ApprovalStatus.PENDING,
                        requested_at=now,
                        decided_at=None,
                        decided_by=None,
                    )
                )

            await self._complete(
                operation=OPERATION_CONFIRM_ORDER,
                key=idempotency_key,
                resource_id=confirmed.id,
                now=now,
            )
            await self._uow.commit()
        return confirmed

    async def cancel_order(
        self,
        *,
        customer_id: uuid.UUID,
        order_id: uuid.UUID,
        at: datetime | None = None,
    ) -> Order:
        """Cancelamento pelo cliente — somente em `DRAFT` (§14).

        Sem idempotency key: a §11 não a exige, e a operação não tem efeito
        externo. Repetição encontra estado incompatível e é recusada.
        """
        now = _now(at)
        async with self._uow:
            order = await self._uow.orders.get_owned_for_update(
                customer_id=customer_id, order_id=order_id
            )
            if order is None:
                raise OrderNotAccessibleError
            cancelled = cancel_by_customer(order, now)
            await self._uow.orders.update(cancelled)
            await self._uow.commit()
        return cancelled

    async def expire_draft(self, *, order_id: uuid.UUID, at: datetime | None = None) -> Order:
        """Materializa `DRAFT → EXPIRED` para um Order vencido (§5.1).

        Comando operacional, sem ator cliente: destina-se à rotina que
        materializa expirações. A verificação de vencimento na confirmação é
        independente deste comando — um `DRAFT` vencido já é recusado com
        `ORDER_EXPIRED` mesmo que ninguém tenha rodado esta rotina.
        """
        now = _now(at)
        async with self._uow:
            order = await self._uow.orders.get_for_update(order_id)
            if order is None:
                raise OrderNotFoundError
            if not order.is_draft_expired(now):
                raise InvalidOrderStateError
            expired = expire(order, now)
            await self._uow.orders.update(expired)
            await self._uow.commit()
        return expired

    # --- decisão humana (§7) ---------------------------------------------

    async def approve_order(
        self,
        *,
        order_id: uuid.UUID,
        actor: str,
        idempotency_key: str,
        at: datetime | None = None,
    ) -> Order:
        """`Approval APPROVED` ⇒ `REQUIRES_APPROVAL → CONFIRMED` (§7).

        Operação da superfície administrativa: o ator **não** é o cliente,
        então não há filtro de titularidade — e não há o que enumerar. O
        Sales Agent nunca invoca este comando (§7, §18).

        ⚠️ A superfície pela qual um humano decide permanece em aberto (A-07);
        o que existe aqui é o comando determinístico que ela chamará.
        """
        return await self._decide(
            order_id=order_id,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=OPERATION_APPROVE_ORDER,
            granted=True,
            at=at,
        )

    async def reject_order(
        self,
        *,
        order_id: uuid.UUID,
        actor: str,
        idempotency_key: str,
        at: datetime | None = None,
    ) -> Order:
        """`Approval REJECTED` ⇒ `REQUIRES_APPROVAL → CANCELLED` (§7).

        O motivo é registrado como `APPROVAL_REJECTED` — nunca apresentado
        como cancelamento solicitado pelo cliente. Não há reembolso a tratar:
        nenhum pagamento existe neste ponto do fluxo.
        """
        return await self._decide(
            order_id=order_id,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=OPERATION_REJECT_ORDER,
            granted=False,
            at=at,
        )

    async def _decide(
        self,
        *,
        order_id: uuid.UUID,
        actor: str,
        idempotency_key: str,
        operation: str,
        granted: bool,
        at: datetime | None,
    ) -> Order:
        now = _now(at)
        payload = {"order_id": str(order_id), "granted": str(granted).lower()}
        async with self._uow:
            replay = await self._claim(
                operation=operation, key=idempotency_key, payload=payload, now=now
            )
            if replay is not None:
                return await self._require_existing(order_id=order_id)

            # Ordem global de lock: Order ANTES de Approval.
            order = await self._uow.orders.get_for_update(order_id)
            if order is None:
                raise OrderNotFoundError
            approval = await self._uow.approvals.get_for_order_for_update(order_id)
            if approval is None:
                raise ApprovalNotFoundError

            decided = approval.approve(actor, now) if granted else approval.reject(actor, now)
            await self._uow.approvals.update(decided)

            updated = (
                apply_approval_granted(order, now)
                if granted
                else apply_approval_rejected(order, now)
            )
            await self._uow.orders.update(updated)

            await self._complete(
                operation=operation, key=idempotency_key, resource_id=order.id, now=now
            )
            await self._uow.commit()
        return updated

    # --- consultas --------------------------------------------------------

    async def get_order(self, *, customer_id: uuid.UUID, order_id: uuid.UUID) -> Order:
        """Consulta do cliente, sempre filtrada por titularidade."""
        async with self._uow:
            return await self._require_owned(customer_id=customer_id, order_id=order_id)

    async def _require_owned(self, *, customer_id: uuid.UUID, order_id: uuid.UUID) -> Order:
        order = await self._uow.orders.get_owned(customer_id=customer_id, order_id=order_id)
        if order is None:
            raise OrderNotAccessibleError
        return order

    async def _require_existing(self, *, order_id: uuid.UUID) -> Order:
        order = await self._uow.orders.get(order_id)
        if order is None:
            raise OrderNotFoundError
        return order
