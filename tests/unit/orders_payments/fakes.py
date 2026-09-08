"""Dublês em memória para os serviços de SPEC-003.

Diferente de um dicionário simples, este fake é **transacional**: cada
`async with` trabalha sobre uma cópia do estado, `commit()` publica e a saída
sem commit descarta. Sem isso não seria possível provar a afirmação central da
idempotência de fase única (§11.2) — que uma falha desfaz reivindicação e
efeito **juntos**, não deixando `IN_PROGRESS` órfão.

Os fakes também aplicam as unicidades que o banco garante em produção
(uma tentativa ativa por Order, um aprovado por Order, um Order por Quote,
uma key por operação). Assim, se o serviço violar uma invariante, o teste
falha aqui em vez de passar em memória e quebrar só no PostgreSQL.

O que estes fakes **não** modelam é lock de linha: `get_for_update` equivale a
`get`. Concorrência real é assunto de teste de integração, com dois
`AsyncSession` e `SELECT ... FOR UPDATE` de verdade.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Self

from urbanopay.core.idempotency import (
    IdempotencyClaim,
    IdempotencyRecord,
    IdempotencyStatus,
)
from urbanopay.modules.payments.domain.entities import (
    ACTIVE_PAYMENT_STATUSES,
    Payment,
)
from urbanopay.modules.payments.domain.enums import PaymentStatus

if TYPE_CHECKING:
    from datetime import datetime

    from urbanopay.core.idempotency import IdempotencyRepository
    from urbanopay.modules.approvals.domain.entities import Approval
    from urbanopay.modules.approvals.domain.ports import ApprovalRepository
    from urbanopay.modules.orders.domain.entities import Order, Quote
    from urbanopay.modules.orders.domain.ports import OrderRepository, QuoteRepository
    from urbanopay.modules.payments.domain.entities import PaymentEvent
    from urbanopay.modules.payments.domain.enums import ProviderName
    from urbanopay.modules.payments.domain.ports import (
        PaymentEventRepository,
        PaymentRepository,
    )


@dataclass
class State:
    """Conteúdo persistido, em memória."""

    quotes: dict[uuid.UUID, Quote] = field(default_factory=dict)
    orders: dict[uuid.UUID, Order] = field(default_factory=dict)
    approvals: dict[uuid.UUID, Approval] = field(default_factory=dict)
    payments: dict[uuid.UUID, Payment] = field(default_factory=dict)
    events: set[tuple[str, str]] = field(default_factory=set)
    idempotency: dict[tuple[str, str], IdempotencyRecord] = field(default_factory=dict)

    def copy(self) -> State:
        """Cópia rasa — as entidades são imutáveis, então basta."""
        return State(
            quotes=dict(self.quotes),
            orders=dict(self.orders),
            approvals=dict(self.approvals),
            payments=dict(self.payments),
            events=set(self.events),
            idempotency=dict(self.idempotency),
        )


class Store:
    """Guarda o estado publicado. Compartilhado entre UoWs de módulos."""

    def __init__(self) -> None:
        self.state = State()


class FakeQuoteRepository:
    def __init__(self, state: State) -> None:
        self._state = state

    async def add(self, quote: Quote) -> None:
        self._state.quotes[quote.id] = quote

    async def get_owned(self, *, customer_id: uuid.UUID, quote_id: uuid.UUID) -> Quote | None:
        quote = self._state.quotes.get(quote_id)
        if quote is None or quote.customer_id != customer_id:
            return None
        return quote


class FakeOrderRepository:
    def __init__(self, state: State) -> None:
        self._state = state

    async def add(self, order: Order) -> None:
        # Espelha `uq_orders_quote_id`: uma Quote gera um único Order.
        if any(o.quote_id == order.quote_id for o in self._state.orders.values()):
            raise AssertionError("uq_orders_quote_id violado pelo serviço")
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


class FakeApprovalRepository:
    def __init__(self, state: State) -> None:
        self._state = state

    async def add(self, approval: Approval) -> None:
        # Espelha `uq_approvals_order_id`.
        if any(a.order_id == approval.order_id for a in self._state.approvals.values()):
            raise AssertionError("uq_approvals_order_id violado pelo serviço")
        self._state.approvals[approval.id] = approval

    async def get_for_order(self, order_id: uuid.UUID) -> Approval | None:
        for approval in self._state.approvals.values():
            if approval.order_id == order_id:
                return approval
        return None

    async def get_for_order_for_update(self, order_id: uuid.UUID) -> Approval | None:
        return await self.get_for_order(order_id)

    async def update(self, approval: Approval) -> None:
        self._state.approvals[approval.id] = approval


class FakePaymentRepository:
    def __init__(self, state: State) -> None:
        self._state = state

    async def add(self, payment: Payment) -> None:
        # Espelha os índices únicos parciais de `pay0001`.
        for existing in self._state.payments.values():
            if existing.order_id != payment.order_id:
                continue
            if existing.is_active and payment.is_active:
                raise AssertionError("uq_payments_active_per_order violado pelo serviço")
            if (
                existing.status is PaymentStatus.APPROVED
                and payment.status is PaymentStatus.APPROVED
            ):
                raise AssertionError("uq_payments_approved_per_order violado pelo serviço")
        if any(p.idempotency_key == payment.idempotency_key for p in self._state.payments.values()):
            raise AssertionError("uq_payments_idempotency_key violado pelo serviço")
        self._state.payments[payment.id] = payment

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        return self._state.payments.get(payment_id)

    async def get_for_update(self, payment_id: uuid.UUID) -> Payment | None:
        return await self.get(payment_id)

    async def get_active_for_order(self, order_id: uuid.UUID) -> Payment | None:
        for payment in self._state.payments.values():
            if payment.order_id == order_id and payment.status in ACTIVE_PAYMENT_STATUSES:
                return payment
        return None

    async def get_approved_for_order(self, order_id: uuid.UUID) -> Payment | None:
        for payment in self._state.payments.values():
            if payment.order_id == order_id and payment.status is PaymentStatus.APPROVED:
                return payment
        return None

    async def get_latest_for_order(self, order_id: uuid.UUID) -> Payment | None:
        """Tentativa mais recente do Order, com o mesmo desempate do SQL."""
        candidates = [p for p in self._state.payments.values() if p.order_id == order_id]
        if not candidates:
            return None
        return max(candidates, key=lambda p: (p.created_at, p.id))

    async def find_by_provider_payment_id(
        self, *, provider: ProviderName, provider_payment_id: str
    ) -> Payment | None:
        for payment in self._state.payments.values():
            if payment.provider is provider and payment.provider_payment_id == provider_payment_id:
                return payment
        return None

    async def update(self, payment: Payment) -> None:
        self._state.payments[payment.id] = payment


class FakePaymentEventRepository:
    def __init__(self, state: State) -> None:
        self._state = state

    async def record(self, event: PaymentEvent) -> bool:
        """Espelha `UNIQUE (provider, provider_event_id)`."""
        identity = (event.provider.value, event.provider_event_id)
        if identity in self._state.events:
            return False
        self._state.events.add(identity)
        return True


class FakeIdempotencyRepository:
    def __init__(self, state: State) -> None:
        self._state = state

    async def claim(
        self, *, operation: str, key: str, fingerprint: str, at: datetime
    ) -> IdempotencyClaim:
        identity = (operation, key)
        existing = self._state.idempotency.get(identity)
        if existing is not None:
            return IdempotencyClaim(acquired=False, existing=existing)
        self._state.idempotency[identity] = IdempotencyRecord(
            key=key,
            operation=operation,
            request_fingerprint=fingerprint,
            status=IdempotencyStatus.IN_PROGRESS,
            resource_id=None,
            response_reference=None,
            created_at=at,
            updated_at=at,
            completed_at=None,
        )
        return IdempotencyClaim(acquired=True, existing=None)

    async def get(self, *, operation: str, key: str) -> IdempotencyRecord | None:
        return self._state.idempotency.get((operation, key))

    async def complete(
        self,
        *,
        operation: str,
        key: str,
        resource_id: uuid.UUID | None,
        response_reference: str | None,
        at: datetime,
    ) -> None:
        self._set(
            operation=operation,
            key=key,
            status=IdempotencyStatus.COMPLETED,
            resource_id=resource_id,
            response_reference=response_reference,
            at=at,
        )

    async def fail(
        self, *, operation: str, key: str, response_reference: str | None, at: datetime
    ) -> None:
        self._set(
            operation=operation,
            key=key,
            status=IdempotencyStatus.FAILED,
            resource_id=None,
            response_reference=response_reference,
            at=at,
        )

    def _set(
        self,
        *,
        operation: str,
        key: str,
        status: IdempotencyStatus,
        resource_id: uuid.UUID | None,
        response_reference: str | None,
        at: datetime,
    ) -> None:
        identity = (operation, key)
        current = self._state.idempotency[identity]
        self._state.idempotency[identity] = replace(
            current,
            status=status,
            resource_id=resource_id if resource_id is not None else current.resource_id,
            response_reference=response_reference,
            updated_at=at,
            completed_at=at,
        )


class _TransactionalUnitOfWork:
    """Base dos UoWs falsos: staging por contexto, publicação no commit."""

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
        self._build_repositories()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        # Saída sem commit descarta o trabalho pendente — inclusive por
        # exceção. É o que prova que a reivindicação de key não sobrevive a
        # uma falha da operação local.
        self._staged = None

    async def commit(self) -> None:
        self._store.state = self.staged.copy()
        self.commits += 1

    async def rollback(self) -> None:
        self._staged = self._store.state.copy()
        self._build_repositories()

    def _build_repositories(self) -> None:  # pragma: no cover - sobrescrito
        raise NotImplementedError


class FakeOrdersUnitOfWork(_TransactionalUnitOfWork):
    """Implementa o port `OrdersUnitOfWork`."""

    quotes: QuoteRepository
    orders: OrderRepository
    approvals: ApprovalRepository
    idempotency: IdempotencyRepository

    def _build_repositories(self) -> None:
        self.quotes = FakeQuoteRepository(self.staged)
        self.orders = FakeOrderRepository(self.staged)
        self.approvals = FakeApprovalRepository(self.staged)
        self.idempotency = FakeIdempotencyRepository(self.staged)


class FakePaymentsUnitOfWork(_TransactionalUnitOfWork):
    """Implementa o port `PaymentsUnitOfWork`."""

    payments: PaymentRepository
    payment_events: PaymentEventRepository
    orders: OrderRepository
    idempotency: IdempotencyRepository

    def _build_repositories(self) -> None:
        self.payments = FakePaymentRepository(self.staged)
        self.payment_events = FakePaymentEventRepository(self.staged)
        self.orders = FakeOrderRepository(self.staged)
        self.idempotency = FakeIdempotencyRepository(self.staged)
