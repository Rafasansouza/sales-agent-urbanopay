"""Titularidade, masking e leitura de saldo (SPEC-002 §5–§7)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from tests.unit.cards.fakes import InMemoryCardRepository, make_card
from urbanopay.modules.cards.application.services import CardService
from urbanopay.modules.cards.domain.enums import CardStatus, FareProfile
from urbanopay.modules.cards.domain.errors import CardNotAccessibleError

MARIANA = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
LUCAS = uuid.UUID("00000000-0000-4000-8000-0000000000a2")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lista_somente_cartoes_proprios() -> None:
    own_one = make_card(customer_id=MARIANA, last4="4821")
    own_two = make_card(customer_id=MARIANA, last4="9001", profile=FareProfile.INTEGRAL)
    other = make_card(customer_id=LUCAS, last4="1257")
    service = CardService(InMemoryCardRepository([own_one, other, own_two]))

    cards = await service.list_cards(MARIANA)

    assert {card.id for card in cards} == {own_one.id, own_two.id}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cartao_de_outro_customer_nao_e_acessivel() -> None:
    card = make_card(customer_id=LUCAS)
    service = CardService(InMemoryCardRepository([card]))

    with pytest.raises(CardNotAccessibleError) as excinfo:
        await service.get_card(MARIANA, card.id)
    assert excinfo.value.code == "CARD_NOT_ACCESSIBLE"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inexistente_e_alheio_produzem_o_mesmo_erro_publico() -> None:
    """Anti-enumeração (§5): a resposta não revela se o cartão existe."""
    card = make_card(customer_id=LUCAS)
    service = CardService(InMemoryCardRepository([card]))

    with pytest.raises(CardNotAccessibleError) as foreign:
        await service.get_card(MARIANA, card.id)
    with pytest.raises(CardNotAccessibleError) as missing:
        await service.get_card(MARIANA, uuid.uuid4())

    assert type(foreign.value) is type(missing.value)
    assert str(foreign.value) == str(missing.value)
    assert foreign.value.code == missing.value.code


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saldo_e_decimal_exato() -> None:
    card = make_card(customer_id=MARIANA, balance="21.50")
    service = CardService(InMemoryCardRepository([card]))

    balance = await service.get_card_balance(MARIANA, card.id)

    assert type(balance) is Decimal
    assert balance == Decimal("21.50")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saldo_de_cartao_bloqueado_do_titular_e_legivel() -> None:
    """§7 não restringe leitura a cartão ACTIVE — o titular consulta o saldo."""
    card = make_card(customer_id=MARIANA, status=CardStatus.BLOCKED, balance="10.00")
    service = CardService(InMemoryCardRepository([card]))

    assert await service.get_card_balance(MARIANA, card.id) == Decimal("10.00")


@pytest.mark.unit
def test_masking_no_formato_da_spec() -> None:
    """§6: `****4821` — asteriscos + últimos 4 dígitos."""
    card = make_card(customer_id=MARIANA, last4="4821")
    assert card.masked_number == "****4821"


@pytest.mark.unit
def test_entidade_nao_possui_numero_completo() -> None:
    """Minimização aprovada: o número completo não existe no sistema."""
    card = make_card(customer_id=MARIANA)

    assert not hasattr(card, "card_number")
    # O repr expõe apenas o last4 — que é o dado de apresentação previsto (§6).
    assert "card_last4='4821'" in repr(card)
