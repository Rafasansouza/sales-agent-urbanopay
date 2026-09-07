"""Jornada transacional contra PostgreSQL real (SPEC-003 §5, §7, §8, §9, §14).

Prova a máquina de estados atravessando persistência de verdade: ida e volta de
`Decimal`, itens congelados, `Approval` criada na mesma transação e `Order PAID`
somente a partir de `Payment APPROVED`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.orders_payments.conftest import (
    FIXED_NOW,
    TTL,
    OrdersPaymentsTestData,
)
from urbanopay.modules.approvals.domain.enums import ApprovalStatus
from urbanopay.modules.approvals.infrastructure.repositories import (
    SqlAlchemyApprovalRepository,
)
from urbanopay.modules.orders.application.services import OrderService, QuoteService
from urbanopay.modules.orders.domain.enums import CancellationReason, OrderStatus
from urbanopay.modules.payments.application.services import PaymentService
from urbanopay.modules.payments.domain.enums import PaymentStatus, ProviderName
from urbanopay.providers.payments.fake import FakePaymentProvider


async def _quote_and_order(
    data: OrdersPaymentsTestData,
    quote_service: QuoteService,
    order_service: OrderService,
    *,
    total: Decimal,
) -> tuple[uuid.UUID, uuid.UUID]:
    customer_id, card_id = await data.add_customer_with_card()
    quote = await quote_service.create_recharge_quote(
        customer_id=customer_id,
        card_id=card_id,
        fare_profile="INTEGRAL",
        amount=total,
        at=FIXED_NOW,
    )
    order = await order_service.create_order(
        customer_id=customer_id,
        quote_id=quote.id,
        idempotency_key=f"create-{quote.id}",
        at=FIXED_NOW,
    )
    return customer_id, order.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jornada_de_recarga_sem_aprovacao(
    data: OrdersPaymentsTestData,
    quote_service: QuoteService,
    order_service: OrderService,
    payment_service: PaymentService,
    provider: FakePaymentProvider,
) -> None:
    """Recarga de R$ 50,00: confirmação, Pix e pagamento aprovado."""
    customer_id, order_id = await _quote_and_order(
        data, quote_service, order_service, total=Decimal("50.00")
    )

    confirmed = await order_service.confirm_order(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=f"confirm-{order_id}",
        at=FIXED_NOW,
    )
    assert confirmed.status is OrderStatus.CONFIRMED
    assert confirmed.requires_approval is False

    resultado = await payment_service.create_payment(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=f"pay-{order_id}",
        at=FIXED_NOW,
    )
    assert resultado.payment.status is PaymentStatus.PENDING
    assert resultado.payment.amount == Decimal("50.00")
    assert resultado.qr_code is not None

    reloaded = await order_service.get_order(customer_id=customer_id, order_id=order_id)
    assert reloaded.status is OrderStatus.PAYMENT_PENDING

    charge_id = resultado.payment.provider_payment_id
    assert charge_id is not None
    webhook = await payment_service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id=f"evt-{charge_id}",
        provider_payment_id=charge_id,
        reported_status=PaymentStatus.APPROVED,
        payload={"id": charge_id, "status": "approved"},
        at=FIXED_NOW,
    )
    assert webhook.applied is True

    pago = await order_service.get_order(customer_id=customer_id, order_id=order_id)
    assert pago.status is OrderStatus.PAID
    assert provider.create_calls == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_jornada_com_aprovacao_humana(
    data: OrdersPaymentsTestData,
    quote_service: QuoteService,
    order_service: OrderService,
    payment_service: PaymentService,
) -> None:
    """Recarga de R$ 250,00: confirmação leva a `REQUIRES_APPROVAL` (§7, §14)."""
    customer_id, order_id = await _quote_and_order(
        data, quote_service, order_service, total=Decimal("250.00")
    )

    confirmed = await order_service.confirm_order(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=f"confirm-{order_id}",
        at=FIXED_NOW,
    )
    assert confirmed.requires_approval is True
    assert confirmed.status is OrderStatus.REQUIRES_APPROVAL

    liberado = await order_service.approve_order(
        order_id=order_id,
        actor="operator-integration",
        idempotency_key=f"approve-{order_id}",
        at=FIXED_NOW,
    )
    assert liberado.status is OrderStatus.CONFIRMED

    resultado = await payment_service.create_payment(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=f"pay-{order_id}",
        at=FIXED_NOW,
    )
    assert resultado.payment.amount == Decimal("250.00")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approval_nasce_pendente_na_mesma_transacao(
    data: OrdersPaymentsTestData,
    quote_service: QuoteService,
    order_service: OrderService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Nunca existe Order em `REQUIRES_APPROVAL` sem `Approval` persistida.

    A leitura usa uma sessão nova, fora da transação que confirmou: se a
    `Approval` não tivesse sido comitada junto com a transição do Order, ela
    não estaria visível aqui.
    """
    customer_id, order_id = await _quote_and_order(
        data, quote_service, order_service, total=Decimal("300.00")
    )
    await order_service.confirm_order(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=f"confirm-{order_id}",
        at=FIXED_NOW,
    )

    async with session_factory() as session:
        approval = await SqlAlchemyApprovalRepository(session).get_for_order(order_id)

    assert approval is not None
    assert approval.status is ApprovalStatus.PENDING
    assert approval.decided_at is None
    assert approval.decided_by is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rejeicao_cancela_com_motivo_de_rejeicao(
    data: OrdersPaymentsTestData,
    quote_service: QuoteService,
    order_service: OrderService,
) -> None:
    customer_id, order_id = await _quote_and_order(
        data, quote_service, order_service, total=Decimal("250.00")
    )
    await order_service.confirm_order(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=f"confirm-{order_id}",
        at=FIXED_NOW,
    )

    cancelado = await order_service.reject_order(
        order_id=order_id,
        actor="operator-integration",
        idempotency_key=f"reject-{order_id}",
        at=FIXED_NOW,
    )

    assert cancelado.status is OrderStatus.CANCELLED
    assert cancelado.cancellation_reason is CancellationReason.APPROVAL_REJECTED

    reloaded = await order_service.get_order(customer_id=customer_id, order_id=order_id)
    assert reloaded.cancellation_reason is CancellationReason.APPROVAL_REJECTED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_valores_e_itens_atravessam_a_persistencia_sem_perda(
    data: OrdersPaymentsTestData,
    quote_service: QuoteService,
    order_service: OrderService,
) -> None:
    """`Decimal` ida e volta, com escala preservada — nunca float."""
    total = Decimal("137.45")
    customer_id, order_id = await _quote_and_order(data, quote_service, order_service, total=total)

    reloaded = await order_service.get_order(customer_id=customer_id, order_id=order_id)

    assert reloaded.total == total
    assert reloaded.subtotal == total
    assert reloaded.discount_amount == Decimal("0.00")
    assert str(reloaded.total) == "137.45"
    assert isinstance(reloaded.total, Decimal)
    assert len(reloaded.items) == 1
    item = reloaded.items[0]
    assert item.quantity == 1
    assert item.unit_amount == total
    assert item.total_amount == total
    assert reloaded.expires_at == FIXED_NOW + TTL


