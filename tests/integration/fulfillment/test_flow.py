"""Fulfillment contra PostgreSQL real (SPEC-005 §6, §8.1, §11, §12.1, §13).

Prova a cadeia inteira atravessando persistência de verdade: `Order PAID` →
crédito → ledger → `Order COMPLETED`, com `Decimal` exato e rollback atômico.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.integration.fulfillment.conftest import LATER, FulfillmentTestData
from urbanopay.modules.fulfillment.application.services import (
    FulfillmentRecoveryService,
    FulfillmentService,
)
from urbanopay.modules.fulfillment.domain.enums import DocumentKind, FulfillmentStatus
from urbanopay.modules.fulfillment.domain.errors import (
    EffectConflictError,
    OrderNotPaidError,
    ReceiptNotAvailableError,
    ReconciliationRequiredError,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_pago_credita_e_conclui(
    data: FulfillmentTestData, fulfillment_service: FulfillmentService
) -> None:
    cenario = await data.add_scenario(total=Decimal("50.00"), balance=Decimal("21.50"))

    resultado = await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    assert resultado.fulfillment.status is FulfillmentStatus.COMPLETED
    assert resultado.fulfillment.payment_id == cenario.payment_id
    assert resultado.ledger_entry.amount == Decimal("50.00")
    assert resultado.ledger_entry.balance_before == Decimal("21.50")
    assert resultado.ledger_entry.balance_after == Decimal("71.50")

    # Saldo atualizado no banco, com escala preservada.
    saldo = await data.balance_of(cenario.card_id)
    assert saldo == Decimal("71.50")
    assert str(saldo) == "71.50"

    assert await data.count_ledger(cenario.order_id) == 1
    assert await data.count_receipts(cenario.order_id) == 1
    assert await data.order_status(cenario.order_id) == "COMPLETED"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_valor_creditado_e_o_total_do_order(
    data: FulfillmentTestData, fulfillment_service: FulfillmentService
) -> None:
    """A tarifa não é recalculada; o crédito é exatamente `order.total`."""
    cenario = await data.add_scenario(total=Decimal("137.45"), balance=Decimal("0.00"))

    resultado = await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    assert resultado.ledger_entry.amount == cenario.total
    assert await data.balance_of(cenario.card_id) == Decimal("137.45")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_replay_nao_credita_de_novo(
    data: FulfillmentTestData, fulfillment_service: FulfillmentService
) -> None:
    cenario = await data.add_scenario(total=Decimal("40.00"), balance=Decimal("10.00"))

    primeiro = await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)
    segundo = await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    assert segundo.replayed is True
    assert segundo.ledger_entry.id == primeiro.ledger_entry.id
    assert segundo.receipt.id == primeiro.receipt.id
    assert await data.count_ledger(cenario.order_id) == 1
    assert await data.count_receipts(cenario.order_id) == 1
    # Creditado UMA vez.
    assert await data.balance_of(cenario.card_id) == Decimal("50.00")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_nao_pago_produz_zero_efeito(
    data: FulfillmentTestData, fulfillment_service: FulfillmentService
) -> None:
    cenario = await data.add_scenario(order_status="CONFIRMED", balance=Decimal("10.00"))

    with pytest.raises(OrderNotPaidError):
        await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    assert await data.count_ledger(cenario.order_id) == 0
    assert await data.count_fulfillments(cenario.order_id) == 0
    assert await data.balance_of(cenario.card_id) == Decimal("10.00")
    assert await data.order_status(cenario.order_id) == "CONFIRMED"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_pago_sem_payment_aprovado_vai_para_reconciliacao(
    data: FulfillmentTestData, fulfillment_service: FulfillmentService
) -> None:
    """Inconsistência de dados: estado conhecido, zero efeito (§11.1)."""
    cenario = await data.add_scenario(payment_status=None, balance=Decimal("10.00"))

    with pytest.raises(ReconciliationRequiredError):
        await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    assert await data.count_ledger(cenario.order_id) == 0
    assert await data.count_receipts(cenario.order_id) == 0
    assert await data.balance_of(cenario.card_id) == Decimal("10.00")
    assert await data.fulfillment_status(cenario.order_id) == "RECONCILIATION_REQUIRED"
    assert await data.order_status(cenario.order_id) == "FULFILLMENT_FAILED"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("card_status", ["BLOCKED", "EXPIRED", "CANCELLED"])
async def test_cartao_nao_ativo_vai_para_reconciliacao(
    data: FulfillmentTestData,
    fulfillment_service: FulfillmentService,
    card_status: str,
) -> None:
    """Pago e não entregável: zero crédito, zero estorno, estado auditável."""
    cenario = await data.add_scenario(card_status=card_status, balance=Decimal("7.00"))

    with pytest.raises(ReconciliationRequiredError):
        await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    assert await data.count_ledger(cenario.order_id) == 0
    assert await data.count_receipts(cenario.order_id) == 0
    assert await data.balance_of(cenario.card_id) == Decimal("7.00")
    assert await data.fulfillment_status(cenario.order_id) == "RECONCILIATION_REQUIRED"
    assert await data.order_status(cenario.order_id) == "FULFILLMENT_FAILED"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_payment_pendente_nao_autoriza_fulfillment(
    data: FulfillmentTestData, fulfillment_service: FulfillmentService
) -> None:
    cenario = await data.add_scenario(payment_status="PENDING", balance=Decimal("5.00"))

    with pytest.raises(ReconciliationRequiredError):
        await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    assert await data.count_ledger(cenario.order_id) == 0
    assert await data.balance_of(cenario.card_id) == Decimal("5.00")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_comprovante_disponivel_somente_apos_conclusao(
    data: FulfillmentTestData, fulfillment_service: FulfillmentService
) -> None:
    cenario = await data.add_scenario(total=Decimal("80.00"))

    with pytest.raises(ReceiptNotAvailableError):
        await fulfillment_service.get_receipt(
            customer_id=cenario.customer_id, order_id=cenario.order_id
        )

    await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    receipt = await fulfillment_service.get_receipt(
        customer_id=cenario.customer_id, order_id=cenario.order_id
    )
    assert receipt.document_kind is DocumentKind.SIMULATED_NON_FISCAL
    assert receipt.amount == Decimal("80.00")
    assert receipt.masked_card == "****4821"
    assert receipt.disclaimer_version


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reentrada_apos_reconciliacao_conclui_a_entrega(
    data: FulfillmentTestData,
    fulfillment_service: FulfillmentService,
    session_factory: object,
) -> None:
    """Cartão reativado permite concluir, sem nova cobrança (§5.1)."""
    import sqlalchemy as sa

    from urbanopay.modules.cards.infrastructure.models import CardModel

    cenario = await data.add_scenario(
        card_status="BLOCKED", total=Decimal("30.00"), balance=Decimal("0.00")
    )

    with pytest.raises(ReconciliationRequiredError):
        await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    # Correção administrativa do dado.
    async with session_factory() as session:  # type: ignore[operator]
        await session.execute(
            sa.update(CardModel).where(CardModel.id == cenario.card_id).values(status="ACTIVE")
        )
        await session.commit()

    resultado = await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    assert resultado.fulfillment.status is FulfillmentStatus.COMPLETED
    assert resultado.fulfillment.failure_reason is None
    assert await data.count_ledger(cenario.order_id) == 1
    assert await data.count_fulfillments(cenario.order_id) == 1
    assert await data.balance_of(cenario.card_id) == Decimal("30.00")
    assert await data.order_status(cenario.order_id) == "COMPLETED"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_consultas_de_recuperacao(
    data: FulfillmentTestData,
    fulfillment_service: FulfillmentService,
    recovery_service: FulfillmentRecoveryService,
) -> None:
    cenario = await data.add_scenario()

    antes = await recovery_service.build_report(limit=500)
    assert cenario.order_id in antes.eligible_orders
    assert cenario.order_id not in antes.completed_without_ledger

    await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    depois = await recovery_service.build_report(limit=500)
    assert cenario.order_id not in depois.eligible_orders
    assert cenario.order_id not in depois.completed_without_ledger
    assert cenario.order_id not in depois.ledger_without_completed


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fulfillment_completed_sem_ledger_e_detectado_e_nao_credita(
    data: FulfillmentTestData,
    fulfillment_service: FulfillmentService,
    recovery_service: FulfillmentRecoveryService,
    session_factory: object,
) -> None:
    """Inconsistência grave: reporta, recusa e não regride (§12.1)."""
    import sqlalchemy as sa

    from urbanopay.modules.fulfillment.infrastructure.models import CardLedgerEntryModel

    cenario = await data.add_scenario(total=Decimal("25.00"), balance=Decimal("0.00"))
    await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    # Simula a inconsistência removendo o ledger — o que só um defeito ou uma
    # intervenção manual produziria.
    async with session_factory() as session:  # type: ignore[operator]
        await session.execute(
            sa.delete(CardLedgerEntryModel).where(CardLedgerEntryModel.order_id == cenario.order_id)
        )
        await session.commit()

    relatorio = await recovery_service.build_report(limit=500)
    assert cenario.order_id in relatorio.completed_without_ledger
    assert relatorio.has_grave_inconsistency

    # Nova chamada NÃO credita: recusa com conflito de efeito.
    with pytest.raises(EffectConflictError):
        await fulfillment_service.fulfill_order(order_id=cenario.order_id, at=LATER)

    assert await data.count_ledger(cenario.order_id) == 0
    assert await data.fulfillment_status(cenario.order_id) == "COMPLETED"
    # O saldo creditado na primeira execução permanece — nada foi somado de novo.
    assert await data.balance_of(cenario.card_id) == Decimal("25.00")
