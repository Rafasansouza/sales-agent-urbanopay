"""Construtores de entidades para os testes de SPEC-003.

Valores fictícios e instante fixo: nenhum teste depende de relógio real, e
todo cenário é reprodutível.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from urbanopay.modules.approvals.domain.entities import Approval
from urbanopay.modules.approvals.domain.enums import ApprovalStatus
from urbanopay.modules.orders.domain.entities import LineItem, Order, Quote
from urbanopay.modules.orders.domain.enums import (
    CURRENCY_BRL,
    CancellationReason,
    OperationType,
    OrderStatus,
)
from urbanopay.modules.payments.domain.entities import Payment
from urbanopay.modules.payments.domain.enums import (
    PaymentMethod,
    PaymentStatus,
    ProviderName,
)

FIXED_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
TTL = timedelta(minutes=10)
DEFAULT_TOTAL = Decimal("50.00")
ZERO = Decimal("0.00")


def make_quote(
    *,
    quote_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    card_id: uuid.UUID | None = None,
    total: Decimal = DEFAULT_TOTAL,
    operation_type: OperationType = OperationType.RECHARGE,
    created_at: datetime = FIXED_NOW,
    expires_at: datetime | None = None,
) -> Quote:
    return Quote(
        id=quote_id or uuid.uuid4(),
        customer_id=customer_id or uuid.uuid4(),
        card_id=card_id or uuid.uuid4(),
        operation_type=operation_type,
        fare_profile="INTEGRAL",
        items=(LineItem.for_recharge(total),),
        subtotal=total,
        discount_amount=ZERO,
        total=total,
        currency=CURRENCY_BRL,
        expires_at=expires_at or (created_at + TTL),
        created_at=created_at,
    )


def make_order(
    *,
    order_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    quote_id: uuid.UUID | None = None,
    status: OrderStatus = OrderStatus.DRAFT,
    requires_approval: bool = False,
    total: Decimal = DEFAULT_TOTAL,
    cancellation_reason: CancellationReason | None = None,
    created_at: datetime = FIXED_NOW,
    expires_at: datetime | None = None,
) -> Order:
    return Order(
        id=order_id or uuid.uuid4(),
        customer_id=customer_id or uuid.uuid4(),
        card_id=uuid.uuid4(),
        quote_id=quote_id or uuid.uuid4(),
        operation_type=OperationType.RECHARGE,
        status=status,
        items=(LineItem.for_recharge(total),),
        subtotal=total,
        discount_amount=ZERO,
        total=total,
        currency=CURRENCY_BRL,
        requires_approval=requires_approval,
        expires_at=expires_at or (created_at + TTL),
        cancellation_reason=cancellation_reason,
        created_at=created_at,
        updated_at=created_at,
    )


def make_approval(
    *,
    order_id: uuid.UUID,
    status: ApprovalStatus = ApprovalStatus.PENDING,
    requested_at: datetime = FIXED_NOW,
) -> Approval:
    decided = status is not ApprovalStatus.PENDING
    return Approval(
        id=uuid.uuid4(),
        order_id=order_id,
        status=status,
        requested_at=requested_at,
        decided_at=requested_at if decided else None,
        decided_by="operator-1" if decided else None,
    )


def make_payment(
    *,
    order_id: uuid.UUID,
    status: PaymentStatus = PaymentStatus.CREATED,
    amount: Decimal = DEFAULT_TOTAL,
    provider_payment_id: str | None = None,
    idempotency_key: str = "key-1",
    created_at: datetime = FIXED_NOW,
) -> Payment:
    return Payment(
        id=uuid.uuid4(),
        order_id=order_id,
        provider=ProviderName.FAKE,
        provider_payment_id=provider_payment_id,
        method=PaymentMethod.PIX,
        amount=amount,
        currency=CURRENCY_BRL,
        status=status,
        idempotency_key=idempotency_key,
        created_at=created_at,
        updated_at=created_at,
    )
