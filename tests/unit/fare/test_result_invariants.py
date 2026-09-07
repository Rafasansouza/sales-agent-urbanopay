"""Invariantes estruturais do FareCalculation (SPEC-001 §13).

Construções inconsistentes devem falhar na origem — resultado inválido é bug e
não ganha fallback.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from tests.unit.fare.fakes import FIXED_NOW
from urbanopay.modules.fare.domain.enums import FareProfile, TransportMode, TripType
from urbanopay.modules.fare.domain.value_objects import (
    AppliedDiscount,
    CalculatedSegment,
    FareCalculation,
)


def seg(
    amount: str, mode: TransportMode = TransportMode.BUS, line: str | None = "101"
) -> CalculatedSegment:
    return CalculatedSegment(
        mode=mode,
        line_code=line if mode is TransportMode.BUS else None,
        fare_amount=Decimal(amount),
        fare_id=uuid.uuid4(),
    )


def discount(amount: str, percentage: str = "15.00") -> AppliedDiscount:
    return AppliedDiscount(
        type=TripType.INTEGRATION,
        percentage=Decimal(percentage),
        amount=Decimal(amount),
        rule_id=uuid.uuid4(),
    )


@pytest.mark.unit
def test_resultado_valido_sem_desconto() -> None:
    result = FareCalculation(
        fare_profile=FareProfile.INTEGRAL,
        trip_type=TripType.SINGLE,
        segments=(seg("6.00"),),
        subtotal=Decimal("6.00"),
        discount=None,
        total=Decimal("6.00"),
        reference_datetime=FIXED_NOW,
    )
    assert result.currency == "BRL"


@pytest.mark.unit
def test_resultado_valido_com_desconto() -> None:
    result = FareCalculation(
        fare_profile=FareProfile.MEIA,
        trip_type=TripType.INTEGRATION,
        segments=(seg("4.00"), seg("5.00", TransportMode.METRO)),
        subtotal=Decimal("9.00"),
        discount=discount("1.35"),
        total=Decimal("7.65"),
        reference_datetime=FIXED_NOW,
    )
    assert result.discount is not None
    assert result.discount.rule_id is not None


@pytest.mark.unit
def test_sem_segmentos_e_invalido() -> None:
    with pytest.raises(ValueError, match="ao menos um segmento"):
        FareCalculation(
            fare_profile=FareProfile.MEIA,
            trip_type=TripType.SINGLE,
            segments=(),
            subtotal=Decimal("0"),
            discount=None,
            total=Decimal("0"),
            reference_datetime=FIXED_NOW,
        )


@pytest.mark.unit
def test_subtotal_divergente_da_soma_e_invalido() -> None:
    with pytest.raises(ValueError, match="subtotal difere"):
        FareCalculation(
            fare_profile=FareProfile.MEIA,
            trip_type=TripType.SINGLE,
            segments=(seg("4.00"),),
            subtotal=Decimal("5.00"),
            discount=None,
            total=Decimal("5.00"),
            reference_datetime=FIXED_NOW,
        )


@pytest.mark.unit
@pytest.mark.parametrize("trip_type", [TripType.SINGLE, TripType.COMMON])
def test_desconto_em_single_ou_common_e_invalido(trip_type: TripType) -> None:
    segments = (
        (seg("6.00"),) if trip_type is TripType.SINGLE else (seg("6.00"), seg("8.00", line="303"))
    )
    subtotal = sum((s.fare_amount for s in segments), start=Decimal("0"))
    with pytest.raises(ValueError, match="não possuem desconto"):
        FareCalculation(
            fare_profile=FareProfile.INTEGRAL,
            trip_type=trip_type,
            segments=segments,
            subtotal=subtotal,
            discount=discount("1.00"),
            total=subtotal - Decimal("1.00"),
            reference_datetime=FIXED_NOW,
        )


@pytest.mark.unit
def test_integration_sem_desconto_e_invalido() -> None:
    with pytest.raises(ValueError, match="INTEGRATION exige desconto"):
        FareCalculation(
            fare_profile=FareProfile.MEIA,
            trip_type=TripType.INTEGRATION,
            segments=(seg("4.00"), seg("5.00", TransportMode.METRO)),
            subtotal=Decimal("9.00"),
            discount=None,
            total=Decimal("9.00"),
            reference_datetime=FIXED_NOW,
        )


@pytest.mark.unit
def test_total_sem_desconto_deve_igualar_subtotal() -> None:
    with pytest.raises(ValueError, match="igual ao subtotal"):
        FareCalculation(
            fare_profile=FareProfile.MEIA,
            trip_type=TripType.SINGLE,
            segments=(seg("4.00"),),
            subtotal=Decimal("4.00"),
            discount=None,
            total=Decimal("3.99"),
            reference_datetime=FIXED_NOW,
        )


@pytest.mark.unit
def test_total_com_desconto_deve_ser_subtotal_menos_desconto() -> None:
    with pytest.raises(ValueError, match="subtotal - discount_amount"):
        FareCalculation(
            fare_profile=FareProfile.MEIA,
            trip_type=TripType.INTEGRATION,
            segments=(seg("4.00"), seg("5.00", TransportMode.METRO)),
            subtotal=Decimal("9.00"),
            discount=discount("1.35"),
            total=Decimal("7.66"),
            reference_datetime=FIXED_NOW,
        )


@pytest.mark.unit
def test_desconto_maior_que_subtotal_e_invalido() -> None:
    with pytest.raises(ValueError, match="exceder o subtotal"):
        FareCalculation(
            fare_profile=FareProfile.MEIA,
            trip_type=TripType.INTEGRATION,
            segments=(seg("4.00"), seg("5.00", TransportMode.METRO)),
            subtotal=Decimal("9.00"),
            discount=discount("9.01"),
            total=Decimal("-0.01"),
            reference_datetime=FIXED_NOW,
        )


@pytest.mark.unit
def test_float_em_caminho_monetario_e_invalido() -> None:
    with pytest.raises(ValueError, match="deve ser Decimal"):
        FareCalculation(
            fare_profile=FareProfile.MEIA,
            trip_type=TripType.SINGLE,
            segments=(seg("4.00"),),
            subtotal=4.0,  # type: ignore[arg-type]  # violação proposital
            discount=None,
            total=Decimal("4.00"),
            reference_datetime=FIXED_NOW,
        )


@pytest.mark.unit
def test_reference_datetime_naive_e_invalido() -> None:
    from datetime import datetime

    with pytest.raises(ValueError, match="timezone-aware"):
        FareCalculation(
            fare_profile=FareProfile.MEIA,
            trip_type=TripType.SINGLE,
            segments=(seg("4.00"),),
            subtotal=Decimal("4.00"),
            discount=None,
            total=Decimal("4.00"),
            reference_datetime=datetime(2026, 6, 1),  # naive de propósito
        )
