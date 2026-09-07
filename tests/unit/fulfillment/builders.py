"""Construtores para os testes de SPEC-005.

Valores fictícios e instante fixo: nenhum teste depende de relógio real.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from urbanopay.modules.cards.domain.entities import Card
from urbanopay.modules.cards.domain.enums import CardStatus, FareProfile
from urbanopay.modules.fulfillment.domain.entities import (
    CardLedgerEntry,
    Fulfillment,
    Receipt,
)
from urbanopay.modules.fulfillment.domain.enums import (
    CURRENCY_BRL,
    DISCLAIMER_VERSION,
    DocumentKind,
    FailureClass,
    FulfillmentStatus,
    FulfillmentType,
    LedgerEntryType,
)
from urbanopay.modules.orders.domain.entities import LineItem, Order
from urbanopay.modules.orders.domain.enums import OperationType, OrderStatus
from urbanopay.modules.payments.domain.entities import Payment
from urbanopay.modules.payments.domain.enums import (
    PaymentMethod,
    PaymentStatus,
    ProviderName,
)

FIXED_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
LATER = FIXED_NOW + timedelta(minutes=1)
DEFAULT_TOTAL = Decimal("50.00")
ZERO = Decimal("0.00")


def make_card(
    *,
    card_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    balance: Decimal = ZERO,
    status: CardStatus = CardStatus.ACTIVE,
    card_last4: str = "4821",
) -> Card:
    return Card(
        id=card_id or uuid.uuid4(),
        customer_id=customer_id or uuid.uuid4(),
        card_last4=card_last4,
        fare_profile=FareProfile.INTEGRAL,
        balance=balance,
        status=status,
        expires_at=None,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


def make_order(
    *,
    order_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    card_id: uuid.UUID | None = None,
    status: OrderStatus = OrderStatus.PAID,
    total: Decimal = DEFAULT_TOTAL,
) -> Order:
    return Order(
        id=order_id or uuid.uuid4(),
        customer_id=customer_id or uuid.uuid4(),
        card_id=card_id or uuid.uuid4(),
        quote_id=uuid.uuid4(),
        operation_type=OperationType.RECHARGE,
        status=status,
        items=(LineItem.for_recharge(total),),
        subtotal=total,
        discount_amount=ZERO,
        total=total,
        currency=CURRENCY_BRL,
        requires_approval=False,
        expires_at=FIXED_NOW + timedelta(minutes=10),
        cancellation_reason=None,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


def make_payment(
    *,
    order_id: uuid.UUID,
    status: PaymentStatus = PaymentStatus.APPROVED,
    amount: Decimal = DEFAULT_TOTAL,
) -> Payment:
    return Payment(
        id=uuid.uuid4(),
        order_id=order_id,
        provider=ProviderName.FAKE,
        provider_payment_id="fake-charge-1",
        method=PaymentMethod.PIX,
        amount=amount,
        currency=CURRENCY_BRL,
        status=status,
        idempotency_key=f"pay-{order_id}",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


def make_fulfillment(
    *,
    order_id: uuid.UUID,
    card_id: uuid.UUID,
    payment_id: uuid.UUID | None = None,
    status: FulfillmentStatus = FulfillmentStatus.PENDING,
    fulfillment_type: FulfillmentType = FulfillmentType.RECHARGE,
) -> Fulfillment:
    terminal_failure = status in (
        FulfillmentStatus.FAILED,
        FulfillmentStatus.RECONCILIATION_REQUIRED,
    )
    return Fulfillment(
        id=uuid.uuid4(),
        order_id=order_id,
        payment_id=payment_id,
        card_id=card_id,
        fulfillment_type=fulfillment_type,
        status=status,
        failure_reason="MOTIVO_FICTICIO" if terminal_failure else None,
        failure_class=FailureClass.UNKNOWN_OUTCOME if terminal_failure else None,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        completed_at=FIXED_NOW if status is FulfillmentStatus.COMPLETED else None,
    )


def make_ledger_entry(
    *,
    order_id: uuid.UUID,
    card_id: uuid.UUID,
    fulfillment_id: uuid.UUID,
    amount: Decimal = DEFAULT_TOTAL,
    balance_before: Decimal = ZERO,
) -> CardLedgerEntry:
    return CardLedgerEntry(
        id=uuid.uuid4(),
        fulfillment_id=fulfillment_id,
        order_id=order_id,
        card_id=card_id,
        entry_type=LedgerEntryType.RECHARGE_CREDIT,
        amount=amount,
        currency=CURRENCY_BRL,
        balance_before=balance_before,
        balance_after=balance_before + amount,
        created_at=FIXED_NOW,
    )


def make_receipt(
    *,
    order_id: uuid.UUID,
    payment_id: uuid.UUID,
    fulfillment_id: uuid.UUID,
    amount: Decimal = DEFAULT_TOTAL,
) -> Receipt:
    return Receipt(
        id=uuid.uuid4(),
        order_id=order_id,
        payment_id=payment_id,
        fulfillment_id=fulfillment_id,
        card_last4="4821",
        amount=amount,
        currency=CURRENCY_BRL,
        operation_type=OperationType.RECHARGE.value,
        document_kind=DocumentKind.SIMULATED_NON_FISCAL,
        disclaimer_version=DISCLAIMER_VERSION,
        issued_at=FIXED_NOW,
    )
