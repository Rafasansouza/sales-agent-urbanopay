"""Casos obrigatórios de SPEC-001 §12 e comportamento do FareService.

Cobrem 100% dos casos determinísticos exigidos (meta: Fare Calculation
Accuracy = 100%, PRD §16), usando fakes em memória com o dataset oficial
derivado de SPEC-001 §2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.unit.fare.fakes import (
    FIXED_NOW,
    InMemoryFareRepository,
    InMemoryFareRuleRepository,
    UnavailableFareRepository,
    make_fare,
    make_rule,
    official_fares,
)
from urbanopay.modules.fare.application.services import FareService, SegmentInput
from urbanopay.modules.fare.domain.enums import FareProfile, TransportMode, TripType
from urbanopay.modules.fare.domain.errors import (
    BusLineRequiredError,
    EmptyTripError,
    FareLineNotFoundError,
    FareNotAvailableError,
    FareRuleNotFoundError,
    FareServiceUnavailableError,
    InvalidFareProfileError,
    InvalidTransportModeError,
    UnsupportedTripCompositionError,
)


def official_service() -> FareService:
    return FareService(
        fares=InMemoryFareRepository(official_fares()),
        fare_rules=InMemoryFareRuleRepository([make_rule()]),
    )


def bus(line: str) -> SegmentInput:
    return SegmentInput(mode="BUS", line_code=line)


def metro() -> SegmentInput:
    return SegmentInput(mode="METRO")


# Casos determinísticos obrigatórios (SPEC-001 §12) + casos aprovados no plano.
# (id, perfil, segmentos, trip_type, subtotal, desconto, total)
MANDATORY_CASES = [
    pytest.param(
        "INTEGRAL", [bus("101")], TripType.SINGLE, "6.00", None, "6.00", id="101-integral"
    ),
    pytest.param("MEIA", [bus("101")], TripType.SINGLE, "3.00", None, "3.00", id="101-meia"),
    pytest.param(
        "INTEGRAL", [metro()], TripType.SINGLE, "10.00", None, "10.00", id="metro-integral"
    ),
    pytest.param("MEIA", [metro()], TripType.SINGLE, "5.00", None, "5.00", id="metro-meia"),
    pytest.param(
        "INTEGRAL",
        [bus("101"), bus("303")],
        TripType.COMMON,
        "14.00",
        None,
        "14.00",
        id="101+303-integral-common",
    ),
    pytest.param(
        "MEIA",
        [bus("101"), bus("303")],
        TripType.COMMON,
        "7.00",
        None,
        "7.00",
        id="101+303-meia-common",
    ),
    pytest.param(
        "INTEGRAL",
        [bus("303"), metro()],
        TripType.INTEGRATION,
        "18.00",
        "2.70",
        "15.30",
        id="303+metro-integral-integration",
    ),
    pytest.param(
        "MEIA",
        [bus("303"), metro()],
        TripType.INTEGRATION,
        "9.00",
        "1.35",
        "7.65",
        id="303+metro-meia-integration",
    ),
    pytest.param(
        "INTEGRAL",
        [bus("505"), metro()],
        TripType.INTEGRATION,
        "20.00",
        "3.00",
        "17.00",
        id="505+metro-integral",
    ),
    pytest.param(
        "MEIA",
        [bus("505"), metro()],
        TripType.INTEGRATION,
        "10.00",
        "1.50",
        "8.50",
        id="505+metro-meia",
    ),
    pytest.param(
        "INTEGRAL",
        [bus("101"), bus("303"), metro()],
        TripType.INTEGRATION,
        "24.00",
        "3.60",
        "20.40",
        id="101+303+metro-integral-multissegmento",
    ),
    pytest.param(
        "MEIA",
        [bus("101"), bus("303"), metro()],
        TripType.INTEGRATION,
        "12.00",
        "1.80",
        "10.20",
        id="101+303+metro-meia-multissegmento",
    ),
    # Bônus com dados oficiais: 4.50 + 5.00 = 9.50; 15% = 1.425 → 1.43
    # (ROUND_HALF_UP; o arredondamento bancário daria 1.42).
    pytest.param(
        "MEIA",
        [bus("404"), metro()],
        TripType.INTEGRATION,
        "9.50",
        "1.43",
        "8.07",
        id="404+metro-meia-half-up",
    ),
]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "segments", "trip_type", "subtotal", "discount_amount", "total"),
    MANDATORY_CASES,
)
async def test_casos_deterministicos_obrigatorios(
    profile: str,
    segments: list[SegmentInput],
    trip_type: TripType,
    subtotal: str,
    discount_amount: str | None,
    total: str,
) -> None:
    result = await official_service().calculate_trip_fare(profile, segments, at=FIXED_NOW)

    assert result.trip_type is trip_type
    assert result.subtotal == Decimal(subtotal)
    assert result.total == Decimal(total)
    assert result.currency == "BRL"
    assert result.reference_datetime == FIXED_NOW
    assert len(result.segments) == len(segments)

    if discount_amount is None:
        assert result.discount is None
        assert result.total == result.subtotal
    else:
        assert result.discount is not None
        assert result.discount.amount == Decimal(discount_amount)
        assert result.discount.percentage == Decimal("15.00")
        assert result.discount.type is TripType.INTEGRATION


@pytest.mark.unit
@pytest.mark.asyncio
async def test_linha_999_inexistente(  # SPEC-001 §12: linha 999 => erro
) -> None:
    with pytest.raises(FareLineNotFoundError) as excinfo:
        await official_service().calculate_trip_fare("INTEGRAL", [bus("999")], at=FIXED_NOW)
    assert excinfo.value.code == "FARE_LINE_NOT_FOUND"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_perfil_invalido() -> None:
    with pytest.raises(InvalidFareProfileError):
        await official_service().calculate_trip_fare("meia", [bus("101")], at=FIXED_NOW)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trajeto_vazio() -> None:
    with pytest.raises(EmptyTripError):
        await official_service().calculate_trip_fare("INTEGRAL", [], at=FIXED_NOW)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vigencia_antiga_e_nova_retornam_valor_do_periodo() -> None:
    """SPEC-001 §12: vigência antiga/nova => valor correspondente ao período."""
    old_period = make_fare(
        TransportMode.BUS,
        "808",
        FareProfile.MEIA,
        "5.00",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_until=datetime(2021, 1, 1, tzinfo=UTC),
    )
    current_period = make_fare(
        TransportMode.BUS,
        "808",
        FareProfile.MEIA,
        "6.50",
        valid_from=datetime(2021, 1, 1, tzinfo=UTC),
    )
    service = FareService(
        fares=InMemoryFareRepository([old_period, current_period]),
        fare_rules=InMemoryFareRuleRepository([]),
    )

    at_2020 = await service.calculate_trip_fare(
        "MEIA", [bus("808")], at=datetime(2020, 6, 1, tzinfo=UTC)
    )
    assert at_2020.total == Decimal("5.00")
    assert at_2020.segments[0].fare_id == old_period.id

    at_now = await service.calculate_trip_fare("MEIA", [bus("808")], at=FIXED_NOW)
    assert at_now.total == Decimal("6.50")
    assert at_now.segments[0].fare_id == current_period.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_limite_da_vigencia_e_semiaberto() -> None:
    """No instante exato da troca vale a tarifa nova: [from, until)."""
    boundary = datetime(2021, 1, 1, tzinfo=UTC)
    old_period = make_fare(
        TransportMode.BUS,
        "808",
        FareProfile.MEIA,
        "5.00",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_until=boundary,
    )
    new_period = make_fare(TransportMode.BUS, "808", FareProfile.MEIA, "6.50", valid_from=boundary)
    service = FareService(
        fares=InMemoryFareRepository([old_period, new_period]),
        fare_rules=InMemoryFareRuleRepository([]),
    )

    result = await service.calculate_trip_fare("MEIA", [bus("808")], at=boundary)
    assert result.segments[0].fare_id == new_period.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bus_conhecido_sem_vigencia_e_fare_not_available() -> None:
    """Linha existe, mas nada vigente na data → FARE_NOT_AVAILABLE."""
    with pytest.raises(FareNotAvailableError) as excinfo:
        await official_service().calculate_trip_fare(
            "INTEGRAL", [bus("101")], at=datetime(1999, 1, 1, tzinfo=UTC)
        )
    assert excinfo.value.code == "FARE_NOT_AVAILABLE"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_metro_sem_vigencia_nunca_e_line_not_found() -> None:
    """METRO não possui linha: ausência de tarifa é sempre FARE_NOT_AVAILABLE."""
    with pytest.raises(FareNotAvailableError):
        await official_service().calculate_trip_fare(
            "MEIA", [metro()], at=datetime(1999, 1, 1, tzinfo=UTC)
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_integration_sem_regra_vigente() -> None:
    """INTEGRATION exige regra vigente — nunca 15% de fallback (SPEC §11, §13)."""
    service = FareService(
        fares=InMemoryFareRepository(official_fares()),
        fare_rules=InMemoryFareRuleRepository([]),
    )
    with pytest.raises(FareRuleNotFoundError) as excinfo:
        await service.calculate_trip_fare("MEIA", [bus("303"), metro()], at=FIXED_NOW)
    assert excinfo.value.code == "FARE_RULE_NOT_FOUND"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_composicao_metro_metro_e_rejeitada_apos_consulta_tarifaria() -> None:
    """Metrô-só multi-segmento (A-04): com tarifas vigentes disponíveis, a
    classificação (§6.7) rejeita a composição — decisão inalterada, no momento
    normativo do fluxo."""
    with pytest.raises(UnsupportedTripCompositionError) as excinfo:
        await official_service().calculate_trip_fare("MEIA", [metro(), metro()], at=FIXED_NOW)
    assert excinfo.value.code == "UNSUPPORTED_TRIP_COMPOSITION"


# ---------------------------------------------------------------------------
# Precedência de erros — a ordem normativa de SPEC-001 §6 decide qual erro
# vence quando a entrada tem mais de um problema potencial.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_precedencia_tarifa_indisponivel_antes_de_composicao() -> None:
    """Metrô-só fora de vigência tem DOIS problemas: tarifa ausente (§6.4) e
    composição não suportada (§6.7). A ordem da SPEC decide: consulta vem
    antes da classificação, portanto FARE_NOT_AVAILABLE vence."""
    with pytest.raises(FareNotAvailableError):
        await official_service().calculate_trip_fare(
            "MEIA", [metro(), metro()], at=datetime(1999, 1, 1, tzinfo=UTC)
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_precedencia_perfil_invalido_antes_de_composicao() -> None:
    """Perfil inválido (§6.3) precede a classificação (§6.7)."""
    with pytest.raises(InvalidFareProfileError):
        await official_service().calculate_trip_fare("meia", [metro(), metro()], at=FIXED_NOW)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_precedencia_trajeto_vazio_antes_de_perfil() -> None:
    """Request vazio (§6.1) precede a validação de perfil (§6.3)."""
    with pytest.raises(EmptyTripError):
        await official_service().calculate_trip_fare("meia", [], at=FIXED_NOW)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_precedencia_modo_invalido_antes_de_perfil() -> None:
    """Validação de segmentos (§6.2) precede a de perfil (§6.3)."""
    with pytest.raises(InvalidTransportModeError):
        await official_service().calculate_trip_fare(
            "meia", [SegmentInput(mode="TRAIN", line_code="101")], at=FIXED_NOW
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_precedencia_bus_sem_linha_antes_de_perfil() -> None:
    """Estrutura do segmento (§6.2) precede a validação de perfil (§6.3)."""
    with pytest.raises(BusLineRequiredError):
        await official_service().calculate_trip_fare(
            "meia", [SegmentInput(mode="BUS", line_code=None)], at=FIXED_NOW
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_indisponibilidade_propaga() -> None:
    service = FareService(
        fares=UnavailableFareRepository(),
        fare_rules=InMemoryFareRuleRepository([make_rule()]),
    )
    with pytest.raises(FareServiceUnavailableError) as excinfo:
        await service.calculate_trip_fare("MEIA", [bus("101")], at=FIXED_NOW)
    assert excinfo.value.code == "FARE_SERVICE_UNAVAILABLE"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_instante_de_referencia_naive_e_rejeitado() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await official_service().calculate_trip_fare(
            "MEIA",
            [bus("101")],
            at=datetime(2026, 6, 1),  # naive de propósito
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_determinismo() -> None:
    """SPEC-001 §13: mesma entrada + mesmas regras ⇒ mesmo resultado."""
    service = official_service()
    first = await service.calculate_trip_fare("MEIA", [bus("303"), metro()], at=FIXED_NOW)
    second = await service.calculate_trip_fare("MEIA", [bus("303"), metro()], at=FIXED_NOW)
    assert first == second


@pytest.mark.unit
@pytest.mark.asyncio
async def test_breakdown_e_auditavel() -> None:
    """O resultado permite reconstruir como o valor foi calculado."""
    fares = official_fares()
    rule = make_rule()
    service = FareService(
        fares=InMemoryFareRepository(fares),
        fare_rules=InMemoryFareRuleRepository([rule]),
    )

    result = await service.calculate_trip_fare("MEIA", [bus("303"), metro()], at=FIXED_NOW)

    by_key = {(f.mode, f.line_code, f.fare_profile): f for f in fares}
    expected_bus = by_key[(TransportMode.BUS, "303", FareProfile.MEIA)]
    expected_metro = by_key[(TransportMode.METRO, None, FareProfile.MEIA)]

    # Segmentos preservam a ordem de entrada e apontam a tarifa exata usada.
    assert result.segments[0].fare_id == expected_bus.id
    assert result.segments[0].fare_amount == Decimal("4.00")
    assert result.segments[1].fare_id == expected_metro.id
    assert result.segments[1].fare_amount == Decimal("5.00")
    assert result.discount is not None
    assert result.discount.rule_id == rule.id
    assert result.reference_datetime == FIXED_NOW


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segmento_repetido_e_cobrado_duas_vezes() -> None:
    """Dois segmentos da mesma linha são dois embarques: soma dupla."""
    result = await official_service().calculate_trip_fare(
        "INTEGRAL", [bus("101"), bus("101")], at=FIXED_NOW
    )
    assert result.trip_type is TripType.COMMON
    assert result.subtotal == Decimal("12.00")
    assert result.total == Decimal("12.00")
    assert len(result.segments) == 2
