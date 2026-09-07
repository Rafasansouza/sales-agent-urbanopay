"""Repositories do Fare Engine contra PostgreSQL real, com o seed oficial."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.fare.conftest import FareTestData
from tests.unit.fare.fakes import (
    FIXED_NOW,
    OFFICIAL_BUS_FARES,
    OFFICIAL_METRO_FARES,
)
from urbanopay.modules.fare.domain.enums import FareProfile, TransportMode, TripType
from urbanopay.modules.fare.domain.value_objects import FareLookupKey
from urbanopay.modules.fare.infrastructure.repositories import (
    SqlAlchemyFareRepository,
    SqlAlchemyFareRuleRepository,
)

ALL_KEYS = frozenset(
    {FareLookupKey(TransportMode.BUS, line) for line in OFFICIAL_BUS_FARES}
    | {FareLookupKey(TransportMode.METRO, None)}
)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [FareProfile.INTEGRAL, FareProfile.MEIA])
async def test_todas_as_tarifas_oficiais_estao_carregadas(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
    profile: FareProfile,
) -> None:
    """Valida que a migration de dados carregou o conjunto completo derivado
    de SPEC-001 §2 — 6 chaves por perfil, 12 tarifas no total."""
    async with session_factory() as session:
        repo = SqlAlchemyFareRepository(session)
        fares = await repo.find_active_fares(profile, ALL_KEYS, FIXED_NOW)

    assert len(fares) == len(ALL_KEYS)

    index = 0 if profile is FareProfile.INTEGRAL else 1
    for line, amounts in OFFICIAL_BUS_FARES.items():
        fare = fares[FareLookupKey(TransportMode.BUS, line)]
        assert fare.amount == Decimal(amounts[index])
        assert type(fare.amount) is Decimal
        assert fare.fare_profile is profile

    metro_fare = fares[FareLookupKey(TransportMode.METRO, None)]
    assert metro_fare.amount == Decimal(OFFICIAL_METRO_FARES[index])
    assert type(metro_fare.amount) is Decimal


@pytest.mark.integration
@pytest.mark.asyncio
async def test_regra_oficial_de_integracao_esta_carregada(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyFareRuleRepository(session)
        rule = await repo.find_active_rule(TripType.INTEGRATION, FIXED_NOW)

    assert rule is not None
    assert rule.discount_percentage == Decimal("15.00")
    assert type(rule.discount_percentage) is Decimal
    assert rule.valid_until is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_known_bus_lines_distingue_linhas_existentes(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyFareRepository(session)
        known = await repo.known_bus_lines(frozenset({"101", "999"}))

    assert known == frozenset({"101"})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_consulta_por_vigencia_retorna_tarifa_do_periodo(
    fare_data: FareTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Tarifas históricas continuam consultáveis pela data (SPEC-001 §8, §12)."""
    old_id = await fare_data.add_fare(
        mode="BUS",
        line_code="808",
        fare_profile="MEIA",
        amount="5.00",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_until=datetime(2021, 1, 1, tzinfo=UTC),
    )
    new_id = await fare_data.add_fare(
        mode="BUS",
        line_code="808",
        fare_profile="MEIA",
        amount="6.50",
        valid_from=datetime(2021, 1, 1, tzinfo=UTC),
        valid_until=datetime(2022, 1, 1, tzinfo=UTC),
    )
    key = FareLookupKey(TransportMode.BUS, "808")

    async with session_factory() as session:
        repo = SqlAlchemyFareRepository(session)

        at_2020 = await repo.find_active_fares(
            FareProfile.MEIA, frozenset({key}), datetime(2020, 6, 1, tzinfo=UTC)
        )
        assert at_2020[key].id == old_id
        assert at_2020[key].amount == Decimal("5.00")

        at_2021 = await repo.find_active_fares(
            FareProfile.MEIA, frozenset({key}), datetime(2021, 6, 1, tzinfo=UTC)
        )
        assert at_2021[key].id == new_id
        assert at_2021[key].amount == Decimal("6.50")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_nao_retorna_tarifa_fora_de_vigencia(
    fare_data: FareTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await fare_data.add_fare(
        mode="BUS",
        line_code="809",
        fare_profile="MEIA",
        amount="4.00",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_until=datetime(2021, 1, 1, tzinfo=UTC),
    )
    key = FareLookupKey(TransportMode.BUS, "809")

    async with session_factory() as session:
        repo = SqlAlchemyFareRepository(session)

        before = await repo.find_active_fares(
            FareProfile.MEIA, frozenset({key}), datetime(2019, 6, 1, tzinfo=UTC)
        )
        after = await repo.find_active_fares(
            FareProfile.MEIA, frozenset({key}), datetime(2021, 6, 1, tzinfo=UTC)
        )

    assert before == {}
    assert after == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chaves_vazias_nao_consultam(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyFareRepository(session)
        assert await repo.find_active_fares(FareProfile.MEIA, frozenset(), FIXED_NOW) == {}
        assert await repo.known_bus_lines(frozenset()) == frozenset()
