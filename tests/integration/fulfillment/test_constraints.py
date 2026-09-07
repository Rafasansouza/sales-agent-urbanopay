"""Invariantes garantidas pelo banco (SPEC-005 §7.1, §19; ADR-012).

Cada teste escreve **direto nas tabelas**, sem passar pelo serviço. É
proposital: o que se prova aqui é que o banco recusa o estado inválido mesmo
que a camada de aplicação tenha um defeito. A constraint decisiva é
`uq_card_ledger_entries_recharge_per_order` — um crédito por Order.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.fulfillment.conftest import (
    FIXED_NOW,
    LATER,
    FulfillmentTestData,
    Scenario,
)
from urbanopay.modules.fulfillment.infrastructure.models import (
    CardLedgerEntryModel,
    FulfillmentModel,
    ReceiptModel,
)


def _fulfillment(
    cenario: Scenario,
    *,
    status: str = "PENDING",
    failure_reason: str | None = None,
    failure_class: str | None = None,
    completed_at: object = None,
    fulfillment_type: str = "RECHARGE",
    updated_at: object = None,
) -> FulfillmentModel:
    return FulfillmentModel(
        id=uuid.uuid4(),
        order_id=cenario.order_id,
        payment_id=cenario.payment_id,
        card_id=cenario.card_id,
        fulfillment_type=fulfillment_type,
        status=status,
        failure_reason=failure_reason,
        failure_class=failure_class,
        created_at=FIXED_NOW,
        updated_at=updated_at if updated_at is not None else FIXED_NOW,
        completed_at=completed_at,
    )


def _entry(
    cenario: Scenario,
    fulfillment_id: uuid.UUID,
    *,
    amount: Decimal = Decimal("50.00"),
    currency: str = "BRL",
    balance_before: Decimal = Decimal("0.00"),
    balance_after: Decimal | None = None,
    entry_type: str = "RECHARGE_CREDIT",
) -> CardLedgerEntryModel:
    return CardLedgerEntryModel(
        id=uuid.uuid4(),
        fulfillment_id=fulfillment_id,
        order_id=cenario.order_id,
        card_id=cenario.card_id,
        entry_type=entry_type,
        amount=amount,
        currency=currency,
        balance_before=balance_before,
        balance_after=balance_after if balance_after is not None else balance_before + amount,
        created_at=FIXED_NOW,
    )


def _receipt(
    cenario: Scenario,
    fulfillment_id: uuid.UUID,
    *,
    card_last4: str = "4821",
    amount: Decimal = Decimal("50.00"),
    document_kind: str = "SIMULATED_NON_FISCAL",
    disclaimer_version: str = "1",
) -> ReceiptModel:
    assert cenario.payment_id is not None
    return ReceiptModel(
        id=uuid.uuid4(),
        order_id=cenario.order_id,
        payment_id=cenario.payment_id,
        fulfillment_id=fulfillment_id,
        card_last4=card_last4,
        amount=amount,
        currency="BRL",
        operation_type="RECHARGE",
        document_kind=document_kind,
        disclaimer_version=disclaimer_version,
        issued_at=FIXED_NOW,
    )


async def _persist(session_factory: async_sessionmaker[AsyncSession], *models: object) -> None:
    async with session_factory() as session:
        for model in models:
            session.add(model)
            await session.flush()
        await session.commit()


# --- a invariante central ------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_um_recharge_credit_por_order(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`uq_card_ledger_entries_recharge_per_order`: barreira final."""
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario)
    await _persist(session_factory, fulfillment, _entry(cenario, fulfillment.id))

    with pytest.raises(IntegrityError):
        await _persist(session_factory, _entry(cenario, fulfillment.id))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_um_fulfillment_por_order(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()
    await _persist(session_factory, _fulfillment(cenario))

    with pytest.raises(IntegrityError):
        await _persist(session_factory, _fulfillment(cenario))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_um_comprovante_por_order(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario, status="COMPLETED", completed_at=FIXED_NOW)
    await _persist(session_factory, fulfillment, _receipt(cenario, fulfillment.id))

    with pytest.raises(IntegrityError):
        await _persist(session_factory, _receipt(cenario, fulfillment.id))


# --- aritmética e domínio do ledger --------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_aritmetica_do_ledger_e_verificada_pelo_banco(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ck_card_ledger_entries_balance_arithmetic`."""
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario)
    await _persist(session_factory, fulfillment)

    with pytest.raises(IntegrityError):
        await _persist(
            session_factory,
            _entry(
                cenario,
                fulfillment.id,
                amount=Decimal("50.00"),
                balance_before=Decimal("10.00"),
                balance_after=Decimal("70.00"),  # deveria ser 60,00
            ),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_valor_do_ledger_precisa_ser_positivo(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario)
    await _persist(session_factory, fulfillment)

    with pytest.raises(IntegrityError):
        await _persist(session_factory, _entry(cenario, fulfillment.id, amount=Decimal("0.00")))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_saldo_negativo_no_ledger_e_recusado(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario)
    await _persist(session_factory, fulfillment)

    with pytest.raises(IntegrityError):
        await _persist(
            session_factory,
            _entry(
                cenario,
                fulfillment.id,
                amount=Decimal("10.00"),
                balance_before=Decimal("-5.00"),
                balance_after=Decimal("5.00"),
            ),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_moeda_do_ledger_e_restrita_a_brl(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario)
    await _persist(session_factory, fulfillment)

    with pytest.raises(IntegrityError):
        await _persist(session_factory, _entry(cenario, fulfillment.id, currency="USD"))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tipo_de_movimento_fora_do_dominio_e_recusado(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """O MVP credita e não debita: `RECHARGE_DEBIT` não existe."""
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario)
    await _persist(session_factory, fulfillment)

    with pytest.raises(IntegrityError):
        await _persist(
            session_factory, _entry(cenario, fulfillment.id, entry_type="RECHARGE_DEBIT")
        )


# --- coerência de estado do Fulfillment ----------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_fora_do_dominio_e_recusado(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()

    with pytest.raises(IntegrityError):
        await _persist(session_factory, _fulfillment(cenario, status="CONCLUIDO"))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_completed_exige_completed_at(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ck_fulfillments_completed_at_matches_status`, nos dois sentidos."""
    cenario = await data.add_scenario()

    with pytest.raises(IntegrityError):
        await _persist(
            session_factory, _fulfillment(cenario, status="COMPLETED", completed_at=None)
        )

    outro = await data.add_scenario()
    with pytest.raises(IntegrityError):
        # `completed_at` sem estar COMPLETED também é recusado.
        await _persist(
            session_factory, _fulfillment(outro, status="PENDING", completed_at=FIXED_NOW)
        )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["FAILED", "RECONCILIATION_REQUIRED"])
async def test_estado_de_falha_exige_motivo_e_classe(
    data: FulfillmentTestData,
    session_factory: async_sessionmaker[AsyncSession],
    status: str,
) -> None:
    """Registro pela metade não serve para trilha de auditoria financeira."""
    cenario = await data.add_scenario()

    with pytest.raises(IntegrityError):
        await _persist(session_factory, _fulfillment(cenario, status=status))

    outro = await data.add_scenario()
    with pytest.raises(IntegrityError):
        # Motivo sem classe também é recusado.
        await _persist(
            session_factory,
            _fulfillment(outro, status=status, failure_reason="MOTIVO"),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_metadados_de_falha_exigem_estado_de_falha(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()

    with pytest.raises(IntegrityError):
        await _persist(
            session_factory,
            _fulfillment(
                cenario,
                status="PENDING",
                failure_reason="MOTIVO",
                failure_class="RETRYABLE",
            ),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_classe_de_falha_fora_do_dominio_e_recusada(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()

    with pytest.raises(IntegrityError):
        await _persist(
            session_factory,
            _fulfillment(
                cenario,
                status="FAILED",
                failure_reason="MOTIVO",
                failure_class="TALVEZ",
            ),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_timestamps_incoerentes_sao_recusados(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`updated_at >= created_at` e `completed_at >= created_at`."""
    cenario = await data.add_scenario()

    with pytest.raises(IntegrityError):
        await _persist(
            session_factory,
            _fulfillment(cenario, updated_at=FIXED_NOW - timedelta(hours=1)),
        )

    outro = await data.add_scenario()
    with pytest.raises(IntegrityError):
        await _persist(
            session_factory,
            _fulfillment(
                outro,
                status="COMPLETED",
                completed_at=FIXED_NOW - timedelta(hours=1),
                updated_at=LATER,
            ),
        )


# --- comprovante ---------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_comprovante_exige_ultimos_quatro_digitos_numericos(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario, status="COMPLETED", completed_at=FIXED_NOW)
    await _persist(session_factory, fulfillment)

    with pytest.raises(IntegrityError):
        await _persist(session_factory, _receipt(cenario, fulfillment.id, card_last4="48X1"))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_comprovante_e_sempre_simulado(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """O banco recusa qualquer natureza que não seja simulada/não fiscal."""
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario, status="COMPLETED", completed_at=FIXED_NOW)
    await _persist(session_factory, fulfillment)

    with pytest.raises(IntegrityError):
        await _persist(
            session_factory,
            _receipt(cenario, fulfillment.id, document_kind="NFE"),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_comprovante_exige_versao_de_aviso(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario, status="COMPLETED", completed_at=FIXED_NOW)
    await _persist(session_factory, fulfillment)

    with pytest.raises(IntegrityError):
        await _persist(
            session_factory,
            _receipt(cenario, fulfillment.id, disclaimer_version="   "),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_comprovante_com_valor_nao_positivo_e_recusado(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario()
    fulfillment = _fulfillment(cenario, status="COMPLETED", completed_at=FIXED_NOW)
    await _persist(session_factory, fulfillment)

    with pytest.raises(IntegrityError):
        await _persist(
            session_factory,
            _receipt(cenario, fulfillment.id, amount=Decimal("0.00")),
        )


# --- saldo do cartão -----------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_saldo_do_cartao_nunca_fica_negativo(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ck_cards_balance_non_negative`, herdada da SPEC-002."""
    import sqlalchemy as sa

    from urbanopay.modules.cards.infrastructure.models import CardModel

    cenario = await data.add_scenario(balance=Decimal("10.00"))

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            await session.execute(
                sa.update(CardModel)
                .where(CardModel.id == cenario.card_id)
                .values(balance=Decimal("-1.00"))
            )
            await session.commit()
