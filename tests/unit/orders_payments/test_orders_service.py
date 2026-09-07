"""Serviços de aplicação de Orders (SPEC-003 §4, §5, §7, §8, §11)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.orders_payments.builders import FIXED_NOW, TTL, make_quote
from urbanopay.core.idempotency import (
    IdempotencyConflictError,
    IdempotencyStatus,
)
from urbanopay.modules.approvals.domain.enums import ApprovalStatus
from urbanopay.modules.approvals.domain.errors import (
    ApprovalNotFoundError,
    InvalidApprovalStateError,
)
from urbanopay.modules.orders.application.services import (
    OPERATION_CONFIRM_ORDER,
    OPERATION_CREATE_ORDER,
    OrderService,
    QuoteService,
)
from urbanopay.modules.orders.domain.enums import CancellationReason, OrderStatus
from urbanopay.modules.orders.domain.errors import (
    InvalidOrderStateError,
    OrderExpiredError,
    OrderNotAccessibleError,
    OrderNotFoundError,
    QuoteAlreadyConsumedError,
    QuoteExpiredError,
    QuoteNotAccessibleError,
)
from urbanopay.modules.orders.domain.policies import ApprovalPolicy

from .fakes import FakeOrdersUnitOfWork, Store

CUSTOMER = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
OTHER_CUSTOMER = uuid.UUID("00000000-0000-4000-8000-0000000000c2")
ACTOR = "operator-3"
LATER = FIXED_NOW + timedelta(minutes=1)


def make_service(store: Store) -> OrderService:
    return OrderService(FakeOrdersUnitOfWork(store), ApprovalPolicy(), draft_ttl=TTL)


async def seed_order(
    store: Store,
    *,
    total: Decimal = Decimal("50.00"),
    customer_id: uuid.UUID = CUSTOMER,
) -> uuid.UUID:
    """Cria uma Quote e um Order em DRAFT, devolvendo o `order_id`."""
    quote = make_quote(customer_id=customer_id, total=total)
    store.state.quotes[quote.id] = quote
    order = await make_service(store).create_order(
        customer_id=customer_id,
        quote_id=quote.id,
        idempotency_key=f"create-{quote.id}",
        at=FIXED_NOW,
    )
    return order.id


# --- create_quote (§4) ---------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_quote_de_recarga_congela_valores_sem_desconto() -> None:
    store = Store()
    service = QuoteService(FakeOrdersUnitOfWork(store), quote_ttl=TTL)

    quote = await service.create_recharge_quote(
        customer_id=CUSTOMER,
        card_id=uuid.uuid4(),
        fare_profile="MEIA",
        amount=Decimal("120.00"),
        at=FIXED_NOW,
    )

    assert quote.subtotal == Decimal("120.00")
    assert quote.discount_amount == Decimal("0.00")
    assert quote.total == Decimal("120.00")
    assert quote.currency == "BRL"
    assert quote.fare_profile == "MEIA"
    assert quote.expires_at == FIXED_NOW + TTL
    assert len(quote.items) == 1
    assert store.state.quotes[quote.id] == quote


# --- create_order (§5, §11) ---------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_order_congela_valores_da_quote() -> None:
    store = Store()
    quote = make_quote(customer_id=CUSTOMER, total=Decimal("50.00"))
    store.state.quotes[quote.id] = quote

    order = await make_service(store).create_order(
        customer_id=CUSTOMER, quote_id=quote.id, idempotency_key="k1", at=FIXED_NOW
    )

    assert order.status is OrderStatus.DRAFT
    assert order.total == quote.total
    assert order.subtotal == quote.subtotal
    assert order.discount_amount == quote.discount_amount
    assert order.items == quote.items
    assert order.card_id == quote.card_id
    assert order.quote_id == quote.id
    assert order.requires_approval is False
    assert order.expires_at == FIXED_NOW + TTL
    assert order.cancellation_reason is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_order_congela_requires_approval_acima_do_limiar() -> None:
    """Congelado na criação: recalcular depois permitiria contornar (§5, §7)."""
    store = Store()
    quote = make_quote(customer_id=CUSTOMER, total=Decimal("250.00"))
    store.state.quotes[quote.id] = quote

    order = await make_service(store).create_order(
        customer_id=CUSTOMER, quote_id=quote.id, idempotency_key="k1", at=FIXED_NOW
    )

    assert order.requires_approval is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_order_registra_idempotencia_completa() -> None:
    store = Store()
    quote = make_quote(customer_id=CUSTOMER)
    store.state.quotes[quote.id] = quote

    order = await make_service(store).create_order(
        customer_id=CUSTOMER, quote_id=quote.id, idempotency_key="k1", at=FIXED_NOW
    )

    record = store.state.idempotency[(OPERATION_CREATE_ORDER, "k1")]
    assert record.status is IdempotencyStatus.COMPLETED
    assert record.resource_id == order.id
    assert record.completed_at == FIXED_NOW


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_da_mesma_key_devolve_o_mesmo_order() -> None:
    store = Store()
    quote = make_quote(customer_id=CUSTOMER)
    store.state.quotes[quote.id] = quote
    service = make_service(store)

    primeiro = await service.create_order(
        customer_id=CUSTOMER, quote_id=quote.id, idempotency_key="k1", at=FIXED_NOW
    )
    segundo = await service.create_order(
        customer_id=CUSTOMER, quote_id=quote.id, idempotency_key="k1", at=LATER
    )

    assert segundo.id == primeiro.id
    assert len(store.state.orders) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mesma_key_com_payload_diferente_conflita() -> None:
    store = Store()
    quote_a = make_quote(customer_id=CUSTOMER)
    quote_b = make_quote(customer_id=CUSTOMER)
    store.state.quotes[quote_a.id] = quote_a
    store.state.quotes[quote_b.id] = quote_b
    service = make_service(store)

    await service.create_order(
        customer_id=CUSTOMER, quote_id=quote_a.id, idempotency_key="k1", at=FIXED_NOW
    )

    with pytest.raises(IdempotencyConflictError):
        await service.create_order(
            customer_id=CUSTOMER, quote_id=quote_b.id, idempotency_key="k1", at=LATER
        )
    assert len(store.state.orders) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_quote_de_outro_cliente_nao_e_acessivel() -> None:
    """Mesma resposta para inexistente e alheia: anti-enumeração."""
    store = Store()
    quote = make_quote(customer_id=OTHER_CUSTOMER)
    store.state.quotes[quote.id] = quote
    service = make_service(store)

    with pytest.raises(QuoteNotAccessibleError):
        await service.create_order(
            customer_id=CUSTOMER, quote_id=quote.id, idempotency_key="k1", at=FIXED_NOW
        )

    with pytest.raises(QuoteNotAccessibleError):
        await service.create_order(
            customer_id=CUSTOMER,
            quote_id=uuid.uuid4(),
            idempotency_key="k2",
            at=FIXED_NOW,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_quote_expirada_nao_gera_order() -> None:
    store = Store()
    quote = make_quote(customer_id=CUSTOMER, expires_at=FIXED_NOW)
    store.state.quotes[quote.id] = quote

    with pytest.raises(QuoteExpiredError):
        await make_service(store).create_order(
            customer_id=CUSTOMER, quote_id=quote.id, idempotency_key="k1", at=FIXED_NOW
        )
    assert not store.state.orders


@pytest.mark.unit
@pytest.mark.asyncio
async def test_falha_local_desfaz_a_reivindicacao_da_key() -> None:
    """§11.2: reivindicação e efeito falham juntos — sem `IN_PROGRESS` órfão.

    Se a key sobrevivesse à falha, uma segunda tentativa legítima com a mesma
    key seria interpretada como replay e devolveria um recurso inexistente.
    """
    store = Store()
    quote = make_quote(customer_id=CUSTOMER, expires_at=FIXED_NOW)
    store.state.quotes[quote.id] = quote

    with pytest.raises(QuoteExpiredError):
        await make_service(store).create_order(
            customer_id=CUSTOMER, quote_id=quote.id, idempotency_key="k1", at=FIXED_NOW
        )

    assert (OPERATION_CREATE_ORDER, "k1") not in store.state.idempotency


@pytest.mark.unit
@pytest.mark.asyncio
async def test_quote_gera_no_maximo_um_order() -> None:
    """Um consentimento de valor não produz dois pedidos pagáveis (§4)."""
    store = Store()
    quote = make_quote(customer_id=CUSTOMER)
    store.state.quotes[quote.id] = quote
    service = make_service(store)

    await service.create_order(
        customer_id=CUSTOMER, quote_id=quote.id, idempotency_key="k1", at=FIXED_NOW
    )

    with pytest.raises(QuoteAlreadyConsumedError) as exc:
        await service.create_order(
            customer_id=CUSTOMER, quote_id=quote.id, idempotency_key="k2", at=LATER
        )
    assert exc.value.code == "INVALID_ORDER_STATE"
    assert len(store.state.orders) == 1


# --- confirm_order (§8) -------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirmacao_sem_aprovacao_nao_cria_approval() -> None:
    store = Store()
    order_id = await seed_order(store, total=Decimal("50.00"))

    confirmado = await make_service(store).confirm_order(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="c1", at=LATER
    )

    assert confirmado.status is OrderStatus.CONFIRMED
    assert not store.state.approvals


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirmacao_com_aprovacao_cria_approval_pendente_na_mesma_transacao() -> None:
    """Nunca existe Order em `REQUIRES_APPROVAL` sem `Approval` (§7, §8)."""
    store = Store()
    order_id = await seed_order(store, total=Decimal("250.00"))

    confirmado = await make_service(store).confirm_order(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="c1", at=LATER
    )

    assert confirmado.status is OrderStatus.REQUIRES_APPROVAL
    approvals = list(store.state.approvals.values())
    assert len(approvals) == 1
    assert approvals[0].order_id == order_id
    assert approvals[0].status is ApprovalStatus.PENDING
    assert approvals[0].requested_at == LATER
    assert approvals[0].decided_by is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_de_confirmacao_nao_cria_segunda_approval() -> None:
    store = Store()
    order_id = await seed_order(store, total=Decimal("250.00"))
    service = make_service(store)

    await service.confirm_order(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="c1", at=LATER
    )
    novamente = await service.confirm_order(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="c1", at=LATER
    )

    assert novamente.status is OrderStatus.REQUIRES_APPROVAL
    assert len(store.state.approvals) == 1
    assert store.state.idempotency[(OPERATION_CONFIRM_ORDER, "c1")].status is (
        IdempotencyStatus.COMPLETED
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_draft_expirado_nao_e_confirmavel_e_nao_deixa_key() -> None:
    store = Store()
    order_id = await seed_order(store)

    with pytest.raises(OrderExpiredError):
        await make_service(store).confirm_order(
            customer_id=CUSTOMER,
            order_id=order_id,
            idempotency_key="c1",
            at=FIXED_NOW + TTL,
        )

    assert store.state.orders[order_id].status is OrderStatus.DRAFT
    assert (OPERATION_CONFIRM_ORDER, "c1") not in store.state.idempotency


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_de_outro_cliente_nao_e_confirmavel() -> None:
    store = Store()
    order_id = await seed_order(store)

    with pytest.raises(OrderNotAccessibleError):
        await make_service(store).confirm_order(
            customer_id=OTHER_CUSTOMER, order_id=order_id, idempotency_key="c1", at=LATER
        )
    assert store.state.orders[order_id].status is OrderStatus.DRAFT


# --- cancelamento (§14) -------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cliente_cancela_draft() -> None:
    store = Store()
    order_id = await seed_order(store)

    cancelado = await make_service(store).cancel_order(
        customer_id=CUSTOMER, order_id=order_id, at=LATER
    )

    assert cancelado.status is OrderStatus.CANCELLED
    assert cancelado.cancellation_reason is CancellationReason.CUSTOMER_REQUEST


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancelamento_de_order_de_outro_cliente_e_recusado() -> None:
    store = Store()
    order_id = await seed_order(store)

    with pytest.raises(OrderNotAccessibleError):
        await make_service(store).cancel_order(
            customer_id=OTHER_CUSTOMER, order_id=order_id, at=LATER
        )


# --- expiração (§5.1) ---------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_expiracao_materializa_estado_de_draft_vencido() -> None:
    store = Store()
    order_id = await seed_order(store)

    expirado = await make_service(store).expire_draft(order_id=order_id, at=FIXED_NOW + TTL)

    assert expirado.status is OrderStatus.EXPIRED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_expiracao_de_draft_ainda_valido_e_recusada() -> None:
    store = Store()
    order_id = await seed_order(store)

    with pytest.raises(InvalidOrderStateError):
        await make_service(store).expire_draft(order_id=order_id, at=FIXED_NOW)


# --- decisão humana (§7) ------------------------------------------------


async def seed_awaiting_approval(store: Store) -> uuid.UUID:
    order_id = await seed_order(store, total=Decimal("250.00"))
    await make_service(store).confirm_order(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="c1", at=LATER
    )
    return order_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aprovacao_libera_o_order_e_registra_auditoria() -> None:
    store = Store()
    order_id = await seed_awaiting_approval(store)

    liberado = await make_service(store).approve_order(
        order_id=order_id, actor=ACTOR, idempotency_key="a1", at=LATER
    )

    assert liberado.status is OrderStatus.CONFIRMED
    approval = next(iter(store.state.approvals.values()))
    assert approval.status is ApprovalStatus.APPROVED
    assert approval.decided_by == ACTOR
    assert approval.decided_at == LATER


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rejeicao_cancela_com_motivo_de_rejeicao() -> None:
    """Nunca apresentado como cancelamento solicitado pelo cliente (§7)."""
    store = Store()
    order_id = await seed_awaiting_approval(store)

    cancelado = await make_service(store).reject_order(
        order_id=order_id, actor=ACTOR, idempotency_key="r1", at=LATER
    )

    assert cancelado.status is OrderStatus.CANCELLED
    assert cancelado.cancellation_reason is CancellationReason.APPROVAL_REJECTED
    approval = next(iter(store.state.approvals.values()))
    assert approval.status is ApprovalStatus.REJECTED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_de_aprovacao_e_idempotente() -> None:
    store = Store()
    order_id = await seed_awaiting_approval(store)
    service = make_service(store)

    await service.approve_order(order_id=order_id, actor=ACTOR, idempotency_key="a1", at=LATER)
    novamente = await service.approve_order(
        order_id=order_id, actor=ACTOR, idempotency_key="a1", at=LATER
    )

    assert novamente.status is OrderStatus.CONFIRMED
    approval = next(iter(store.state.approvals.values()))
    assert approval.decided_at == LATER


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redecisao_com_nova_key_e_recusada() -> None:
    """Terminal não volta a `PENDING` e não é redecidido (§7)."""
    store = Store()
    order_id = await seed_awaiting_approval(store)
    service = make_service(store)

    await service.approve_order(order_id=order_id, actor=ACTOR, idempotency_key="a1", at=LATER)

    with pytest.raises(InvalidApprovalStateError):
        await service.reject_order(order_id=order_id, actor=ACTOR, idempotency_key="r1", at=LATER)
    assert store.state.orders[order_id].status is OrderStatus.CONFIRMED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aprovacao_sem_approval_registrada_e_recusada() -> None:
    store = Store()
    order_id = await seed_order(store, total=Decimal("50.00"))
    await make_service(store).confirm_order(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="c1", at=LATER
    )

    with pytest.raises(ApprovalNotFoundError):
        await make_service(store).approve_order(
            order_id=order_id, actor=ACTOR, idempotency_key="a1", at=LATER
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aprovacao_de_order_inexistente_e_recusada() -> None:
    store = Store()

    with pytest.raises(OrderNotFoundError):
        await make_service(store).approve_order(
            order_id=uuid.uuid4(), actor=ACTOR, idempotency_key="a1", at=LATER
        )


# --- consulta ------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_consulta_filtra_por_titularidade() -> None:
    store = Store()
    order_id = await seed_order(store)
    service = make_service(store)

    assert (await service.get_order(customer_id=CUSTOMER, order_id=order_id)).id == order_id

    with pytest.raises(OrderNotAccessibleError):
        await service.get_order(customer_id=OTHER_CUSTOMER, order_id=order_id)
