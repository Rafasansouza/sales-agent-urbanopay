"""Unit of Work do módulo payments, sobre a foundation (ADR-012).

Compõe `orders` porque o desfecho de um Payment transiciona o Order na mesma
transação (§13.2). Não compõe `approvals`: nenhuma operação de pagamento
decide aprovação.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from urbanopay.db.idempotency import SqlAlchemyIdempotencyRepository
from urbanopay.db.unit_of_work import SqlAlchemyUnitOfWork
from urbanopay.modules.orders.infrastructure.repositories import SqlAlchemyOrderRepository
from urbanopay.modules.payments.infrastructure.repositories import (
    SqlAlchemyPaymentEventRepository,
    SqlAlchemyPaymentRepository,
)

if TYPE_CHECKING:
    from urbanopay.core.idempotency import IdempotencyRepository
    from urbanopay.modules.orders.domain.ports import OrderRepository
    from urbanopay.modules.payments.domain.ports import (
        PaymentEventRepository,
        PaymentRepository,
    )


class SqlAlchemyPaymentsUnitOfWork(SqlAlchemyUnitOfWork):
    """UoW de payments: repositories disponíveis dentro do contexto."""

    payments: PaymentRepository
    payment_events: PaymentEventRepository
    orders: OrderRepository
    idempotency: IdempotencyRepository

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.payments = SqlAlchemyPaymentRepository(self.session)
        self.payment_events = SqlAlchemyPaymentEventRepository(self.session)
        self.orders = SqlAlchemyOrderRepository(self.session)
        self.idempotency = SqlAlchemyIdempotencyRepository(self.session)
        return self