@pytest.mark.integration
@pytest.mark.asyncio
async def test_nova_tentativa_comercial_apos_recusa(
    data: OrdersPaymentsTestData,
    quote_service: QuoteService,
    order_service: OrderService,
    payment_service: PaymentService,
    provider: FakePaymentProvider,
) -> None:
    """Terminal não aprovado devolve o Order a `CONFIRMED` (§13.2)."""
    customer_id, order_id = await _quote_and_order(
        data, quote_service, order_service, total=Decimal("60.00")
    )
    await order_service.confirm_order(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=f"confirm-{order_id}",
        at=FIXED_NOW,
    )
    primeiro = await payment_service.create_payment(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=f"pay1-{order_id}",
        at=FIXED_NOW,
    )
    charge_id = primeiro.payment.provider_payment_id
    assert charge_id is not None

    await payment_service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id=f"evt-rej-{charge_id}",
        provider_payment_id=charge_id,
        reported_status=PaymentStatus.REJECTED,
        payload={"id": charge_id, "status": "rejected"},
        at=FIXED_NOW,
    )

    liberado = await order_service.get_order(customer_id=customer_id, order_id=order_id)
    assert liberado.status is OrderStatus.CONFIRMED

    segundo = await payment_service.create_payment(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=f"pay2-{order_id}",
        at=FIXED_NOW,
    )

    assert segundo.payment.id != primeiro.payment.id
    assert segundo.payment.status is PaymentStatus.PENDING
    assert provider.create_calls == 2
