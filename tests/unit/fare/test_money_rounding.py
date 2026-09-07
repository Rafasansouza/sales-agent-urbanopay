"""Aritmética monetária e ROUND_HALF_UP (SPEC-001 §7).

Inclui o caso crítico aprovado no plano: subtotal 7.50 com 15% de desconto
produz 1.125, que DEVE arredondar para 1.13 (half-up) — o arredondamento
bancário padrão do Python daria 1.12.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.unit.fare.fakes import (
    FIXED_NOW,
    InMemoryFareRepository,
    InMemoryFareRuleRepository,
    make_fare,
    make_rule,
)
from urbanopay.modules.fare.application.services import FareService, SegmentInput
from urbanopay.modules.fare.domain.enums import FareProfile, TransportMode
from urbanopay.modules.fare.domain.value_objects import percentage_of, to_money


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("1.125", "1.13", id="meio-exato-sobe"),
        pytest.param("1.425", "1.43", id="meio-exato-sobe-2"),
        pytest.param("1.1149", "1.11", id="abaixo-do-meio-desce"),
        pytest.param("1.135", "1.14", id="meio-exato-sobe-3"),
        pytest.param("2.00", "2.00", id="exato-inalterado"),
        pytest.param("0.005", "0.01", id="menor-meio-sobe"),
    ],
)
def test_to_money_round_half_up(value: str, expected: str) -> None:
    assert to_money(Decimal(value)) == Decimal(expected)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("amount", "percentage", "expected"),
    [
        pytest.param("7.50", "15.00", "1.13", id="caso-critico-7.50-15pct"),
        pytest.param("9.50", "15.00", "1.43", id="9.50-15pct-half-up"),
        pytest.param("9.00", "15.00", "1.35", id="9.00-15pct-exato"),
        pytest.param("20.00", "15.00", "3.00", id="20.00-15pct-exato"),
        pytest.param("7.43", "15.00", "1.11", id="arredonda-para-baixo"),
        pytest.param("10.00", "0.00", "0.00", id="zero-por-cento"),
        pytest.param("10.00", "100.00", "10.00", id="cem-por-cento"),
    ],
)
def test_percentage_of(amount: str, percentage: str, expected: str) -> None:
    assert percentage_of(Decimal(amount), Decimal(percentage)) == Decimal(expected)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_caso_critico_do_plano_fim_a_fim() -> None:
    """subtotal 7.50 → desconto 1.125 → 1.13 → total 6.37, via FareService."""
    fares = [
        make_fare(TransportMode.BUS, "202", FareProfile.MEIA, "3.50"),
        make_fare(TransportMode.METRO, None, FareProfile.MEIA, "4.00"),
    ]
    service = FareService(
        fares=InMemoryFareRepository(fares),
        fare_rules=InMemoryFareRuleRepository([make_rule("15.00")]),
    )

    result = await service.calculate_trip_fare(
        "MEIA",
        [SegmentInput(mode="BUS", line_code="202"), SegmentInput(mode="METRO")],
        at=FIXED_NOW,
    )

    assert result.subtotal == Decimal("7.50")
    assert result.discount is not None
    assert result.discount.amount == Decimal("1.13")
    assert result.total == Decimal("6.37")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_percentual_vem_da_regra_e_nao_de_constante() -> None:
    """Regra com percentual diferente muda o resultado: 15% não é hardcoded."""
    fares = [
        make_fare(TransportMode.BUS, "303", FareProfile.MEIA, "4.00"),
        make_fare(TransportMode.METRO, None, FareProfile.MEIA, "5.00"),
    ]
    service = FareService(
        fares=InMemoryFareRepository(fares),
        fare_rules=InMemoryFareRuleRepository([make_rule("20.00")]),
    )

    result = await service.calculate_trip_fare(
        "MEIA",
        [SegmentInput(mode="BUS", line_code="303"), SegmentInput(mode="METRO")],
        at=FIXED_NOW,
    )

    assert result.discount is not None
    assert result.discount.percentage == Decimal("20.00")
    assert result.discount.amount == Decimal("1.80")
    assert result.total == Decimal("7.20")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_todos_os_valores_monetarios_sao_decimal() -> None:
    fares = [
        make_fare(TransportMode.BUS, "303", FareProfile.MEIA, "4.00"),
        make_fare(TransportMode.METRO, None, FareProfile.MEIA, "5.00"),
    ]
    service = FareService(
        fares=InMemoryFareRepository(fares),
        fare_rules=InMemoryFareRuleRepository([make_rule()]),
    )
    result = await service.calculate_trip_fare(
        "MEIA",
        [SegmentInput(mode="BUS", line_code="303"), SegmentInput(mode="METRO")],
        at=FIXED_NOW,
    )

    assert type(result.subtotal) is Decimal
    assert type(result.total) is Decimal
    assert result.discount is not None
    assert type(result.discount.amount) is Decimal
    assert type(result.discount.percentage) is Decimal
    for segment in result.segments:
        assert type(segment.fare_amount) is Decimal
