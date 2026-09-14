"""Units of Work do módulo fulfillment, sobre a foundation (ADR-012).

Dois, com razões distintas de existir:

- `SqlAlchemyFulfillmentUnitOfWork` — a fronteira **transacional** do efeito:
  ledger, saldo, fulfillment, Order e comprovante comitam juntos;
- `SqlAlchemyFulfillmentRecoveryUnitOfWork` — **somente leitura**, para as
  consultas cross-aggregate de consistência. Não participa da transação do
  efeito e não deve carregar seus repositories.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from urbanopay_database.unit_of_work import SqlAlchemyUnitOfWork
from urbanopay_domains.cards.infrastructure.repositories import (
    SqlAlchemyCardBalanceRepository,
)
from urbanopay_domains.fulfillment.infrastructure.repositories import (
    SqlAlchemyCardLedgerRepository,
    SqlAlchemyFulfillmentRecoveryPort,
    SqlAlchemyFulfillmentRepository,
    SqlAlchemyReceiptRepository,
)
from urbanopay_domains.orders.infrastructure.repositories import SqlAlchemyOrderRepository
from urbanopay_domains.payments.infrastructure.repositories import (
    SqlAlchemyPaymentRepository,
)

if TYPE_CHECKING:
    from urbanopay_domains.cards.domain.ports import CardBalanceRepository
    from urbanopay_domains.fulfillment.domain.ports import (
        CardLedgerRepository,
        FulfillmentRecoveryPort,
        FulfillmentRepository,
        ReceiptRepository,
    )
    from urbanopay_domains.orders.domain.ports import OrderRepository
    from urbanopay_domains.payments.domain.ports import PaymentRepository


class SqlAlchemyFulfillmentUnitOfWork(SqlAlchemyUnitOfWork):
    """UoW do fulfillment: seis repositories, uma transação.

    A atomicidade é o que os reúne — separá-los por estética criaria estado
    financeiro parcial. `payments` entra somente-leitura: `APPROVED` é
    terminal e imutável.
    """

    fulfillments: FulfillmentRepository
    ledger: CardLedgerRepository
    receipts: ReceiptRepository
    orders: OrderRepository
    payments: PaymentRepository
    cards: CardBalanceRepository

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.fulfillments = SqlAlchemyFulfillmentRepository(self.session)
        self.ledger = SqlAlchemyCardLedgerRepository(self.session)
        self.receipts = SqlAlchemyReceiptRepository(self.session)
        self.orders = SqlAlchemyOrderRepository(self.session)
        self.payments = SqlAlchemyPaymentRepository(self.session)
        self.cards = SqlAlchemyCardBalanceRepository(self.session)
        return self


class SqlAlchemyFulfillmentRecoveryUnitOfWork(SqlAlchemyUnitOfWork):
    """UoW somente-leitura das consultas de consistência (§12.1)."""

    recovery: FulfillmentRecoveryPort

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.recovery = SqlAlchemyFulfillmentRecoveryPort(self.session)
        return self
