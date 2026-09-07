"""Constraints físicas das tabelas do Fare Engine, violadas de propósito.

Cada invariante crítica ganhou proteção no PostgreSQL (ADR-004, ADR-012);
estes testes provam que a proteção existe de verdade, incluindo as EXCLUDE
constraints de não-sobreposição de vigência.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.fare.conftest import FareTestData
from urbanopay.modules.fare.infrastructure.models import FareModel, FareRuleModel

# Janela futura que nunca cruza a vigência dos dados sintéticos históricos.
FUTURE_2030 = datetime(2030, 1, 1, tzinfo=UTC)
FUTURE_2031 = datetime(2031, 1, 1, tzinfo=UTC)


def _fare(**overrides: object) -> FareModel:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "mode": "BUS",
        "line_code": "902",
        "fare_profile": "INTEGRAL",
        "amount": Decimal("5.00"),
        "valid_from": FUTURE_2030,
        "valid_until": FUTURE_2031,
    }
    values.update(overrides)
    return FareModel(**values)


async def _expect_violation(
    session_factory: async_sessionmaker[AsyncSession],
    instance: FareModel | FareRuleModel,
    constraint: str,
) -> None:
    async with session_factory() as session:
        session.add(instance)
        with pytest.raises(IntegrityError) as excinfo:
            await session.commit()
        await session.rollback()
    assert constraint in str(excinfo.value)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        # line_code=None mantém `bus_requires_line` satisfeita (TRAIN != BUS),
        # isolando a violação em `mode_valid`.
        pytest.param(
            {"mode": "TRAIN", "line_code": None}, "ck_fares_mode_valid", id="mode-invalido"
        ),
        pytest.param({"fare_profile": "GRATUITO"}, "ck_fares_profile_valid", id="perfil-invalido"),
        pytest.param(
            {"amount": Decimal("-0.01")}, "ck_fares_amount_non_negative", id="amount-negativo"
        ),
        pytest.param({"line_code": None}, "ck_fares_bus_requires_line", id="bus-sem-linha"),
        pytest.param(
            {"mode": "METRO", "line_code": "L1"},
            "ck_fares_bus_requires_line",
            id="metro-com-linha",
        ),
        pytest.param({"line_code": "   "}, "ck_fares_line_code_not_blank", id="linha-em-branco"),
        pytest.param(
            {"valid_from": FUTURE_2031, "valid_until": FUTURE_2030},
            "ck_fares_validity_order",
            id="vigencia-invertida",
        ),
    ],
)
async def test_constraints_de_fares(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
    overrides: dict[str, object],
    constraint: str,
) -> None:
    await _expect_violation(session_factory, _fare(**overrides), constraint)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sobreposicao_com_tarifa_oficial_e_rejeitada(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A tarifa oficial da linha 101 tem vigência aberta: qualquer novo período
    para a mesma chave conflita — SPEC-001 §8 materializada em EXCLUDE."""
    await _expect_violation(
        session_factory,
        _fare(line_code="101", fare_profile="INTEGRAL", amount=Decimal("7.00")),
        "ex_fares_no_overlapping_validity",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sobreposicao_entre_periodos_proprios_e_rejeitada(
    fare_data: FareTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await fare_data.add_fare(
        mode="BUS",
        line_code="901",
        fare_profile="INTEGRAL",
        amount="5.00",
        valid_from=FUTURE_2030,
        valid_until=None,
    )
    await _expect_violation(
        session_factory,
        _fare(line_code="901", valid_from=FUTURE_2031, valid_until=None),
        "ex_fares_no_overlapping_validity",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mesmo_periodo_com_perfis_diferentes_nao_conflita(
    fare_data: FareTestData,
) -> None:
    """A exclusão é por (modo, linha, perfil): perfis distintos coexistem."""
    await fare_data.add_fare(
        mode="BUS",
        line_code="903",
        fare_profile="INTEGRAL",
        amount="5.00",
        valid_from=FUTURE_2030,
        valid_until=FUTURE_2031,
    )
    await fare_data.add_fare(
        mode="BUS",
        line_code="903",
        fare_profile="MEIA",
        amount="2.50",
        valid_from=FUTURE_2030,
        valid_until=FUTURE_2031,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_periodos_adjacentes_nao_conflitam(fare_data: FareTestData) -> None:
    """Intervalos semiabertos [from, until): o encontro exato não sobrepõe."""
    await fare_data.add_fare(
        mode="BUS",
        line_code="904",
        fare_profile="INTEGRAL",
        amount="5.00",
        valid_from=FUTURE_2030,
        valid_until=FUTURE_2031,
    )
    await fare_data.add_fare(
        mode="BUS",
        line_code="904",
        fare_profile="INTEGRAL",
        amount="5.50",
        valid_from=FUTURE_2031,
        valid_until=None,
    )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param(
            {"discount_percentage": Decimal("150.00")},
            "ck_fare_rules_discount_within_bounds",
            id="desconto-acima-de-100",
        ),
        pytest.param(
            {"discount_percentage": Decimal("-1.00")},
            "ck_fare_rules_discount_within_bounds",
            id="desconto-negativo",
        ),
        pytest.param(
            {"trip_type": "COMMON"},
            "ck_fare_rules_trip_type_valid",
            id="trip-type-nao-permitido",
        ),
    ],
)
async def test_constraints_de_fare_rules(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
    overrides: dict[str, object],
    constraint: str,
) -> None:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "trip_type": "INTEGRATION",
        "discount_percentage": Decimal("10.00"),
        "valid_from": FUTURE_2030,
        "valid_until": FUTURE_2031,
    }
    values.update(overrides)
    await _expect_violation(session_factory, FareRuleModel(**values), constraint)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_regra_sobreposta_a_oficial_e_rejeitada(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A regra oficial de INTEGRATION tem vigência aberta: nova regra em
    período sobreposto conflita na EXCLUDE."""
    await _expect_violation(
        session_factory,
        FareRuleModel(
            id=uuid.uuid4(),
            trip_type="INTEGRATION",
            discount_percentage=Decimal("20.00"),
            valid_from=FUTURE_2030,
            valid_until=None,
        ),
        "ex_fare_rules_no_overlapping_validity",
    )
