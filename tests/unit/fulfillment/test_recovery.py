"""Consultas de recuperação e consistência (SPEC-005 §12.1, §20.1).

O ponto central: **detecção, nunca reparo**. Nenhuma função aqui aplica
efeito financeiro, e o relatório vazio é a expectativa em operação normal.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from tests.unit.fulfillment.builders import (
    LATER,
    make_card,
    make_fulfillment,
    make_ledger_entry,
    make_order,
    make_payment,
)
from tests.unit.fulfillment.fakes import (
    FakeFulfillmentRecoveryPort,
    FakeFulfillmentUnitOfWork,
    Store,
)
from urbanopay.modules.fulfillment.application.services import (
    FulfillmentRecoveryService,
    FulfillmentService,
)
from urbanopay.modules.fulfillment.domain.enums import FulfillmentStatus
from urbanopay.modules.orders.domain.enums import OrderStatus

CUSTOMER = uuid.UUID("00000000-0000-4000-8000-0000000000c1")


def make_recovery(store: Store) -> FulfillmentRecoveryService:
    return FulfillmentRecoveryService(FakeFulfillmentRecoveryPort(store))


def seed_paid_order(store: Store, *, total: Decimal = Decimal("50.00")) -> uuid.UUID:
    card = make_card(customer_id=CUSTOMER)
    order = make_order(customer_id=CUSTOMER, card_id=card.id, status=OrderStatus.PAID, total=total)
    payment = make_payment(order_id=order.id, amount=total)
    store.state.cards[card.id] = card
    store.state.orders[order.id] = order
    store.state.payments[payment.id] = payment
    return order.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_relatorio_vazio_quando_nada_ha_a_reconciliar() -> None:
    store = Store()
    relatorio = await make_recovery(store).build_report()

    assert relatorio.is_clean
    assert not relatorio.has_grave_inconsistency


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_pago_sem_fulfillment_e_elegivel() -> None:
    store = Store()
    order_id = seed_paid_order(store)

    relatorio = await make_recovery(store).build_report()

    assert relatorio.eligible_orders == [order_id]
    assert not relatorio.has_grave_inconsistency


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_concluido_sai_da_lista_de_elegiveis() -> None:
    store = Store()
    order_id = seed_paid_order(store)
    await FulfillmentService(FakeFulfillmentUnitOfWork(store)).fulfill_order(
        order_id=order_id, at=LATER
    )

    relatorio = await make_recovery(store).build_report()

    assert relatorio.is_clean


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_em_reconciliacao_continua_elegivel() -> None:
    """Reentrada por comando explícito precisa de um caminho de descoberta."""
    store = Store()
    card = make_card(customer_id=CUSTOMER)
    order = make_order(customer_id=CUSTOMER, card_id=card.id, status=OrderStatus.FULFILLMENT_FAILED)
    store.state.cards[card.id] = card
    store.state.orders[order.id] = order
    fulfillment = make_fulfillment(
        order_id=order.id,
        card_id=card.id,
        status=FulfillmentStatus.RECONCILIATION_REQUIRED,
    )
    store.state.fulfillments[fulfillment.id] = fulfillment

    relatorio = await make_recovery(store).build_report()

    assert relatorio.eligible_orders == [order.id]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fulfillment_completed_sem_ledger_e_inconsistencia_grave() -> None:
    """O achado que não pode existir: concluído sem prova de efeito."""
    store = Store()
    order_id = seed_paid_order(store)
    order = store.state.orders[order_id]
    fulfillment = make_fulfillment(
        order_id=order_id, card_id=order.card_id, status=FulfillmentStatus.COMPLETED
    )
    store.state.fulfillments[fulfillment.id] = fulfillment

    relatorio = await make_recovery(store).build_report()

    assert relatorio.completed_without_ledger == [order_id]
    assert relatorio.has_grave_inconsistency
    assert not relatorio.is_clean
    # Detecção não repara: nenhum ledger foi criado pela consulta.
    assert not store.state.ledger


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ledger_sem_fulfillment_concluido_e_detectado() -> None:
    """O efeito aconteceu: o encerramento vem da evidência, não de novo crédito."""
    store = Store()
    order_id = seed_paid_order(store)
    order = store.state.orders[order_id]
    fulfillment = make_fulfillment(
        order_id=order_id, card_id=order.card_id, status=FulfillmentStatus.PROCESSING
    )
    store.state.fulfillments[fulfillment.id] = fulfillment
    entry = make_ledger_entry(
        order_id=order_id, card_id=order.card_id, fulfillment_id=fulfillment.id
    )
    store.state.ledger[entry.id] = entry

    relatorio = await make_recovery(store).build_report()

    assert relatorio.ledger_without_completed == [order_id]
    assert len(store.state.ledger) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_relatorio_respeita_o_limite() -> None:
    store = Store()
    for _ in range(5):
        seed_paid_order(store)

    relatorio = await make_recovery(store).build_report(limit=2)

    assert len(relatorio.eligible_orders) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_servico_de_recuperacao_nao_expoe_escrita() -> None:
    """Somente leitura: nada aqui pode aplicar efeito financeiro."""
    import inspect

    publicos = [
        nome
        for nome, _ in inspect.getmembers(FulfillmentRecoveryService, inspect.isfunction)
        if not nome.startswith("_")
    ]

    assert publicos == ["build_report"]
