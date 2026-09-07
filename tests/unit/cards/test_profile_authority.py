"""Autoridade do perfil tarifário oficial (SPEC-002 §1, §8, §16).

Inclui a composição com o Fare Engine via fakes: o perfil declarado pelo
usuário NUNCA substitui o do cartão — o cálculo oficial usa o perfil do Card.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from tests.unit.cards.fakes import InMemoryCardRepository, make_card
from tests.unit.fare.fakes import (
    FIXED_NOW,
    InMemoryFareRepository,
    InMemoryFareRuleRepository,
    make_rule,
    official_fares,
)
from urbanopay.modules.cards.application.services import CardService
from urbanopay.modules.cards.domain.enums import CardStatus, FareProfile, FareProfileSource
from urbanopay.modules.cards.domain.errors import CardNotAccessibleError, CardNotActiveError
from urbanopay.modules.cards.domain.value_objects import (
    ProfileSignal,
    detect_profile_divergence,
)
from urbanopay.modules.fare.application.services import FareService, SegmentInput

MARIANA = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
LUCAS = uuid.UUID("00000000-0000-4000-8000-0000000000a2")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("declared", "official", "expected"),
    [
        pytest.param(None, FareProfile.INTEGRAL, None, id="sem-declaracao"),
        pytest.param(FareProfile.INTEGRAL, FareProfile.INTEGRAL, None, id="declaracao-igual"),
        pytest.param(
            FareProfile.MEIA,
            FareProfile.INTEGRAL,
            ProfileSignal.FARE_PROFILE_CHANGED,
            id="declara-meia-cartao-integral",
        ),
        pytest.param(
            FareProfile.INTEGRAL,
            FareProfile.MEIA,
            ProfileSignal.FARE_PROFILE_CHANGED,
            id="declara-integral-cartao-meia",
        ),
    ],
)
def test_deteccao_de_divergencia(
    declared: FareProfile | None,
    official: FareProfile,
    expected: ProfileSignal | None,
) -> None:
    assert detect_profile_divergence(declared, official) is expected


@pytest.mark.unit
@pytest.mark.asyncio
async def test_perfil_oficial_vem_do_cartao_com_sinal() -> None:
    """§14.9: usuário declara MEIA, cartão INTEGRAL → oficial é INTEGRAL."""
    card = make_card(customer_id=MARIANA, profile=FareProfile.INTEGRAL)
    service = CardService(InMemoryCardRepository([card]))

    result = await service.resolve_official_fare_profile(
        MARIANA, card.id, declared_profile=FareProfile.MEIA
    )

    assert result.official_profile is FareProfile.INTEGRAL
    assert result.source is FareProfileSource.CARD
    assert result.verified is True
    assert result.declared_profile is FareProfile.MEIA
    assert result.signal is ProfileSignal.FARE_PROFILE_CHANGED
    assert result.card_id == card.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_declaracao_igual_nao_gera_sinal() -> None:
    card = make_card(customer_id=MARIANA, profile=FareProfile.MEIA)
    service = CardService(InMemoryCardRepository([card]))

    result = await service.resolve_official_fare_profile(
        MARIANA, card.id, declared_profile=FareProfile.MEIA
    )

    assert result.official_profile is FareProfile.MEIA
    assert result.signal is None


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [CardStatus.BLOCKED, CardStatus.EXPIRED, CardStatus.CANCELLED],
    ids=lambda status: status.value.lower(),
)
async def test_somente_cartao_active_e_autoridade(status: CardStatus) -> None:
    """PRD RN-09: cartão não-ACTIVE não fornece o perfil oficial."""
    card = make_card(customer_id=MARIANA, status=status)
    service = CardService(InMemoryCardRepository([card]))

    with pytest.raises(CardNotActiveError) as excinfo:
        await service.resolve_official_fare_profile(MARIANA, card.id)
    assert excinfo.value.code == "CARD_NOT_ACTIVE"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_titularidade_antes_de_status() -> None:
    """Cartão BLOQUEADO de terceiro → CARD_NOT_ACCESSIBLE, nunca CARD_NOT_ACTIVE:
    a resposta não revela nem a existência nem o estado do cartão alheio."""
    card = make_card(customer_id=LUCAS, status=CardStatus.BLOCKED)
    service = CardService(InMemoryCardRepository([card]))

    with pytest.raises(CardNotAccessibleError):
        await service.resolve_official_fare_profile(MARIANA, card.id)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_perfil_do_cartao_alimenta_o_fare_engine() -> None:
    """Composição SPEC-002 → SPEC-001: declara MEIA, cartão INTEGRAL, e o
    cálculo oficial usa INTEGRAL (6.00 na linha 101, não 3.00).

    A fronteira é o valor string do perfil — `cards` não importa `fare` e
    vice-versa; quem compõe é este teste (papel da futura SPEC-004).
    """
    card = make_card(customer_id=MARIANA, profile=FareProfile.INTEGRAL)
    card_service = CardService(InMemoryCardRepository([card]))
    fare_service = FareService(
        fares=InMemoryFareRepository(official_fares()),
        fare_rules=InMemoryFareRuleRepository([make_rule()]),
    )

    resolution = await card_service.resolve_official_fare_profile(
        MARIANA, card.id, declared_profile=FareProfile.MEIA
    )
    assert resolution.signal is ProfileSignal.FARE_PROFILE_CHANGED

    calculation = await fare_service.calculate_trip_fare(
        resolution.official_profile.value,
        [SegmentInput(mode="BUS", line_code="101")],
        at=FIXED_NOW,
    )

    assert calculation.total == Decimal("6.00")  # INTEGRAL, não os 3.00 da MEIA
    assert calculation.fare_profile.value == "INTEGRAL"
