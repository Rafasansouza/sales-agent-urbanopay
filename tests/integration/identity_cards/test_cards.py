"""Cartões contra PostgreSQL real: ownership, masking, saldo e autoridade de
perfil alimentando o Fare Engine real (SPEC-002 §5–§8, §14, §15)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.identity_cards.conftest import FIXED_NOW, IdentityCardsTestData
from urbanopay.modules.cards.application.services import CardService
from urbanopay.modules.cards.domain.enums import CardStatus, FareProfile, FareProfileSource
from urbanopay.modules.cards.domain.errors import CardNotAccessibleError, CardNotActiveError
from urbanopay.modules.cards.domain.value_objects import ProfileSignal
from urbanopay.modules.cards.infrastructure.repositories import SqlAlchemyCardRepository
from urbanopay.modules.fare.application.services import FareService, SegmentInput
from urbanopay.modules.fare.infrastructure.repositories import (
    SqlAlchemyFareRepository,
    SqlAlchemyFareRuleRepository,
)


async def _seed_spec13_dataset(
    data: IdentityCardsTestData,
) -> dict[str, uuid.UUID]:
    """Dataset nominal de SPEC-002 §13 + cartão EXPIRED (cobre A-12)."""
    mariana = await data.add_customer(name="Mariana", cpf="60160160160")
    lucas = await data.add_customer(name="Lucas", cpf="60260260260")
    camila = await data.add_customer(name="Camila", cpf="60360360360")
    cliente4 = await data.add_customer(name="Cliente Quatro", cpf="60460460460")

    return {
        "mariana": mariana,
        "lucas": lucas,
        "camila": camila,
        "cliente4": cliente4,
        "mariana_card": await data.add_card(
            customer_id=mariana, last4="4821", fare_profile="MEIA", balance="21.50"
        ),
        "mariana_expired_card": await data.add_card(
            customer_id=mariana,
            last4="7000",
            fare_profile="MEIA",
            balance="0.00",
            status="EXPIRED",
        ),
        "lucas_card": await data.add_card(
            customer_id=lucas, last4="1257", fare_profile="INTEGRAL", balance="42.00"
        ),
        "camila_card": await data.add_card(
            customer_id=camila,
            last4="7934",
            fare_profile="INTEGRAL",
            balance="10.00",
            status="BLOCKED",
        ),
        "cliente4_meia": await data.add_card(
            customer_id=cliente4, last4="1111", fare_profile="MEIA", balance="5.00"
        ),
        "cliente4_integral": await data.add_card(
            customer_id=cliente4, last4="2222", fare_profile="INTEGRAL", balance="6.00"
        ),
    }


def _service(session: AsyncSession) -> CardService:
    return CardService(SqlAlchemyCardRepository(session))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lista_somente_cartoes_proprios(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_spec13_dataset(data)
    async with session_factory() as session:
        cards = await _service(session).list_cards(ids["cliente4"])

    assert {card.id for card in cards} == {ids["cliente4_meia"], ids["cliente4_integral"]}
    assert {card.fare_profile for card in cards} == {FareProfile.MEIA, FareProfile.INTEGRAL}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ownership_cruzado_e_inexistente_sao_indistinguiveis(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """§14.8 + anti-enumeração (§5): mesmo erro público para os dois casos."""
    ids = await _seed_spec13_dataset(data)
    async with session_factory() as session:
        service = _service(session)

        with pytest.raises(CardNotAccessibleError) as foreign:
            await service.get_card(ids["mariana"], ids["lucas_card"])
        with pytest.raises(CardNotAccessibleError) as missing:
            await service.get_card(ids["mariana"], uuid.uuid4())

    assert str(foreign.value) == str(missing.value)
    assert foreign.value.code == missing.value.code == "CARD_NOT_ACCESSIBLE"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_saldo_decimal_exato_e_masking(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_spec13_dataset(data)
    async with session_factory() as session:
        service = _service(session)
        card = await service.get_card(ids["mariana"], ids["mariana_card"])
        balance = await service.get_card_balance(ids["mariana"], ids["mariana_card"])

    assert type(balance) is Decimal
    assert balance == Decimal("21.50")
    assert card.masked_number == "****4821"
    assert not hasattr(card, "card_number")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cartao_expirado_do_titular_e_visivel_mas_nao_e_autoridade(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """§14.7: cartão EXPIRED — legível pelo titular; inutilizável como perfil."""
    ids = await _seed_spec13_dataset(data)
    async with session_factory() as session:
        service = _service(session)
        card = await service.get_card(ids["mariana"], ids["mariana_expired_card"])
        assert card.status is CardStatus.EXPIRED

        with pytest.raises(CardNotActiveError):
            await service.resolve_official_fare_profile(ids["mariana"], ids["mariana_expired_card"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cartao_bloqueado_nao_e_autoridade(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_spec13_dataset(data)
    async with session_factory() as session:
        with pytest.raises(CardNotActiveError) as excinfo:
            await _service(session).resolve_official_fare_profile(ids["camila"], ids["camila_card"])
    assert excinfo.value.code == "CARD_NOT_ACTIVE"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_perfil_oficial_com_sinal_de_divergencia(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """§14.9: declara MEIA, cartão INTEGRAL → oficial INTEGRAL + sinal."""
    ids = await _seed_spec13_dataset(data)
    async with session_factory() as session:
        result = await _service(session).resolve_official_fare_profile(
            ids["lucas"], ids["lucas_card"], declared_profile=FareProfile.MEIA
        )

    assert result.official_profile is FareProfile.INTEGRAL
    assert result.source is FareProfileSource.CARD
    assert result.verified is True
    assert result.signal is ProfileSignal.FARE_PROFILE_CHANGED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_perfil_oficial_do_cartao_alimenta_o_fare_engine_real(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SPEC-002 §15 fim a fim: cartão INTEGRAL no banco → FareService real com
    as tarifas oficiais seedadas → o cálculo usa INTEGRAL, não a declaração.

    `cards` e `fare` continuam sem se conhecer: a composição acontece aqui,
    passando o valor string do perfil (papel da futura SPEC-004).
    """
    ids = await _seed_spec13_dataset(data)
    async with session_factory() as session:
        resolution = await _service(session).resolve_official_fare_profile(
            ids["lucas"], ids["lucas_card"], declared_profile=FareProfile.MEIA
        )
        fare_service = FareService(
            fares=SqlAlchemyFareRepository(session),
            fare_rules=SqlAlchemyFareRuleRepository(session),
        )
        calculation = await fare_service.calculate_trip_fare(
            resolution.official_profile.value,
            [SegmentInput(mode="BUS", line_code="101")],
            at=FIXED_NOW,
        )

    assert resolution.signal is ProfileSignal.FARE_PROFILE_CHANGED
    assert calculation.total == Decimal("6.00")  # INTEGRAL oficial, não MEIA declarada
    assert calculation.fare_profile.value == "INTEGRAL"
