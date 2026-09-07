"""FareService fim a fim contra PostgreSQL: dados efetivamente carregados do
banco, matemática no domínio (SPEC-001 §6, §12)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.unit.fare.fakes import FIXED_NOW
from urbanopay.modules.fare.application.services import FareService, SegmentInput
from urbanopay.modules.fare.domain.enums import TripType
from urbanopay.modules.fare.domain.errors import (
    FareLineNotFoundError,
    FareNotAvailableError,
)
from urbanopay.modules.fare.infrastructure.models import FareModel, FareRuleModel
from urbanopay.modules.fare.infrastructure.repositories import (
    SqlAlchemyFareRepository,
    SqlAlchemyFareRuleRepository,
)


def _service(session: AsyncSession) -> FareService:
    """Composição real: sessão → repositories → serviço de aplicação."""
    return FareService(
        fares=SqlAlchemyFareRepository(session),
        fare_rules=SqlAlchemyFareRuleRepository(session),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_integracao_meia_303_metro_com_dados_do_banco(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """O caso de referência da SPEC (§10, §12): 303+METRO MEIA = 7.65."""
    async with session_factory() as session:
        result = await _service(session).calculate_trip_fare(
            "MEIA",
            [SegmentInput(mode="BUS", line_code="303"), SegmentInput(mode="METRO")],
            at=FIXED_NOW,
        )

        # Breakdown completo, auditável contra os registros reais do banco.
        seeded_bus_id = (
            await session.execute(
                sa.select(FareModel.id).where(
                    FareModel.mode == "BUS",
                    FareModel.line_code == "303",
                    FareModel.fare_profile == "MEIA",
                )
            )
        ).scalar_one()
        seeded_rule_id = (
            await session.execute(
                sa.select(FareRuleModel.id).where(FareRuleModel.trip_type == "INTEGRATION")
            )
        ).scalar_one()

    assert result.trip_type is TripType.INTEGRATION
    assert result.subtotal == Decimal("9.00")
    assert result.discount is not None
    assert result.discount.percentage == Decimal("15.00")
    assert result.discount.amount == Decimal("1.35")
    assert result.discount.rule_id == seeded_rule_id
    assert result.total == Decimal("7.65")
    assert result.currency == "BRL"
    assert result.reference_datetime == FIXED_NOW
    assert result.segments[0].fare_id == seeded_bus_id
    assert result.segments[0].fare_amount == Decimal("4.00")
    assert result.segments[1].fare_amount == Decimal("5.00")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_common_integral_101_303_sem_desconto(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await _service(session).calculate_trip_fare(
            "INTEGRAL",
            [SegmentInput(mode="BUS", line_code="101"), SegmentInput(mode="BUS", line_code="303")],
            at=FIXED_NOW,
        )

    assert result.trip_type is TripType.COMMON
    assert result.subtotal == Decimal("14.00")
    assert result.discount is None
    assert result.total == Decimal("14.00")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_linha_999_contra_o_banco(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(FareLineNotFoundError):
            await _service(session).calculate_trip_fare(
                "INTEGRAL", [SegmentInput(mode="BUS", line_code="999")], at=FIXED_NOW
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_antes_da_vigencia_inicial_ficticia(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Antes de 2026-01-01Z (vigência fictícia aprovada do MVP) não há tarifa."""
    async with session_factory() as session:
        with pytest.raises(FareNotAvailableError):
            await _service(session).calculate_trip_fare(
                "INTEGRAL",
                [SegmentInput(mode="BUS", line_code="101")],
                at=datetime(2020, 1, 1, tzinfo=UTC),
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_metro_sem_vigencia_e_not_available_nunca_line_not_found(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(FareNotAvailableError):
            await _service(session).calculate_trip_fare(
                "MEIA", [SegmentInput(mode="METRO")], at=datetime(2020, 1, 1, tzinfo=UTC)
            )
