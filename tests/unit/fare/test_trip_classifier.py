"""Classificação de viagem (SPEC-001 §5)."""

from __future__ import annotations

import pytest

from urbanopay.modules.fare.domain.enums import TransportMode, TripType
from urbanopay.modules.fare.domain.errors import (
    EmptyTripError,
    UnsupportedTripCompositionError,
)
from urbanopay.modules.fare.domain.services import TripClassifier
from urbanopay.modules.fare.domain.value_objects import Segment


def bus(line: str) -> Segment:
    return Segment(mode=TransportMode.BUS, line_code=line)


def metro() -> Segment:
    return Segment(mode=TransportMode.METRO)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        pytest.param([bus("101")], TripType.SINGLE, id="single-bus"),
        pytest.param([metro()], TripType.SINGLE, id="single-metro"),
        pytest.param([bus("101"), bus("303")], TripType.COMMON, id="two-buses"),
        pytest.param([bus("101"), bus("303"), bus("505")], TripType.COMMON, id="three-buses"),
        pytest.param([bus("101"), bus("101")], TripType.COMMON, id="same-bus-twice"),
        pytest.param([bus("303"), metro()], TripType.INTEGRATION, id="bus-metro"),
        pytest.param([metro(), bus("303")], TripType.INTEGRATION, id="metro-bus"),
        pytest.param(
            [bus("101"), bus("303"), metro()],
            TripType.INTEGRATION,
            id="bus-bus-metro",
        ),
        pytest.param(
            [metro(), bus("101"), metro()],
            TripType.INTEGRATION,
            id="metro-bus-metro",
        ),
    ],
)
def test_classificacao(segments: list[Segment], expected: TripType) -> None:
    assert TripClassifier.classify(segments) is expected


@pytest.mark.unit
def test_trajeto_vazio_e_erro_tipado() -> None:
    with pytest.raises(EmptyTripError) as excinfo:
        TripClassifier.classify([])
    assert excinfo.value.code == "EMPTY_TRIP"


@pytest.mark.unit
@pytest.mark.parametrize("count", [2, 3, 5])
def test_multiplos_metros_e_composicao_nao_suportada(count: int) -> None:
    """Decisão A-04 (aprovada): metrô-só multi-segmento é rejeitado.

    Nunca classificado como COMMON, nunca inventada categoria nova.
    """
    with pytest.raises(UnsupportedTripCompositionError) as excinfo:
        TripClassifier.classify([metro() for _ in range(count)])
    assert excinfo.value.code == "UNSUPPORTED_TRIP_COMPOSITION"
