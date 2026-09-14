"""Unit of Work do módulo orders, sobre a foundation (ADR-012).

Compõe exatamente os repositories que as operações de Order precisam na mesma
transação — nada além: `payments` não entra aqui, porque nenhuma operação de
Order escreve Payment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from urbanopay.db.idempotency import SqlAlchemyIdempotencyRepository
from urbanopay.db.unit_of_work import SqlAlchemyUnitOfWork
from urbanopay.modules.approvals.infrastructure.repositories import (
    SqlAlchemyApprovalRepository,
)
from urbanopay.modules.orders.infrastructure.repositories import (
    SqlAlchemyOrderRepository,
    SqlAlchemyQuoteRepository,
)

if TYPE_CHECKING:
    from urbanopay.core.idempotency import IdempotencyRepository
    from urbanopay.modules.approvals.domain.ports import ApprovalRepository
    from urbanopay.modules.orders.domain.ports import OrderRepository, QuoteRepository


class SqlAlchemyOrdersUnitOfWork(SqlAlchemyUnitOfWork):
    """UoW de orders: repositories disponíveis dentro do contexto.

    Semântica herdada da foundation: commit explícito; saída sem commit ou por
    exceção desfaz o trabalho pendente; sessão sempre liberada.
    """

    quotes: QuoteRepository
    orders: OrderRepository
    approvals: ApprovalRepository
    idempotency: IdempotencyRepository

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.quotes = SqlAlchemyQuoteRepository(self.session)
        self.orders = SqlAlchemyOrderRepository(self.session)
        self.approvals = SqlAlchemyApprovalRepository(self.session)
        self.idempotency = SqlAlchemyIdempotencyRepository(self.session)
        return self
