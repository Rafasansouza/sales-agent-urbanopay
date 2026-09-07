"""Fakes em memória do módulo cards. Dados 100% fictícios."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from urbanopay.modules.cards.domain.entities import Card
from urbanopay.modules.cards.domain.enums import CardStatus, FareProfile

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


def make_card(
    *,
    customer_id: uuid.UUID,
    last4: str = "4821",
    profile: FareProfile = FareProfile.MEIA,
    balance: str = "21.50",
    status: CardStatus = CardStatus.ACTIVE,
    card_id: uuid.UUID | None = None,
) -> Card:
    return Card(
        id=card_id if card_id is not None else uuid.uuid4(),
        customer_id=customer_id,
        card_last4=last4,
        fare_profile=profile,
        balance=Decimal(balance),
        status=status,
        expires_at=None,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


class InMemoryCardRepository:
    """Fake do port `CardRepository` — escopo por cliente, como no SQL real."""

    def __init__(self, cards: list[Card]) -> None:
        self._cards = list(cards)

    async def list_for_customer(self, customer_id: uuid.UUID) -> list[Card]:
        return [card for card in self._cards if card.customer_id == customer_id]

    async def get_owned(self, customer_id: uuid.UUID, card_id: uuid.UUID) -> Card | None:
        for card in self._cards:
            if card.id == card_id and card.customer_id == customer_id:
                return card
        return None
