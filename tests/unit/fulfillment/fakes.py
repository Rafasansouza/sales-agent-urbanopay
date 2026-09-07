"""Dublês em memória para os serviços de SPEC-005.

Transacional de verdade, como o da SPEC-003: cada `async with` trabalha sobre
uma cópia do estado, `commit()` publica e a saída sem commit descarta. Sem
isso não seria possível provar a afirmação central do fulfillment — que uma
falha desfaz ledger, saldo, fulfillment, Order e comprovante **juntos**, sem
deixar estado financeiro parcial.

Os fakes também aplicam as unicidades que o banco garante em produção: um
fulfillment por Order, um `RECHARGE_CREDIT` por Order e um comprovante por
Order. Se o serviço violar uma invariante, o teste falha aqui em vez de passar
em memória e quebrar só no PostgreSQL.

O que estes fakes **não** modelam é lock de linha: `get_for_update` equivale a
`get`. Concorrência real é assunto de teste de integração.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Self

from urbanopay.modules.fulfillment.domain.enums import LedgerEntryType

if TYPE_CHECKING:
    from datetime import datetime

    from urbanopay.modules.cards.domain.entities import Card
    from urbanopay.modules.cards.domain.ports import CardBalanceRepository
    from urbanopay.modules.fulfillment.domain.entities import (
        CardLedgerEntry,
        Fulfillment,
        Receipt,
    )
    from urbanopay.modules.fulfillment.domain.ports import (
        CardLedgerRepository,
        FulfillmentRepository,
        ReceiptRepository,
    )
    from urbanopay.modules.orders.domain.entities import Order
    from urbanopay.modules.orders.domain.ports import OrderRepository
    from urbanopay.modules.payments.domain.entities import Payment
    from urbanopay.modules.payments.domain.ports import PaymentRepository


@dataclass
class State:
    """Conteúdo persistido, em memória."""

    orders: dict[uuid.UUID, Order] = field(default_factory=dict)
    payments: dict[uuid.UUID, Payment] = field(default_factory=dict)
    cards: dict[uuid.UUID, Card] = field(default_factory=dict)
    fulfillments: dict[uuid.UUID, Fulfillment] = field(default_factory=dict)
    ledger: dict[uuid.UUID, CardLedgerEntry] = field(default_factory=dict)
    receipts: dict[uuid.UUID, Receipt] = field(default_factory=dict)

    def copy(self) -> State:
        """Cópia rasa — as entidades são imutáveis, então basta."""
        return State(
            orders=dict(self.orders),
            payments=dict(self.payments),
            cards=dict(self.cards),
            fulfillments=dict(self.fulfillments),
            ledger=dict(self.ledger),
            receipts=dict(self.receipts),
        )


class Store:
    """Guarda o estado publicado."""

    def __init__(self) -> None:
        self.state = State()


class FakeOrderRepository:
    def __init__(self, state: State) -> None:
        self._state = state

    async def add(self, order: Order) -> None:
        self._state.orders[order.id] = order

    async def get(self, order_id: uuid.UUID) -> Order | None:
        return self._state.orders.get(order_id)

    async def get_owned(self, *, customer_id: uuid.UUID, order_id: uuid.UUID) -> Order | None:
        order = self._state.orders.get(order_id)
        if order is None or order.customer_id != customer_id:
            return None
        return order

    async def get_for_update(self, order_id: uuid.UUID) -> Order | None:
        return await self.get(order_id)

    async def get_owned_for_update(
        self, *, customer_id: uuid.UUID, order_id: uuid.UUID
    ) -> Order | None:
        return await self.get_owned(customer_id=customer_id, order_id=order_id)

    async def update(self, order: Order) -> None:
        self._state.orders[order.id] = order

    async def has_quote_been_consumed(self, quote_id: uuid.UUID) -> bool:
        return any(o.quote_id == quote_id for o in self._state.orders.values())


class FakePaymentRepository:
    """Somente os métodos que o fulfillment usa; os demais não são exercitados."""

    def __init__(self, state: State) -> None:
        self._state = state

    async def add(self, payment: Payment) -> None:
        self._state.payments[payment.id] = payment

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        return self._state.payments.get(payment_id)

    async def get_for_update(self, payment_id: uuid.UUID) -> Payment | None:
        return await self.get(payment_id)

    async def get_active_for_order(self, order_id: uuid.UUID) -> Payment | None:
        for payment in self._state.payments.values():
            if payment.order_id == order_id and payment.is_active:
                return payment
        return None

    async def get_approved_for_order(self, order_id: uuid.UUID) -> Payment | None:
        from urbanopay.modules.payments.domain.enums import PaymentStatus

        for payment in self._state.payments.values():
            if payment.order_id == order_id and payment.status is PaymentStatus.APPROVED:
                return payment
        return None

    async def find_by_provider_payment_id(
        self, *, provider: object, provider_payment_id: str
    ) -> Payment | None:
        for payment in self._state.payments.values():
            if payment.provider is provider and payment.provider_payment_id == provider_payment_id:
                return payment
        return None

    async def update(self, payment: Payment) -> None:
        self._state.payments[payment.id] = payment


class FakeCardBalanceRepository:
    def __init__(self, state: State) -> None:
        self._state = state

    async def get_for_update(self, card_id: uuid.UUID) -> Card | None:
        return self._state.cards.get(card_id)

    async def apply_credit(self, *, card_id: uuid.UUID, new_balance: Decimal, at: datetime) -> None:
        card = self._state.cards[card_id]
        # Espelha `ck_cards_balance_non_negative`.
        if new_balance < Decimal("0.00"):
            raise AssertionError("ck_cards_balance_non_negative violado pelo serviço")
        self._state.cards[card_id] = replace(card, balance=new_balance, updated_at=at)


class FakeFulfillmentRepository:
    def __init__(self, state: State) -> None:
        self._state = state

    async def add(self, fulfillment: Fulfillment) -> None:
        # Espelha `uq_fulfillments_order_id`.
        if any(f.order_id == fulfillment.order_id for f in self._state.fulfillments.values()):
            raise AssertionError("uq_fulfillments_order_id violado pelo serviço")
        self._state.fulfillments[fulfillment.id] = fulfillment

    async def get_for_order(self, order_id: uuid.UUID) -> Fulfillment | None:
        for fulfillment in self._state.fulfillments.values():
            if fulfillment.order_id == order_id:
                return fulfillment
        return None

    async def get_for_order_for_update(self, order_id: uuid.UUID) -> Fulfillment | None:
        return await self.get_for_order(order_id)

    async def update(self, fulfillment: Fulfillment) -> None:
        self._state.fulfillments[fulfillment.id] = fulfillment


class FakeCardLedgerRepository:
    """Sem `update` e sem `delete`, como o port: o ledger é imutável."""

    def __init__(self, state: State) -> None:
        self._state = state

    async def add(self, entry: CardLedgerEntry) -> None:
        # Espelha `uq_card_ledger_entries_recharge_per_order` — a invariante
        # central da SPEC-005.
        if entry.entry_type is LedgerEntryType.RECHARGE_CREDIT and any(
            e.order_id == entry.order_id and e.entry_type is LedgerEntryType.RECHARGE_CREDIT
            for e in self._state.ledger.values()
        ):
            raise AssertionError("uq_card_ledger_entries_recharge_per_order violado pelo serviço")
        # Espelha `ck_card_ledger_entries_balance_arithmetic`.
        if entry.balance_after != entry.balance_before + entry.amount:
            raise AssertionError("ck_card_ledger_entries_balance_arithmetic violado")
        self._state.ledger[entry.id] = entry

    async def get_recharge_credit_for_order(self, order_id: uuid.UUID) -> CardLedgerEntry | None:
        for entry in self._state.ledger.values():
            if entry.order_id == order_id and entry.entry_type is LedgerEntryType.RECHARGE_CREDIT:
                return entry
        return None


class FakeReceiptRepository:
    def __init__(self, state: State) -> None:
        self._state = state

    async def add(self, receipt: Receipt) -> None:
        # Espelha `uq_receipts_order_id`.
        if any(r.order_id == receipt.order_id for r in self._state.receipts.values()):
            raise AssertionError("uq_receipts_order_id violado pelo serviço")
        self._state.receipts[receipt.id] = receipt

    async def get_for_order(self, order_id: uuid.UUID) -> Receipt | None:
        for receipt in self._state.receipts.values():
            if receipt.order_id == order_id:
                return receipt
        return None


class FakeFulfillmentUnitOfWork:
    """Implementa o port `FulfillmentUnitOfWork`, com staging por contexto."""

    fulfillments: FulfillmentRepository
    ledger: CardLedgerRepository
    receipts: ReceiptRepository
    orders: OrderRepository
    payments: PaymentRepository
    cards: CardBalanceRepository

    def __init__(self, store: Store) -> None:
        self._store = store
        self._staged: State | None = None
        self.commits = 0

    @property
    def staged(self) -> State:
        if self._staged is None:
            raise RuntimeError("Unit of Work fora de contexto.")
        return self._staged

    async def __aenter__(self) -> Self:
        if self._staged is not None:
            raise RuntimeError("Unit of Work já está em uso: instâncias não são reentrantes.")
        self._staged = self._store.state.copy()
        self._build()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        # Saída sem commit descarta tudo — inclusive por exceção. É o que
        # prova que nenhum efeito financeiro parcial sobrevive.
        self._staged = None

    async def commit(self) -> None:
        self._store.state = self.staged.copy()
        self.commits += 1

    async def rollback(self) -> None:
        self._staged = self._store.state.copy()
        self._build()

    def _build(self) -> None:
        self.fulfillments = FakeFulfillmentRepository(self.staged)
        self.ledger = FakeCardLedgerRepository(self.staged)
        self.receipts = FakeReceiptRepository(self.staged)
        self.orders = FakeOrderRepository(self.staged)
        self.payments = FakePaymentRepository(self.staged)
        self.cards = FakeCardBalanceRepository(self.staged)


class FakeFulfillmentRecoveryPort:
    """Implementa o port de recuperação sobre o estado publicado."""

    def __init__(self, store: Store) -> None:
        self._store = store

    async def find_paid_orders_without_completed_fulfillment(
        self, *, limit: int
    ) -> list[uuid.UUID]:
        from urbanopay.modules.orders.domain.enums import OrderStatus

        elegiveis = {
            OrderStatus.PAID,
            OrderStatus.FULFILLING,
            OrderStatus.FULFILLMENT_FAILED,
        }
        completed = {f.order_id for f in self._store.state.fulfillments.values() if f.is_completed}
        return [
            o.id
            for o in self._store.state.orders.values()
            if o.status in elegiveis and o.id not in completed
        ][:limit]

    async def find_completed_fulfillments_without_ledger(self, *, limit: int) -> list[uuid.UUID]:
        with_ledger = {e.order_id for e in self._store.state.ledger.values()}
        return [
            f.order_id
            for f in self._store.state.fulfillments.values()
            if f.is_completed and f.order_id not in with_ledger
        ][:limit]

    async def find_ledger_without_completed_fulfillment(self, *, limit: int) -> list[uuid.UUID]:
        completed = {f.order_id for f in self._store.state.fulfillments.values() if f.is_completed}
        return [
            e.order_id for e in self._store.state.ledger.values() if e.order_id not in completed
        ][:limit]
