"""Validação estrutural de segmentos, perfil e modal (SPEC-001 §3, §4, §11)."""

from __future__ import annotations

import pytest

from urbanopay.modules.fare.domain.enums import FareProfile, TransportMode
from urbanopay.modules.fare.domain.errors import (
    BusLineRequiredError,
    InvalidFareProfileError,
    InvalidSegmentStructureError,
    InvalidTransportModeError,
)
from urbanopay.modules.fare.domain.value_objects import (
    Segment,
    parse_fare_profile,
    parse_transport_mode,
)


@pytest.mark.unit
@pytest.mark.parametrize("line_code", [None, "", "   "], ids=["none", "empty", "whitespace"])
def test_bus_sem_linha_util_exige_bus_line_required(line_code: str | None) -> None:
    with pytest.raises(BusLineRequiredError) as excinfo:
        Segment(mode=TransportMode.BUS, line_code=line_code)
    assert excinfo.value.code == "BUS_LINE_REQUIRED"


@pytest.mark.unit
def test_metro_com_linha_e_estrutura_invalida() -> None:
    """Decisão aprovada: METRO não possui line_code (SPEC-001 §4)."""
    with pytest.raises(InvalidSegmentStructureError) as excinfo:
        Segment(mode=TransportMode.METRO, line_code="L1")
    assert excinfo.value.code == "INVALID_SEGMENT_STRUCTURE"


@pytest.mark.unit
def test_segmentos_validos() -> None:
    bus = Segment(mode=TransportMode.BUS, line_code="303")
    assert bus.lookup_key.line_code == "303"

    metro = Segment(mode=TransportMode.METRO)
    assert metro.lookup_key.line_code is None


@pytest.mark.unit
def test_line_code_nao_e_normalizado() -> None:
    """O código informado é preservado exatamente como chegou."""
    segment = Segment(mode=TransportMode.BUS, line_code=" 303 ")
    assert segment.line_code == " 303 "


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw", ["TRAIN", "bus", "metrô", ""], ids=["train", "lower", "pt", "empty"]
)
def test_modal_invalido(raw: str) -> None:
    with pytest.raises(InvalidTransportModeError) as excinfo:
        parse_transport_mode(raw)
    assert excinfo.value.code == "INVALID_TRANSPORT_MODE"


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw", ["meia", "HALF", "INTEGRAL ", ""], ids=["lower", "en", "spaced", "empty"]
)
def test_perfil_invalido(raw: str) -> None:
    with pytest.raises(InvalidFareProfileError) as excinfo:
        parse_fare_profile(raw)
    assert excinfo.value.code == "INVALID_FARE_PROFILE"


@pytest.mark.unit
def test_perfis_e_modais_validos() -> None:
    assert parse_fare_profile("INTEGRAL") is FareProfile.INTEGRAL
    assert parse_fare_profile("MEIA") is FareProfile.MEIA
    assert parse_transport_mode("BUS") is TransportMode.BUS
    assert parse_transport_mode("METRO") is TransportMode.METRO
