"""Invariantes garantidas pelo banco (SPEC-003; ADR-012).

Cada teste escreve **direto nas tabelas**, sem passar pelos serviços. É
proposital: o que se prova aqui é que o banco recusa o estado inválido mesmo
que a camada de aplicação tenha um defeito. Constraint que só é testada através
do serviço não prova nada sobre o banco.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.orders_payments.conftest import (
    FIXED_NOW,
    TTL,
    OrdersPaymentsTestData,
)
from urbanopay.db.idempotency import IdempotencyRecordModel
from urbanopay.modules.approvals.infrastructure.models import ApprovalModel
from urbanopay.modules.orders.infrastructure.models import OrderModel, QuoteModel
from urbanopay.modules.payments.infrastructure.models import (
    PaymentEventModel,
    PaymentModel,
)


async def _seed_quote_and_order(
    data: OrdersPaymentsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    total: Decimal = Decimal("50.00"),
    status: str = "CONFIRMED",
) -> tuple[uuid.UUID, uuid.UUID]:
    """Quote e Order válidos, escritos direto no banco."""
    customer_id, card_id = await data.add_customer_with_card()
    quote_id = uuid.uuid4()
    order_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            QuoteModel(
                id=quote_id,
                customer_id=customer_id,
                card_id=card_id,
                operation_type="RECHARGE",
                fare_profile="INTEGRAL",
                subtotal=total,
                discount_amount=Decimal("0.00"),
                total=total,
                currency="BRL",
                expires_at=FIXED_NOW + TTL,
                created_at=FIXED_NOW,
            )
        )
        # `flush` antes do Order: sem `relationship()`, a ordem de INSERT por
        # dependência de FK não é garantida (`fk_orders_quote_id_quotes`).
        await session.flush()
        session.add(
            OrderModel(
                id=order_id,
                customer_id=customer_id,
                card_id=card_id,
                quote_id=quote_id,
                operation_type="RECHARGE",
                status=status,
                subtotal=total,
                discount_amount=Decimal("0.00"),
                total=total,
                currency="BRL",
                requires_approval=False,
                expires_at=FIXED_NOW + TTL,
                cancellation_reason=None,
                created_at=FIXED_NOW,
                updated_at=FIXED_NOW,
            )
        )
        await session.commit()
    return quote_id, order_id


def _payment(
    order_id: uuid.UUID, *, status: str, key: str, external: str | None = None
) -> PaymentModel:
    return PaymentModel(
        id=uuid.uuid4(),
        order_id=order_id,
        provider="FAKE",
        provider_payment_id=external,
        method="PIX",
        amount=Decimal("50.00"),
        currency="BRL",
        status=status,
        idempotency_key=key,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


# --- unicidade de pagamento ---------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_maximo_uma_tentativa_ativa_por_order(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`uq_payments_active_per_order`: barreira final contra cobrança dupla."""
    _, order_id = await _seed_quote_and_order(data, session_factory)

    async with session_factory() as session:
        session.add(_payment(order_id, status="CREATED", key=f"k1-{order_id}"))
        await session.commit()

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(_payment(order_id, status="PENDING", key=f"k2-{order_id}"))
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_maximo_um_pagamento_aprovado_por_order(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`uq_payments_approved_per_order`."""
    _, order_id = await _seed_quote_and_order(data, session_factory)

    async with session_factory() as session:
        session.add(_payment(order_id, status="APPROVED", key=f"a1-{order_id}"))
        await session.commit()

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(_payment(order_id, status="APPROVED", key=f"a2-{order_id}"))
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminais_nao_aprovados_convivem_no_mesmo_order(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`1..N` Payments por Order é permitido — a unicidade é parcial (§13)."""
    _, order_id = await _seed_quote_and_order(data, session_factory)

    async with session_factory() as session:
        session.add(_payment(order_id, status="REJECTED", key=f"r1-{order_id}"))
        session.add(_payment(order_id, status="EXPIRED", key=f"r2-{order_id}"))
        session.add(_payment(order_id, status="CANCELLED", key=f"r3-{order_id}"))
        session.add(_payment(order_id, status="FAILED", key=f"r4-{order_id}"))
        # Uma tentativa ativa ao lado de vários terminais continua válida.
        session.add(_payment(order_id, status="PENDING", key=f"r5-{order_id}"))
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_uma_idempotency_key_produz_um_unico_payment(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`uq_payments_idempotency_key`: materializa o retry técnico (§13.1)."""
    _, order_id = await _seed_quote_and_order(data, session_factory)
    key = f"same-{order_id}"

    async with session_factory() as session:
        session.add(_payment(order_id, status="REJECTED", key=key))
        await session.commit()

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(_payment(order_id, status="PENDING", key=key))
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_identificador_externo_pertence_a_um_unico_payment(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`uq_payments_provider_payment_id`."""
    _, order_id = await _seed_quote_and_order(data, session_factory)

    async with session_factory() as session:
        session.add(_payment(order_id, status="REJECTED", key=f"e1-{order_id}", external="ext-dup"))
        await session.commit()

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                _payment(order_id, status="EXPIRED", key=f"e2-{order_id}", external="ext-dup")
            )
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_valor_de_pagamento_precisa_ser_positivo(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ck_payments_amount_positive`."""
    _, order_id = await _seed_quote_and_order(data, session_factory)

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            payment = _payment(order_id, status="CREATED", key=f"z-{order_id}")
            payment.amount = Decimal("0.00")
            session.add(payment)
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_de_pagamento_fora_do_dominio_e_recusado(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ck_payments_status_valid`: não existe `UNKNOWN` nem estado inventado."""
    _, order_id = await _seed_quote_and_order(data, session_factory)

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            payment = _payment(order_id, status="UNKNOWN", key=f"u-{order_id}")
            session.add(payment)
            await session.commit()


# --- deduplicação de evento (§12) ---------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_evento_de_provider_e_unico(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`uq_payment_events_provider_provider_event_id`: webhook duplicado."""
    _, order_id = await _seed_quote_and_order(data, session_factory)
    payment = _payment(order_id, status="PENDING", key=f"ev-{order_id}", external="ext-ev")
    async with session_factory() as session:
        session.add(payment)
        await session.commit()

    def event() -> PaymentEventModel:
        return PaymentEventModel(
            id=uuid.uuid4(),
            payment_id=payment.id,
            provider="FAKE",
            provider_event_id="evt-duplicado",
            reported_status="APPROVED",
            payload={"id": "ext-ev"},
            received_at=FIXED_NOW,
        )

    async with session_factory() as session:
        session.add(event())
        await session.commit()

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(event())
            await session.commit()


# --- Order e Quote -------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_uma_quote_gera_no_maximo_um_order(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`uq_orders_quote_id` (§4)."""
    quote_id, order = await _seed_quote_and_order(data, session_factory)

    async with session_factory() as session:
        existing = await session.get(OrderModel, order)
        assert existing is not None
        customer_id, card_id = existing.customer_id, existing.card_id

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                OrderModel(
                    id=uuid.uuid4(),
                    customer_id=customer_id,
                    card_id=card_id,
                    quote_id=quote_id,
                    operation_type="RECHARGE",
                    status="DRAFT",
                    subtotal=Decimal("50.00"),
                    discount_amount=Decimal("0.00"),
                    total=Decimal("50.00"),
                    currency="BRL",
                    requires_approval=False,
                    expires_at=FIXED_NOW + TTL,
                    cancellation_reason=None,
                    created_at=FIXED_NOW,
                    updated_at=FIXED_NOW,
                )
            )
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_total_incoerente_e_recusado(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ck_orders_total_matches_parts`: aritmética de dinheiro no banco."""
    customer_id, card_id = await data.add_customer_with_card()
    quote_id = uuid.uuid4()

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                QuoteModel(
                    id=quote_id,
                    customer_id=customer_id,
                    card_id=card_id,
                    operation_type="RECHARGE",
                    fare_profile="INTEGRAL",
                    subtotal=Decimal("100.00"),
                    discount_amount=Decimal("10.00"),
                    total=Decimal("100.00"),  # deveria ser 90,00
                    currency="BRL",
                    expires_at=FIXED_NOW + TTL,
                    created_at=FIXED_NOW,
                )
            )
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_de_order_fora_do_dominio_e_recusado(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ck_orders_status_valid`: `APPROVED` e `FAILED` não existem no enum (§6)."""
    for status_invalido in ("APPROVED", "FAILED"):
        with pytest.raises(IntegrityError):
            await _seed_quote_and_order(data, session_factory, status=status_invalido)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_motivo_de_cancelamento_exige_order_cancelado(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ck_orders_cancellation_reason_requires_cancelled`.

    Impede que a rejeição de aprovação fique registrada em um Order que
    seguiu adiante.
    """
    _, order_id = await _seed_quote_and_order(data, session_factory, status="CONFIRMED")

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            order = await session.get(OrderModel, order_id)
            assert order is not None
            order.cancellation_reason = "APPROVAL_REJECTED"
            await session.commit()


# --- Approval ------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_uma_aprovacao_por_order(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`uq_approvals_order_id`."""
    _, order_id = await _seed_quote_and_order(data, session_factory, status="REQUIRES_APPROVAL")

    def approval() -> ApprovalModel:
        return ApprovalModel(
            id=uuid.uuid4(),
            order_id=order_id,
            status="PENDING",
            requested_at=FIXED_NOW,
            decided_at=None,
            decided_by=None,
        )

    async with session_factory() as session:
        session.add(approval())
        await session.commit()

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(approval())
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pendente_nao_pode_ter_decisao_registrada(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """`ck_approvals_decision_audit_complete` (§7)."""
    _, order_id = await _seed_quote_and_order(data, session_factory, status="REQUIRES_APPROVAL")

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                ApprovalModel(
                    id=uuid.uuid4(),
                    order_id=order_id,
                    status="PENDING",
                    requested_at=FIXED_NOW,
                    decided_at=FIXED_NOW,
                    decided_by="operator-1",
                )
            )
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_decisao_exige_ator_e_instante(
    data: OrdersPaymentsTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Toda decisão registra ator e instante — sem exceção (§7)."""
    _, order_id = await _seed_quote_and_order(data, session_factory, status="REQUIRES_APPROVAL")

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                ApprovalModel(
                    id=uuid.uuid4(),
                    order_id=order_id,
                    status="APPROVED",
                    requested_at=FIXED_NOW,
                    decided_at=FIXED_NOW,
                    decided_by=None,
                )
            )
            await session.commit()


# --- idempotência (§11) --------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_escopo_de_idempotencia_e_unico(
    session_factory: async_sessionmaker[AsyncSession], migrated: None
) -> None:
    """`uq_idempotency_records_operation_key`: base de toda a não duplicação."""
    key = f"unique-{uuid.uuid4()}"

    def record() -> IdempotencyRecordModel:
        return IdempotencyRecordModel(
            id=uuid.uuid4(),
            operation="create_payment",
            key=key,
            request_fingerprint="abc",
            status="IN_PROGRESS",
            resource_id=None,
            response_reference=None,
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
            completed_at=None,
        )

    async with session_factory() as session:
        session.add(record())
        await session.commit()
    try:
        with pytest.raises(IntegrityError):
            async with session_factory() as session:
                session.add(record())
                await session.commit()

        # A mesma key em OUTRA operação é legítima: o escopo é o par.
        async with session_factory() as session:
            outra = record()
            outra.operation = "create_order"
            session.add(outra)
            await session.commit()
    finally:
        async with session_factory() as session:
            await session.execute(
                sa.delete(IdempotencyRecordModel).where(IdempotencyRecordModel.key == key)
            )
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registro_concluido_exige_instante_de_conclusao(
    session_factory: async_sessionmaker[AsyncSession], migrated: None
) -> None:
    """`ck_idempotency_records_completed_at_matches_status`."""
    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                IdempotencyRecordModel(
                    id=uuid.uuid4(),
                    operation="create_payment",
                    key=f"bad-{uuid.uuid4()}",
                    request_fingerprint="abc",
                    status="COMPLETED",
                    resource_id=None,
                    response_reference=None,
                    created_at=FIXED_NOW,
                    updated_at=FIXED_NOW,
                    completed_at=None,
                )
            )
            await session.commit()
