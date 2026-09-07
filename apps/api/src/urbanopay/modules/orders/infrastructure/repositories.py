"""Repositories SQLAlchemy do módulo orders (ADR-012, SPEC-003).

Contratos respeitados aqui:

- devolvem entidades de domínio, nunca modelos ORM;
- **nunca** executam commit;
- consultas de cliente aplicam titularidade na **mesma** query;
- `SELECT ... FOR UPDATE` respeita a ordem global
  `Order → Approval → Payment → Card → Fulfillment` (ADR-012).

Os itens são carregados em consulta separada, sem `relationship`: `FOR UPDATE`
sobre um join travaria as linhas das duas tabelas, e os itens não precisam de
lock — eles são congelados na criação e nunca mudam.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from urbanopay.modules.orders.domain.entities import LineItem, Order, Quote
from urbanopay.modules.orders.domain.enums import (
    CancellationReason,
    OperationType,
    OrderStatus,
)
from urbanopay.modules.orders.infrastructure.models import (
    OrderItemModel,
    OrderModel,
    QuoteItemModel,
    QuoteModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _to_line_item(model: QuoteItemModel | OrderItemModel) -> LineItem:
    return LineItem(
        description=model.description,
        quantity=model.quantity,
        unit_amount=model.unit_amount,
        total_amount=model.total_amount,
    )


def _to_quote(model: QuoteModel, items: tuple[LineItem, ...]) -> Quote:
    return Quote(
        id=model.id,
        customer_id=model.customer_id,
        card_id=model.card_id,
        operation_type=OperationType(model.operation_type),
        fare_profile=model.fare_profile,
        items=items,
        subtotal=model.subtotal,
        discount_amount=model.discount_amount,
        total=model.total,
        currency=model.currency,
        expires_at=model.expires_at,
        created_at=model.created_at,
    )


def _to_order(model: OrderModel, items: tuple[LineItem, ...]) -> Order:
    return Order(
        id=model.id,
        customer_id=model.customer_id,
        card_id=model.card_id,
        quote_id=model.quote_id,
        operation_type=OperationType(model.operation_type),
        status=OrderStatus(model.status),
        items=items,
        subtotal=model.subtotal,
        discount_amount=model.discount_amount,
        total=model.total,
        currency=model.currency,
        requires_approval=model.requires_approval,
        expires_at=model.expires_at,
        cancellation_reason=(
            CancellationReason(model.cancellation_reason)
            if model.cancellation_reason is not None
            else None
        ),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyQuoteRepository:
    """Implementação do port `QuoteRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, quote: Quote) -> None:
        self._session.add(
            QuoteModel(
                id=quote.id,
                customer_id=quote.customer_id,
                card_id=quote.card_id,
                operation_type=quote.operation_type.value,
                fare_profile=quote.fare_profile,
                subtotal=quote.subtotal,
                discount_amount=quote.discount_amount,
                total=quote.total,
                currency=quote.currency,
                expires_at=quote.expires_at,
                created_at=quote.created_at,
            )
        )
        # `flush` do pai ANTES dos itens: os models não declaram
        # `relationship()`, e sem ele o flush não garante a ordem de INSERT
        # exigida pela chave estrangeira `quote_items.quote_id`.
        await self._session.flush()
        for item in quote.items:
            self._session.add(
                QuoteItemModel(
                    id=uuid.uuid4(),
                    quote_id=quote.id,
                    description=item.description,
                    quantity=item.quantity,
                    unit_amount=item.unit_amount,
                    total_amount=item.total_amount,
                )
            )
        await self._session.flush()

    async def get_owned(self, *, customer_id: uuid.UUID, quote_id: uuid.UUID) -> Quote | None:
        # UMA query com ambos os filtros: inexistente e alheio são
        # indistinguíveis no resultado (anti-enumeração).
        stmt = sa.select(QuoteModel).where(
            QuoteModel.id == quote_id,
            QuoteModel.customer_id == customer_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        return _to_quote(model, await self._load_items(quote_id))

    async def _load_items(self, quote_id: uuid.UUID) -> tuple[LineItem, ...]:
        stmt = (
            sa.select(QuoteItemModel)
            .where(QuoteItemModel.quote_id == quote_id)
            .order_by(QuoteItemModel.description)
        )
        result = await self._session.execute(stmt)
        return tuple(_to_line_item(item) for item in result.scalars())


class SqlAlchemyOrderRepository:
    """Implementação do port `OrderRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: Order) -> None:
        self._session.add(
            OrderModel(
                id=order.id,
                customer_id=order.customer_id,
                card_id=order.card_id,
                quote_id=order.quote_id,
                operation_type=order.operation_type.value,
                status=order.status.value,
                subtotal=order.subtotal,
                discount_amount=order.discount_amount,
                total=order.total,
                currency=order.currency,
                requires_approval=order.requires_approval,
                expires_at=order.expires_at,
                cancellation_reason=None,
                created_at=order.created_at,
                updated_at=order.updated_at,
            )
        )
        # Mesma razão do `QuoteRepository.add`: o pai precisa existir antes de
        # `order_items.order_id`.
        await self._session.flush()
        for item in order.items:
            self._session.add(
                OrderItemModel(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    description=item.description,
                    quantity=item.quantity,
                    unit_amount=item.unit_amount,
                    total_amount=item.total_amount,
                )
            )
        await self._session.flush()

    async def get(self, order_id: uuid.UUID) -> Order | None:
        stmt = sa.select(OrderModel).where(OrderModel.id == order_id)
        return await self._resolve(stmt, order_id)

    async def get_owned(self, *, customer_id: uuid.UUID, order_id: uuid.UUID) -> Order | None:
        stmt = sa.select(OrderModel).where(
            OrderModel.id == order_id,
            OrderModel.customer_id == customer_id,
        )
        return await self._resolve(stmt, order_id)

    async def get_for_update(self, order_id: uuid.UUID) -> Order | None:
        stmt = sa.select(OrderModel).where(OrderModel.id == order_id).with_for_update()
        return await self._resolve(stmt, order_id)

    async def get_owned_for_update(
        self, *, customer_id: uuid.UUID, order_id: uuid.UUID
    ) -> Order | None:
        stmt = (
            sa.select(OrderModel)
            .where(OrderModel.id == order_id, OrderModel.customer_id == customer_id)
            .with_for_update()
        )
        return await self._resolve(stmt, order_id)

    async def update(self, order: Order) -> None:
        """Persiste a nova versão. Itens são congelados e não são tocados."""
        stmt = (
            sa.update(OrderModel)
            .where(OrderModel.id == order.id)
            .values(
                status=order.status.value,
                cancellation_reason=(
                    order.cancellation_reason.value
                    if order.cancellation_reason is not None
                    else None
                ),
                updated_at=order.updated_at,
            )
        )
        await self._session.execute(stmt)

    async def has_quote_been_consumed(self, quote_id: uuid.UUID) -> bool:
        stmt = (
            sa.select(sa.func.count())
            .select_from(OrderModel)
            .where(OrderModel.quote_id == quote_id)
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    async def _resolve(
        self, stmt: sa.Select[tuple[OrderModel]], order_id: uuid.UUID
    ) -> Order | None:
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        return _to_order(model, await self._load_items(order_id))

    async def _load_items(self, order_id: uuid.UUID) -> tuple[LineItem, ...]:
        stmt = (
            sa.select(OrderItemModel)
            .where(OrderItemModel.order_id == order_id)
            .order_by(OrderItemModel.description)
        )
        result = await self._session.execute(stmt)
        return tuple(_to_line_item(item) for item in result.scalars())
