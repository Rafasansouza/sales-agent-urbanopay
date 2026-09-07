"""Fixtures de integração da SPEC-002.

Identidades e cartões são FIXTURES fictícias (decisão aprovada: sem seed em
migration) — o dataset nominal de SPEC-002 §13 acrescido do cartão EXPIRED e
do cenário cross-user exigidos pelos testes de §14 (resolve A-12 na prática).

Limpeza determinística por IDs rastreados, na ordem reversa das FKs.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.unit.identity.fakes import FakeOtpGenerator
from urbanopay.core.config import Settings
from urbanopay.modules.cards.infrastructure.models import CardModel
from urbanopay.modules.identity.application.services import (
    AuthenticationService,
    SessionService,
)
from urbanopay.modules.identity.domain.value_objects import IdentityHasher
from urbanopay.modules.identity.infrastructure.models import (
    AuthChallengeModel,
    CustomerModel,
    SessionModel,
)
from urbanopay.modules.identity.infrastructure.uow import SqlAlchemyIdentityUnitOfWork

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
FIXED_OTP = "123456"


@pytest.fixture(scope="session")
def hasher(settings: Settings) -> IdentityHasher:
    """Hasher com o segredo do ambiente de teste (fictício)."""
    return IdentityHasher(settings.identity_hash_secret.get_secret_value())


class IdentityCardsTestData:
    """Insere dados fictícios rastreando IDs para limpeza determinística."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hasher: IdentityHasher,
    ) -> None:
        self._session_factory = session_factory
        self._hasher = hasher
        self.customer_ids: list[uuid.UUID] = []
        self.session_ids: list[uuid.UUID] = []
        self.card_ids: list[uuid.UUID] = []

    def track_session(self, session_id: uuid.UUID) -> None:
        """Rastreia sessões criadas pelos serviços durante o teste."""
        self.session_ids.append(session_id)

    async def add_customer(
        self,
        *,
        name: str,
        cpf: str,
        status: str = "ACTIVE",
    ) -> uuid.UUID:
        customer_id = uuid.uuid4()
        async with self._session_factory() as session:
            session.add(
                CustomerModel(
                    id=customer_id,
                    name=name,
                    cpf_hash=self._hasher.hash_cpf(cpf),
                    status=status,
                    created_at=FIXED_NOW,
                    updated_at=FIXED_NOW,
                )
            )
            await session.commit()
        self.customer_ids.append(customer_id)
        return customer_id

    async def add_card(
        self,
        *,
        customer_id: uuid.UUID,
        last4: str,
        fare_profile: str,
        balance: str,
        status: str = "ACTIVE",
    ) -> uuid.UUID:
        card_id = uuid.uuid4()
        async with self._session_factory() as session:
            session.add(
                CardModel(
                    id=card_id,
                    customer_id=customer_id,
                    card_last4=last4,
                    fare_profile=fare_profile,
                    balance=Decimal(balance),
                    status=status,
                    expires_at=None,
                    created_at=FIXED_NOW,
                    updated_at=FIXED_NOW,
                )
            )
            await session.commit()
        self.card_ids.append(card_id)
        return card_id


@pytest_asyncio.fixture
async def data(
    migrated: None,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
) -> AsyncIterator[IdentityCardsTestData]:
    holder = IdentityCardsTestData(session_factory, hasher)
    try:
        yield holder
    finally:
        async with engine.begin() as conn:
            if holder.session_ids:
                await conn.execute(
                    sa.delete(AuthChallengeModel).where(
                        AuthChallengeModel.session_id.in_(holder.session_ids)
                    )
                )
                await conn.execute(
                    sa.delete(SessionModel).where(SessionModel.id.in_(holder.session_ids))
                )
            if holder.card_ids:
                await conn.execute(sa.delete(CardModel).where(CardModel.id.in_(holder.card_ids)))
            if holder.customer_ids:
                await conn.execute(
                    sa.delete(CustomerModel).where(CustomerModel.id.in_(holder.customer_ids))
                )


def build_services(
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
    *,
    otp_max_attempts: int = 5,
    otp_ttl: timedelta = timedelta(minutes=5),
    session_ttl: timedelta = timedelta(minutes=30),
) -> tuple[SessionService, AuthenticationService]:
    """Composição real: UoW do identity + gerador determinístico de teste."""
    uow = SqlAlchemyIdentityUnitOfWork(session_factory)
    sessions = SessionService(uow, session_ttl=session_ttl)
    auth = AuthenticationService(
        uow,
        hasher,
        FakeOtpGenerator(FIXED_OTP),
        otp_ttl=otp_ttl,
        otp_max_attempts=otp_max_attempts,
        session_ttl=session_ttl,
    )
    return sessions, auth
