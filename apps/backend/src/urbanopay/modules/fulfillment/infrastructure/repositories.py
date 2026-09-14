"""Repositories SQLAlchemy do módulo fulfillment (ADR-012, SPEC-005).

Nenhum executa commit: ledger, saldo, fulfillment, Order e comprovante
precisam comitar juntos, e a fronteira é do Unit of Work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from urbanopay.modules.fulfillment.domain.entities import (
    CardLedgerEntry,
    Fulfillment,
    Receipt,
)
from urbanopay.modules.fulfillment.domain.enums import (
    DocumentKind,
    FailureClass,
    FulfillmentStatus,
    FulfillmentType,
    LedgerEntryType,
)
from urbanopay.modules.fulfillment.infrastructure.models import (
    CardLedgerEntryModel,
    FulfillmentModel,
    ReceiptModel,
)
from urbanopay.modules.orders.infrastructure.models import OrderModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def _to_fulfillment(model: FulfillmentModel) -> Fulfillment:
    return Fulfillment(
        id=model.id,
        order_id=model.order_id,
        payment_id=model.payment_id,
        card_id=model.card_id,
        fulfillment_type=FulfillmentType(model.fulfillment_type),
        status=FulfillmentStatus(model.status),
        failure_reason=model.failure_reason,
        failure_class=(
            FailureClass(model.failure_class) if model.failure_class is not None else None
        ),
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


def _to_entry(model: CardLedgerEntryModel) -> CardLedgerEntry:
    return CardLedgerEntry(
        id=model.id,
        fulfillment_id=model.fulfillment_id,
        order_id=model.order_id,
        card_id=model.card_id,
        entry_type=LedgerEntryType(model.entry_type),
        amount=model.amount,
        currency=model.currency,
        balance_before=model.balance_before,
        balance_after=model.balance_after,
        created_at=model.created_at,
    )


def _to_receipt(model: ReceiptModel) -> Receipt:
    return Receipt(
        id=model.id,
        order_id=model.order_id,
        payment_id=model.payment_id,
        fulfillment_id=model.fulfillment_id,
        card_last4=model.card_last4,
        amount=model.amount,
        currency=model.currency,
        operation_type=model.operation_type,
        document_kind=DocumentKind(model.document_kind),
        disclaimer_version=model.disclaimer_version,
        issued_at=model.issued_at,
    )


class SqlAlchemyFulfillmentRepository:
    """Implementação do port `FulfillmentRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, fulfillment: Fulfillment) -> None:
        self._session.add(
            FulfillmentModel(
                id=fulfillment.id,
                order_id=fulfillment.order_id,
                payment_id=fulfillment.payment_id,
                card_id=fulfillment.card_id,
                fulfillment_type=fulfillment.fulfillment_type.value,
                status=fulfillment.status.value,
                failure_reason=fulfillment.failure_reason,
                failure_class=(
                    fulfillment.failure_class.value
                    if fulfillment.failure_class is not None
                    else None
                ),
                created_at=fulfillment.created_at,
                updated_at=fulfillment.updated_at,
                completed_at=fulfillment.completed_at,
            )
        )
        # `flush` explícito: é aqui que `uq_fulfillments_order_id` reprova um
        # segundo fulfillment, ainda dentro da transação de quem chamou.
        await self._session.flush()

    async def get_for_order(self, order_id: UUID) -> Fulfillment | None:
        stmt = sa.select(FulfillmentModel).where(FulfillmentModel.order_id == order_id)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_fulfillment(model) if model is not None else None

    async def get_for_order_for_update(self, order_id: UUID) -> Fulfillment | None:
        # Adquirido DEPOIS do lock do Order e ANTES do lock do Card.
        stmt = (
            sa.select(FulfillmentModel)
            .where(FulfillmentModel.order_id == order_id)
            .with_for_update()
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_fulfillment(model) if model is not None else None

    async def update(self, fulfillment: Fulfillment) -> None:
        stmt = (
            sa.update(FulfillmentModel)
            .where(FulfillmentModel.id == fulfillment.id)
            .values(
                payment_id=fulfillment.payment_id,
                status=fulfillment.status.value,
                failure_reason=fulfillment.failure_reason,
                failure_class=(
                    fulfillment.failure_class.value
                    if fulfillment.failure_class is not None
                    else None
                ),
                updated_at=fulfillment.updated_at,
                completed_at=fulfillment.completed_at,
            )
        )
        await self._session.execute(stmt)


class SqlAlchemyCardLedgerRepository:
    """Implementação do port `CardLedgerRepository`.

    Sem `update` e sem `delete`, por contrato: o ledger é imutável (§7.1). A
    ausência dos métodos é a garantia estrutural — não há como reescrever
    histórico financeiro por este caminho.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: CardLedgerEntry) -> None:
        self._session.add(
            CardLedgerEntryModel(
                id=entry.id,
                fulfillment_id=entry.fulfillment_id,
                order_id=entry.order_id,
                card_id=entry.card_id,
                entry_type=entry.entry_type.value,
                amount=entry.amount,
                currency=entry.currency,
                balance_before=entry.balance_before,
                balance_after=entry.balance_after,
                created_at=entry.created_at,
            )
        )
        # `flush` explícito: aqui o índice único parcial reprova um segundo
        # crédito para o mesmo Order, dentro da transação de quem chamou.
        await self._session.flush()

    async def get_recharge_credit_for_order(self, order_id: UUID) -> CardLedgerEntry | None:
        stmt = sa.select(CardLedgerEntryModel).where(
            CardLedgerEntryModel.order_id == order_id,
            CardLedgerEntryModel.entry_type == LedgerEntryType.RECHARGE_CREDIT.value,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entry(model) if model is not None else None


class SqlAlchemyReceiptRepository:
    """Implementação do port `ReceiptRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, receipt: Receipt) -> None:
        self._session.add(
            ReceiptModel(
                id=receipt.id,
                order_id=receipt.order_id,
                payment_id=receipt.payment_id,
                fulfillment_id=receipt.fulfillment_id,
                card_last4=receipt.card_last4,
                amount=receipt.amount,
                currency=receipt.currency,
                operation_type=receipt.operation_type,
                document_kind=receipt.document_kind.value,
                disclaimer_version=receipt.disclaimer_version,
                issued_at=receipt.issued_at,
            )
        )
        await self._session.flush()

    async def get_for_order(self, order_id: UUID) -> Receipt | None:
        stmt = sa.select(ReceiptModel).where(ReceiptModel.order_id == order_id)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_receipt(model) if model is not None else None


