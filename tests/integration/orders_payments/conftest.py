"""Fixtures de integração da SPEC-003.

Dados fictícios apenas, sem seed em migration. Cliente e cartão são criados
por fixture porque Quote e Order têm chave estrangeira para eles.

Limpeza determinística por IDs rastreados, na ordem reversa das chaves
estrangeiras — nenhum `TRUNCATE`, nenhuma dependência de ordem de teste.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from urbanopay.db.idempotency import IdempotencyRecordModel
from urbanopay.modules.approvals.infrastructure.models import ApprovalModel
from urbanopay.modules.cards.infrastructure.models import CardModel
from urbanopay.modules.identity.infrastructure.models import CustomerModel
from urbanopay.modules.orders.application.services import OrderService, QuoteService
from urbanopay.modules.orders.domain.policies import ApprovalPolicy
from urbanopay.modules.orders.infrastructure.models import (
    OrderItemModel,
    OrderModel,
    QuoteItemModel,
    QuoteModel,
)
from urbanopay.modules.orders.infrastructure.uow import SqlAlchemyOrdersUnitOfWork
from urbanopay.modules.payments.application.services import PaymentService
from urbanopay.modules.payments.infrastructure.models import (
    PaymentEventModel,
    PaymentModel,
)
from urbanopay.modules.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from urbanopay.providers.payments.fake import FakePaymentProvider

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
TTL = timedelta(minutes=10)


class OrdersPaymentsTestData:
    """Cria dados fictícios e limpa por IDs rastreados."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.customer_ids: list[uuid.UUID] = []
        self.card_ids: list[uuid.UUID] = []

    async def add_customer_with_card(
        self, *, name: str = "Cliente Ficticio", cpf_hash: str | None = None
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """Cliente e cartão ativos, ambos fictícios."""
        customer_id = uuid.uuid4()
        card_id = uuid.uuid4()
        async with self._session_factory() as session:
            session.add(
                CustomerModel(
                    id=customer_id,
                    name=name,
                    # Valor opaco fictício: nenhum CPF real, nem mesmo hash de um.
                    cpf_hash=cpf_hash or f"fake-hash-{customer_id}",
                    status="ACTIVE",
                    created_at=FIXED_NOW,
                    updated_at=FIXED_NOW,
                )
            )
            # `flush` explícito antes do cartão: os models não declaram
            # `relationship()`, então a ordenação de INSERT por dependência de
            # chave estrangeira não é garantida pelo flush — sem isto, `cards`
            # pode ser inserido antes de `customers` e violar a FK.
            await session.flush()
            session.add(
                CardModel(
                    id=card_id,
                    customer_id=customer_id,
                    card_last4="4821",
                    fare_profile="INTEGRAL",
                    balance=Decimal("0.00"),
                    status="ACTIVE",
                    expires_at=None,
                    created_at=FIXED_NOW,
                    updated_at=FIXED_NOW,
                )
            )
            await session.commit()
        self.customer_ids.append(customer_id)
        self.card_ids.append(card_id)
        return customer_id, card_id

    async def cleanup(self) -> None:
        """Remove tudo o que os testes criaram, na ordem reversa das FKs."""
        if not self.customer_ids:
            return
        async with self._session_factory() as session:
            order_ids = (
                (
                    await session.execute(
                        sa.select(OrderModel.id).where(
                            OrderModel.customer_id.in_(self.customer_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            payment_ids = (
                (
                    await session.execute(
                        sa.select(PaymentModel.id).where(PaymentModel.order_id.in_(order_ids))
                    )
                )
                .scalars()
                .all()
                if order_ids
                else []
            )
            if payment_ids:
                await session.execute(
                    sa.delete(PaymentEventModel).where(
                        PaymentEventModel.payment_id.in_(payment_ids)
                    )
                )
                await session.execute(
                    sa.delete(PaymentModel).where(PaymentModel.id.in_(payment_ids))
                )
            if order_ids:
                await session.execute(
                    sa.delete(ApprovalModel).where(ApprovalModel.order_id.in_(order_ids))
                )
                await session.execute(
                    sa.delete(OrderItemModel).where(OrderItemModel.order_id.in_(order_ids))
                )
                await session.execute(sa.delete(OrderModel).where(OrderModel.id.in_(order_ids)))

            quote_ids = (
                (
                    await session.execute(
                        sa.select(QuoteModel.id).where(
                            QuoteModel.customer_id.in_(self.customer_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if quote_ids:
                await session.execute(
                    sa.delete(QuoteItemModel).where(QuoteItemModel.quote_id.in_(quote_ids))
                )
                await session.execute(sa.delete(QuoteModel).where(QuoteModel.id.in_(quote_ids)))

            await session.execute(sa.delete(CardModel).where(CardModel.id.in_(self.card_ids)))
            await session.execute(
                sa.delete(CustomerModel).where(CustomerModel.id.in_(self.customer_ids))
            )
            await session.commit()

    async def clear_idempotency(self, *keys: str) -> None:
        """Remove registros de idempotência criados pelos testes."""
        if not keys:
            return
        async with self._session_factory() as session:
            await session.execute(
                sa.delete(IdempotencyRecordModel).where(IdempotencyRecordModel.key.in_(keys))
            )
            await session.commit()


@pytest_asyncio.fixture
async def data(
    migrated: None, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[OrdersPaymentsTestData]:
    helper = OrdersPaymentsTestData(session_factory)
    try:
        yield helper
    finally:
        await helper.cleanup()


@pytest.fixture
def quote_service(session_factory: async_sessionmaker[AsyncSession]) -> QuoteService:
    return QuoteService(SqlAlchemyOrdersUnitOfWork(session_factory), quote_ttl=TTL)


@pytest.fixture
def order_service(session_factory: async_sessionmaker[AsyncSession]) -> OrderService:
    return OrderService(
        SqlAlchemyOrdersUnitOfWork(session_factory), ApprovalPolicy(), draft_ttl=TTL
    )


@pytest.fixture
def provider() -> FakePaymentProvider:
    """Nenhuma chamada real a provider na CI (ADR-007, ADR-010)."""
    return FakePaymentProvider()


@pytest.fixture
def payment_service(
    session_factory: async_sessionmaker[AsyncSession], provider: FakePaymentProvider
) -> PaymentService:
    return PaymentService(SqlAlchemyPaymentsUnitOfWork(session_factory), provider)
