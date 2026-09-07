"""Concorrência real contra PostgreSQL (SPEC-003 §9, §11, §12; ADR-012).

Estes testes usam **duas sessões distintas** em `asyncio.gather`, porque uma
`AsyncSession` nunca é compartilhada entre tasks concorrentes (ADR-012). Só
assim `SELECT ... FOR UPDATE` e os índices únicos parciais são exercitados de
verdade — o dublê em memória dos testes unit não modela lock de linha.

Ordem global de lock: `Order → Approval → Payment → Card → Fulfillment`.
Deste arquivo participam os três primeiros elos.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.orders_payments.conftest import (
    FIXED_NOW,
    TTL,
    OrdersPaymentsTestData,
)
from urbanopay.modules.approvals.infrastructure.models import ApprovalModel
from urbanopay.modules.orders.application.services import OrderService, QuoteService
from urbanopay.modules.orders.domain.enums import OrderStatus
from urbanopay.modules.orders.domain.policies import ApprovalPolicy
from urbanopay.modules.orders.infrastructure.uow import SqlAlchemyOrdersUnitOfWork
from urbanopay.modules.payments.application.services import PaymentService
from urbanopay.modules.payments.domain.enums import PaymentStatus, ProviderName
from urbanopay.modules.payments.infrastructure.models import PaymentModel
from urbanopay.modules.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from urbanopay.providers.payments.fake import FakePaymentProvider


def _orders(session_factory: async_sessionmaker[AsyncSession]) -> OrderService:
    """Serviço com UoW próprio — uma sessão por task concorrente."""
    return OrderService(
        SqlAlchemyOrdersUnitOfWork(session_factory), ApprovalPolicy(), draft_ttl=TTL
    )


def _payments(
    session_factory: async_sessionmaker[AsyncSession], provider: FakePaymentProvider
) -> PaymentService:
    return PaymentService(SqlAlchemyPaymentsUnitOfWork(session_factory), provider)


async def _confirmed_order(
    data: OrdersPaymentsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    total: Decimal = Decimal("50.00"),
) -> tuple[uuid.UUID, uuid.UUID]:
    customer_id, card_id = await data.add_customer_with_card()
    quotes = QuoteService(SqlAlchemyOrdersUnitOfWork(session_factory), quote_ttl=TTL)
    orders = _orders(session_factory)
    quote = await quotes.create_recharge_quote(
        customer_id=customer_id,
        card_id=card_id,
        fare_profile="INTEGRAL",
        amount=total,
        at=FIXED_NOW,
    )
    order = await orders.create_order(
        customer_id=customer_id,
        quote_id=quote.id,
        idempotency_key=f"create-{quote.id}",
        at=FIXED_NOW,
    )
    await orders.confirm_order(
        customer_id=customer_id,
        order_id=order.id,
        idempotency_key=f"confirm-{order.id}",
        at=FIXED_NOW,
    )
    return customer_id, order.id


async def _count_payments(
    session_factory: async_sessionmaker[AsyncSession], order_id: uuid.UUID
) -> int:
    async with session_factory() as session:
        return int(
            (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(PaymentModel)
                    .where(PaymentModel.order_id == order_id)
                )
            ).scalar_one()
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dois_create_payment_concorrentes_produzem_uma_tentativa(
    data: OrdersPaymentsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakePaymentProvider,
) -> None:
    """Cenário crítico: nenhuma cobrança duplicada sob concorrência (§9, §17).

    O lock do Order serializa as duas transações; a segunda encontra tentativa
    ativa e não cria nada. O índice único parcial é a última defesa.
    """
    customer_id, order_id = await _confirmed_order(data, session_factory)
    key = f"pay-{order_id}"

    async def tentar(sufixo: str) -> object:
        service = _payments(session_factory, provider)
        try:
            return await service.create_payment(
                customer_id=customer_id,
                order_id=order_id,
                idempotency_key=f"{key}-{sufixo}",
                at=FIXED_NOW,
            )
        except Exception as exc:
            return exc

    resultados = await asyncio.gather(tentar("a"), tentar("b"))

    assert await _count_payments(session_factory, order_id) == 1
    assert provider.create_calls == 1, "somente um POST pode ter sido emitido"
    # Exatamente uma das duas chamadas resultou em cobrança criada.
    sucessos = [r for r in resultados if not isinstance(r, Exception)]
    assert len(sucessos) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_payment_concorrente_com_a_mesma_key(
    data: OrdersPaymentsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakePaymentProvider,
) -> None:
    """A mesma key em paralelo: a unicidade `(operation, key)` serializa."""
    customer_id, order_id = await _confirmed_order(data, session_factory)
    key = f"same-key-{order_id}"

    async def tentar() -> object:
        service = _payments(session_factory, provider)
        try:
            return await service.create_payment(
                customer_id=customer_id,
                order_id=order_id,
                idempotency_key=key,
                at=FIXED_NOW,
            )
        except Exception as exc:
            return exc

    await asyncio.gather(tentar(), tentar())

    assert await _count_payments(session_factory, order_id) == 1
    assert provider.create_calls == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duas_confirmacoes_concorrentes_criam_uma_aprovacao(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Order acima do limiar: uma única `Approval`, mesmo em paralelo (§7)."""
    customer_id, card_id = await data.add_customer_with_card()
    quotes = QuoteService(SqlAlchemyOrdersUnitOfWork(session_factory), quote_ttl=TTL)
    quote = await quotes.create_recharge_quote(
        customer_id=customer_id,
        card_id=card_id,
        fare_profile="INTEGRAL",
        amount=Decimal("250.00"),
        at=FIXED_NOW,
    )
    order = await _orders(session_factory).create_order(
        customer_id=customer_id,
        quote_id=quote.id,
        idempotency_key=f"create-{quote.id}",
        at=FIXED_NOW,
    )
    key = f"confirm-{order.id}"

    async def confirmar() -> object:
        try:
            return await _orders(session_factory).confirm_order(
                customer_id=customer_id,
                order_id=order.id,
                idempotency_key=key,
                at=FIXED_NOW,
            )
        except Exception as exc:
            return exc

    await asyncio.gather(confirmar(), confirmar())

    async with session_factory() as session:
        total = int(
            (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(ApprovalModel)
                    .where(ApprovalModel.order_id == order.id)
                )
            ).scalar_one()
        )
    assert total == 1

    reloaded = await _orders(session_factory).get_order(customer_id=customer_id, order_id=order.id)
    assert reloaded.status is OrderStatus.REQUIRES_APPROVAL


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_e_consulta_convergem_para_o_mesmo_resultado(
    data: OrdersPaymentsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakePaymentProvider,
) -> None:
    """Webhook e polling em paralelo: resultado único e monotônico (§12, §17).

    Ambos reportam `APPROVED`. O aplicador é o mesmo e o lock do Payment
    serializa: um aplica, o outro reconhece o mesmo fato. O Order termina
    `PAID` uma única vez.
    """
    customer_id, order_id = await _confirmed_order(data, session_factory)
    criado = await _payments(session_factory, provider).create_payment(
        customer_id=customer_id,
        order_id=order_id,
        idempotency_key=f"pay-{order_id}",
        at=FIXED_NOW,
    )
    charge_id = criado.payment.provider_payment_id
    assert charge_id is not None

    # O provider passa a reportar aprovado: é a única forma de `APPROVED`.
    provider.settle(charge_id, PaymentStatus.APPROVED)

    async def via_webhook() -> object:
        try:
            return await _payments(session_factory, provider).process_webhook(
                provider=ProviderName.FAKE,
                provider_event_id=f"evt-{charge_id}",
                provider_payment_id=charge_id,
                reported_status=PaymentStatus.APPROVED,
                payload={"id": charge_id, "status": "approved"},
                at=FIXED_NOW,
            )
        except Exception as exc:
            return exc

    async def via_consulta() -> object:
        try:
            return await _payments(session_factory, provider).reconcile_payment(
                payment_id=criado.payment.id, at=FIXED_NOW
            )
        except Exception as exc:
            return exc

    await asyncio.gather(via_webhook(), via_consulta())

    async with session_factory() as session:
        payment = await session.get(PaymentModel, criado.payment.id)
        assert payment is not None
        assert payment.status == PaymentStatus.APPROVED.value

    final = await _orders(session_factory).get_order(customer_id=customer_id, order_id=order_id)
    assert final.status is OrderStatus.PAID
    assert await _count_payments(session_factory, order_id) == 1
