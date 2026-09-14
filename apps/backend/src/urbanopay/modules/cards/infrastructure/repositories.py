"""Repositories SQLAlchemy do módulo cards (ADR-012, SPEC-002 §5, SPEC-005 §7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from urbanopay.modules.cards.domain.entities import Card
from urbanopay.modules.cards.domain.enums import CardStatus, FareProfile
from urbanopay.modules.cards.infrastructure.models import CardModel

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def _to_card(model: CardModel) -> Card:
    return Card(
        id=model.id,
        customer_id=model.customer_id,
        card_last4=model.card_last4,
        fare_profile=FareProfile(model.fare_profile),
        balance=model.balance,
        status=CardStatus(model.status),
        expires_at=model.expires_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyCardRepository:
    """Implementação do port `CardRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_customer(self, customer_id: UUID) -> list[Card]:
        stmt = (
            sa.select(CardModel)
            .where(CardModel.customer_id == customer_id)
            .order_by(CardModel.created_at)
        )
        result = await self._session.execute(stmt)
        return [_to_card(model) for model in result.scalars()]

    async def get_owned(self, customer_id: UUID, card_id: UUID) -> Card | None:
        # UMA única query com ambos os filtros: inexistente e alheio são
        # indistinguíveis no resultado (anti-enumeração, SPEC-002 §5).
        stmt = sa.select(CardModel).where(
            CardModel.id == card_id,
            CardModel.customer_id == customer_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_card(model) if model is not None else None


class SqlAlchemyCardBalanceRepository:
    """Implementação do port `CardBalanceRepository` (SPEC-005 §7).

    Nunca comita: a fronteira transacional é do Unit of Work de quem credita,
    porque ledger, saldo e status precisam comitar juntos.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, card_id: UUID) -> Card | None:
        stmt = sa.select(CardModel).where(CardModel.id == card_id).with_for_update()
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_card(model) if model is not None else None

    async def apply_credit(self, *, card_id: UUID, new_balance: Decimal, at: datetime) -> None:
        """Grava o saldo resultante. Não soma e não arredonda (ADR-012)."""
        stmt = (
            sa.update(CardModel)
            .where(CardModel.id == card_id)
            .values(balance=new_balance, updated_at=at)
        )
        await self._session.execute(stmt)