class SqlAlchemyFulfillmentRecoveryPort:
    """Consultas cross-aggregate de recuperação (§12.1, §20.1).

    **Somente leitura.** Nenhuma delas aplica efeito financeiro: detecção
    nunca é reparo. Vive fora dos repositories de agregado porque cruza
    `orders`, `fulfillments` e `card_ledger_entries`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_paid_orders_without_completed_fulfillment(self, *, limit: int) -> list[UUID]:
        completed = sa.select(FulfillmentModel.order_id).where(
            FulfillmentModel.status == FulfillmentStatus.COMPLETED.value
        )
        stmt = (
            sa.select(OrderModel.id)
            .where(
                OrderModel.status.in_(("PAID", "FULFILLING", "FULFILLMENT_FAILED")),
                OrderModel.id.notin_(completed),
            )
            .order_by(OrderModel.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def find_completed_fulfillments_without_ledger(self, *, limit: int) -> list[UUID]:
        with_ledger = sa.select(CardLedgerEntryModel.order_id).where(
            CardLedgerEntryModel.entry_type == LedgerEntryType.RECHARGE_CREDIT.value
        )
        stmt = (
            sa.select(FulfillmentModel.order_id)
            .where(
                FulfillmentModel.status == FulfillmentStatus.COMPLETED.value,
                FulfillmentModel.fulfillment_type == FulfillmentType.RECHARGE.value,
                FulfillmentModel.order_id.notin_(with_ledger),
            )
            .order_by(FulfillmentModel.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def find_ledger_without_completed_fulfillment(self, *, limit: int) -> list[UUID]:
        completed = sa.select(FulfillmentModel.order_id).where(
            FulfillmentModel.status == FulfillmentStatus.COMPLETED.value
        )
        stmt = (
            sa.select(CardLedgerEntryModel.order_id)
            .where(
                CardLedgerEntryModel.entry_type == LedgerEntryType.RECHARGE_CREDIT.value,
                CardLedgerEntryModel.order_id.notin_(completed),
            )
            .order_by(CardLedgerEntryModel.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars())
