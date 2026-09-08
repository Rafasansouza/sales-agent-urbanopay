"""Fixtures de integração da SPEC-004 (Etapa 1).

Aqui a camada de tools roda sobre o **composition root real** e o PostgreSQL
real: `build_agent_services` é exatamente a função que a Etapa 3 usará. O que
é substituído são os dois pontos que a SPEC autoriza substituir em teste —
`FakeOtpGenerator` e `FakePaymentProvider` (ADR-007, ADR-010).

⚠️ Injetar o gerador de OTP na composição **não é contornar a autenticação**:
o desafio continua com hash, expiração, limite de tentativas e uso único, e
`verify_otp` executa por inteiro. O teste conhece o código porque o injetou —
que é a mesma técnica usada nos testes de integração da SPEC-002. O canal de
OTP para uma demonstração **humana** continua aberto em H-12.

Dados fictícios apenas. Limpeza determinística por IDs rastreados, na ordem
reversa das FKs.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.unit.identity.fakes import FakeOtpGenerator
from urbanopay.core.config import Settings
from urbanopay.modules.agent.application.executor import ToolExecutor
from urbanopay.modules.agent.domain.conversation import ConversationState
from urbanopay.modules.agent.infrastructure.composition import (
    AgentServices,
    build_agent_services,
)
from urbanopay.modules.approvals.infrastructure.models import ApprovalModel
from urbanopay.modules.cards.infrastructure.models import CardModel
from urbanopay.modules.fulfillment.infrastructure.models import (
    CardLedgerEntryModel,
    FulfillmentModel,
    ReceiptModel,
)
from urbanopay.modules.identity.domain.value_objects import IdentityHasher
from urbanopay.modules.identity.infrastructure.models import (
    AuthChallengeModel,
    CustomerModel,
    SessionModel,
)
from urbanopay.modules.orders.infrastructure.models import (
    OrderItemModel,
    OrderModel,
    QuoteItemModel,
    QuoteModel,
)
from urbanopay.modules.payments.infrastructure.models import PaymentEventModel, PaymentModel
from urbanopay.providers.payments.fake import FakePaymentProvider

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
FIXED_OTP = "123456"


def _fictional_cpf() -> str:
    """Documento ficticio unico por chamada.

    Unico de proposito: `customers.cpf_hash` e unico no banco, e uma constante
    compartilhada faria dois testes — ou duas execucoes — colidirem numa
    constraint que nao tem nada a ver com o que esta sendo verificado.
    """
    return str(uuid.uuid4().int)[:11]


@dataclass(frozen=True, slots=True)
class SeededCustomer:
    """Cliente ficticio inserido pela fixture, com o documento que o autentica."""

    id: uuid.UUID
    cpf: str


@pytest.fixture(scope="session")
def hasher(settings: Settings) -> IdentityHasher:
    return IdentityHasher(settings.identity_hash_secret.get_secret_value())


class AgentTestData:
    """Cenário fictício mínimo da jornada de recarga."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], hasher: IdentityHasher
    ) -> None:
        self._session_factory = session_factory
        self._hasher = hasher
        self.customer_ids: list[uuid.UUID] = []
        self.card_ids: list[uuid.UUID] = []
        self.session_ids: list[uuid.UUID] = []

    def track_session(self, session_id: uuid.UUID) -> None:
        self.session_ids.append(session_id)

    async def add_customer(self, *, status: str = "ACTIVE") -> SeededCustomer:
        customer_id = uuid.uuid4()
        cpf = _fictional_cpf()
        async with self._session_factory() as session:
            session.add(
                CustomerModel(
                    id=customer_id,
                    name="Cliente Ficticio",
                    cpf_hash=self._hasher.hash_cpf(cpf),
                    status=status,
                    created_at=FIXED_NOW,
                    updated_at=FIXED_NOW,
                )
            )
            await session.commit()
        self.customer_ids.append(customer_id)
        return SeededCustomer(id=customer_id, cpf=cpf)

    async def add_card(
        self,
        *,
        customer_id: uuid.UUID,
        last4: str = "4821",
        fare_profile: str = "INTEGRAL",
        balance: str = "21.50",
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

    async def set_card_status(self, card_id: uuid.UUID, status: str) -> None:
        """Muda o estado do cartão fora da jornada — como um back-office faria."""
        async with self._session_factory() as session:
            await session.execute(
                sa.update(CardModel).where(CardModel.id == card_id).values(status=status)
            )
            await session.commit()

    async def expire_session(self, session_id: uuid.UUID) -> None:
        """Envelhece a sessão no banco, sem manipular relógio global.

        `created_at` recua junto com `expires_at`: a constraint
        `ck_sessions_expiry_after_creation` exige que a expiração seja
        posterior à criação, e é ela que garante que o estado escrito aqui é
        um estado que a aplicação também poderia ter produzido.
        """
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            await session.execute(
                sa.update(SessionModel)
                .where(SessionModel.id == session_id)
                .values(
                    created_at=now - timedelta(hours=2),
                    expires_at=now - timedelta(minutes=1),
                )
            )
            await session.commit()

    async def balance_of(self, card_id: uuid.UUID) -> Decimal:
        async with self._session_factory() as session:
            card = await session.get(CardModel, card_id)
            assert card is not None
            return card.balance

    async def order_status(self, order_id: uuid.UUID) -> str:
        async with self._session_factory() as session:
            order = await session.get(OrderModel, order_id)
            assert order is not None
            return order.status

    async def count_payments(self, order_id: uuid.UUID) -> int:
        async with self._session_factory() as session:
            stmt = (
                sa.select(sa.func.count())
                .select_from(PaymentModel)
                .where(PaymentModel.order_id == order_id)
            )
            return int((await session.execute(stmt)).scalar_one())

    async def count_ledger(self, order_id: uuid.UUID) -> int:
        async with self._session_factory() as session:
            stmt = (
                sa.select(sa.func.count())
                .select_from(CardLedgerEntryModel)
                .where(CardLedgerEntryModel.order_id == order_id)
            )
            return int((await session.execute(stmt)).scalar_one())

    async def cleanup(self, engine: AsyncEngine) -> None:
        if not self.customer_ids:
            return
        async with engine.begin() as conn:
            order_ids = list(
                (
                    await conn.execute(
                        sa.select(OrderModel.id).where(
                            OrderModel.customer_id.in_(self.customer_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if order_ids:
                await conn.execute(
                    sa.delete(ReceiptModel).where(ReceiptModel.order_id.in_(order_ids))
                )
                await conn.execute(
                    sa.delete(CardLedgerEntryModel).where(
                        CardLedgerEntryModel.order_id.in_(order_ids)
                    )
                )
                await conn.execute(
                    sa.delete(FulfillmentModel).where(FulfillmentModel.order_id.in_(order_ids))
                )
                payment_ids = list(
                    (
                        await conn.execute(
                            sa.select(PaymentModel.id).where(PaymentModel.order_id.in_(order_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
                if payment_ids:
                    await conn.execute(
                        sa.delete(PaymentEventModel).where(
                            PaymentEventModel.payment_id.in_(payment_ids)
                        )
                    )
                await conn.execute(
                    sa.delete(PaymentModel).where(PaymentModel.order_id.in_(order_ids))
                )
                # `approvals` referencia `orders`: sem esta remoção o DELETE do
                # Order aborta a transação de limpeza, e o resíduo derruba a
                # execução seguinte por colisão de índice único.
                await conn.execute(
                    sa.delete(ApprovalModel).where(ApprovalModel.order_id.in_(order_ids))
                )
                await conn.execute(
                    sa.delete(OrderItemModel).where(OrderItemModel.order_id.in_(order_ids))
                )
                await conn.execute(sa.delete(OrderModel).where(OrderModel.id.in_(order_ids)))

            quote_ids = list(
                (
                    await conn.execute(
                        sa.select(QuoteModel.id).where(
                            QuoteModel.customer_id.in_(self.customer_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if quote_ids:
                await conn.execute(
                    sa.delete(QuoteItemModel).where(QuoteItemModel.quote_id.in_(quote_ids))
                )
                await conn.execute(sa.delete(QuoteModel).where(QuoteModel.id.in_(quote_ids)))

            await conn.execute(
                sa.delete(AuthChallengeModel).where(
                    AuthChallengeModel.customer_id.in_(self.customer_ids)
                )
            )
            if self.session_ids:
                await conn.execute(
                    sa.delete(SessionModel).where(SessionModel.id.in_(self.session_ids))
                )
            await conn.execute(sa.delete(CardModel).where(CardModel.id.in_(self.card_ids)))
            await conn.execute(
                sa.delete(CustomerModel).where(CustomerModel.id.in_(self.customer_ids))
            )


@pytest_asyncio.fixture
async def data(
    migrated: None,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
) -> AsyncIterator[AgentTestData]:
    holder = AgentTestData(session_factory, hasher)
    try:
        yield holder
    finally:
        await holder.cleanup(engine)


@pytest.fixture
def provider() -> FakePaymentProvider:
    return FakePaymentProvider()


@pytest.fixture
def services(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    hasher: IdentityHasher,
    provider: FakePaymentProvider,
) -> AgentServices:
    """Composition root real, com os dois dublês que a SPEC autoriza."""
    return build_agent_services(
        session_factory,
        settings=settings,
        hasher=hasher,
        otp_generator=FakeOtpGenerator(FIXED_OTP),
        payment_provider=provider,
    )


@pytest.fixture
def executor(services: AgentServices) -> ToolExecutor:
    return ToolExecutor(services)


@pytest_asyncio.fixture
async def anonymous_state(services: AgentServices, data: AgentTestData) -> ConversationState:
    """Conversa nova sobre uma sessão anônima recém-criada."""
    session = await services.sessions.create_anonymous_session()
    data.track_session(session.id)
    return ConversationState(conversation_id=uuid.uuid4(), session_id=session.id)
