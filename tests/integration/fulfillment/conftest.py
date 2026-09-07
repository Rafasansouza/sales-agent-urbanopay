"""Fixtures de integração da SPEC-005.

Dados fictícios apenas, sem seed em migration. O cenário mínimo é caro de
montar porque o fulfillment é o fim da cadeia: exige cliente, cartão, Quote,
Order pago e Payment aprovado — todos com as chaves estrangeiras reais.

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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from urbanopay.modules.cards.infrastructure.models import CardModel
from urbanopay.modules.fulfillment.application.services import (
    FulfillmentRecoveryService,
    FulfillmentService,
)
from urbanopay.modules.fulfillment.infrastructure.models import (
    CardLedgerEntryModel,
    FulfillmentModel,
    ReceiptModel,
)
from urbanopay.modules.fulfillment.infrastructure.repositories import (
    SqlAlchemyFulfillmentRecoveryPort,
)
from urbanopay.modules.fulfillment.infrastructure.uow import (
    SqlAlchemyFulfillmentUnitOfWork,
)
from urbanopay.modules.identity.infrastructure.models import CustomerModel
from urbanopay.modules.orders.infrastructure.models import (
    OrderItemModel,
    OrderModel,
    QuoteItemModel,
    QuoteModel,
)
from urbanopay.modules.payments.infrastructure.models import PaymentModel

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
LATER = FIXED_NOW + timedelta(minutes=1)
TTL = timedelta(minutes=10)


class Scenario:
    """IDs do cenário montado, para asserção e limpeza."""

    def __init__(
        self,
        *,
        customer_id: uuid.UUID,
        card_id: uuid.UUID,
        quote_id: uuid.UUID,
        order_id: uuid.UUID,
        payment_id: uuid.UUID | None,
        total: Decimal,
        balance: Decimal,
    ) -> None:
        self.customer_id = customer_id
        self.card_id = card_id
        self.quote_id = quote_id
        self.order_id = order_id
        self.payment_id = payment_id
        self.total = total
        self.balance = balance


class FulfillmentTestData:
    """Monta cenários fictícios e limpa por IDs rastreados."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.customer_ids: list[uuid.UUID] = []
        self.card_ids: list[uuid.UUID] = []

    async def add_scenario(
        self,
        *,
        total: Decimal = Decimal("50.00"),
        balance: Decimal = Decimal("0.00"),
        order_status: str = "PAID",
        card_status: str = "ACTIVE",
        payment_status: str | None = "APPROVED",
    ) -> Scenario:
        """Cliente, cartão, Quote, Order e Payment, todos persistidos."""
        customer_id = uuid.uuid4()
        card_id = uuid.uuid4()
        quote_id = uuid.uuid4()
        order_id = uuid.uuid4()
        payment_id = uuid.uuid4() if payment_status is not None else None

        async with self._session_factory() as session:
            session.add(
                CustomerModel(
                    id=customer_id,
                    name="Cliente Ficticio",
                    cpf_hash=f"fake-hash-{customer_id}",
                    status="ACTIVE",
                    created_at=FIXED_NOW,
                    updated_at=FIXED_NOW,
                )
            )
            # `flush` entre pai e filho: sem `relationship()`, a ordem de
            # INSERT por dependência de FK não é garantida pelo flush.
            await session.flush()
            session.add(
                CardModel(
                    id=card_id,
                    customer_id=customer_id,
                    card_last4="4821",
                    fare_profile="INTEGRAL",
                    balance=balance,
                    status=card_status,
                    expires_at=None,
                    created_at=FIXED_NOW,
                    updated_at=FIXED_NOW,
                )
            )
            session.add(
                QuoteModel(
                    id=quote_id,
                    customer_id=customer_id,
                    card_id=card_id,
                    operation_type="RECHARGE",
                    fare_profile="INTEGRAL",
                    subtotal=total,
                    discount_amount=Decimal("0.00"),
                    total=total,
                    currency="BRL",
                    expires_at=FIXED_NOW + TTL,
                    created_at=FIXED_NOW,
                )
            )
            await session.flush()
            session.add(
                QuoteItemModel(
                    id=uuid.uuid4(),
                    quote_id=quote_id,
                    description="Recarga Livre",
                    quantity=1,
                    unit_amount=total,
                    total_amount=total,
                )
            )
            session.add(
                OrderModel(
                    id=order_id,
                    customer_id=customer_id,
                    card_id=card_id,
                    quote_id=quote_id,
                    operation_type="RECHARGE",
                    status=order_status,
                    subtotal=total,
                    discount_amount=Decimal("0.00"),
                    total=total,
                    currency="BRL",
                    requires_approval=False,
                    expires_at=FIXED_NOW + TTL,
                    cancellation_reason=None,
                    created_at=FIXED_NOW,
                    updated_at=FIXED_NOW,
                )
            )
            await session.flush()
            session.add(
                OrderItemModel(
                    id=uuid.uuid4(),
                    order_id=order_id,
                    description="Recarga Livre",
                    quantity=1,
                    unit_amount=total,
                    total_amount=total,
                )
            )
            if payment_id is not None:
                session.add(
                    PaymentModel(
                        id=payment_id,
                        order_id=order_id,
                        provider="FAKE",
                        provider_payment_id=f"fake-{payment_id}",
                        method="PIX",
                        amount=total,
                        currency="BRL",
                        status=payment_status,
                        idempotency_key=f"pay-{order_id}",
                        created_at=FIXED_NOW,
                        updated_at=FIXED_NOW,
                    )
                )
            await session.commit()

        self.customer_ids.append(customer_id)
        self.card_ids.append(card_id)
        return Scenario(
            customer_id=customer_id,
            card_id=card_id,
            quote_id=quote_id,
            order_id=order_id,
            payment_id=payment_id,
            total=total,
            balance=balance,
        )

    async def balance_of(self, card_id: uuid.UUID) -> Decimal:
        async with self._session_factory() as session:
            card = await session.get(CardModel, card_id)
            assert card is not None
            return card.balance

    async def count_ledger(self, order_id: uuid.UUID) -> int:
        return await self._count(CardLedgerEntryModel, CardLedgerEntryModel.order_id, order_id)

    async def count_receipts(self, order_id: uuid.UUID) -> int:
        return await self._count(ReceiptModel, ReceiptModel.order_id, order_id)

    async def count_fulfillments(self, order_id: uuid.UUID) -> int:
        return await self._count(FulfillmentModel, FulfillmentModel.order_id, order_id)

    async def order_status(self, order_id: uuid.UUID) -> str:
        async with self._session_factory() as session:
            order = await session.get(OrderModel, order_id)
            assert order is not None
            return order.status

    async def fulfillment_status(self, order_id: uuid.UUID) -> str | None:
        async with self._session_factory() as session:
            stmt = sa.select(FulfillmentModel.status).where(FulfillmentModel.order_id == order_id)
            return (await session.execute(stmt)).scalar_one_or_none()

    async def _count(self, model: type, column: object, value: uuid.UUID) -> int:
        async with self._session_factory() as session:
            stmt = sa.select(sa.func.count()).select_from(model).where(column == value)  # type: ignore[arg-type]
            return int((await session.execute(stmt)).scalar_one())

    async def cleanup(self) -> None:
        """Remove tudo o que os testes criaram, na ordem reversa das FKs."""
        if not self.customer_ids:
            return
        async with self._session_factory() as session:
            order_ids = list(
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
            if order_ids:
                await session.execute(
                    sa.delete(ReceiptModel).where(ReceiptModel.order_id.in_(order_ids))
                )
                await session.execute(
                    sa.delete(CardLedgerEntryModel).where(
                        CardLedgerEntryModel.order_id.in_(order_ids)
                    )
                )
                await session.execute(
                    sa.delete(FulfillmentModel).where(FulfillmentModel.order_id.in_(order_ids))
                )
                await session.execute(
                    sa.delete(PaymentModel).where(PaymentModel.order_id.in_(order_ids))
                )
                await session.execute(
                    sa.delete(OrderItemModel).where(OrderItemModel.order_id.in_(order_ids))
                )
                await session.execute(sa.delete(OrderModel).where(OrderModel.id.in_(order_ids)))

            quote_ids = list(
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


@pytest_asyncio.fixture
async def data(
    migrated: None, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[FulfillmentTestData]:
    helper = FulfillmentTestData(session_factory)
    try:
        yield helper
    finally:
        await helper.cleanup()


@pytest.fixture
def fulfillment_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> FulfillmentService:
    return FulfillmentService(SqlAlchemyFulfillmentUnitOfWork(session_factory))


@pytest.fixture
def recovery_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> FulfillmentRecoveryService:
    """Serviço de consistência sobre uma sessão dedicada, somente leitura."""

    class _Recovery:
        def __init__(self) -> None:
            self._factory = session_factory

        async def find_paid_orders_without_completed_fulfillment(
            self, *, limit: int
        ) -> list[uuid.UUID]:
            async with self._factory() as session:
                port = SqlAlchemyFulfillmentRecoveryPort(session)
                return await port.find_paid_orders_without_completed_fulfillment(limit=limit)

        async def find_completed_fulfillments_without_ledger(
            self, *, limit: int
        ) -> list[uuid.UUID]:
            async with self._factory() as session:
                port = SqlAlchemyFulfillmentRecoveryPort(session)
                return await port.find_completed_fulfillments_without_ledger(limit=limit)

        async def find_ledger_without_completed_fulfillment(self, *, limit: int) -> list[uuid.UUID]:
            async with self._factory() as session:
                port = SqlAlchemyFulfillmentRecoveryPort(session)
                return await port.find_ledger_without_completed_fulfillment(limit=limit)

    return FulfillmentRecoveryService(_Recovery())
