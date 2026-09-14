"""Repositories SQLAlchemy do módulo payments (ADR-012, SPEC-003 §9, §12)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from urbanopay.modules.payments.domain.entities import (
    ACTIVE_PAYMENT_STATUSES,
    Payment,
    PaymentEvent,
)
from urbanopay.modules.payments.domain.enums import (
    PaymentMethod,
    PaymentStatus,
    ProviderName,
)
from urbanopay.modules.payments.infrastructure.models import (
    PaymentEventModel,
    PaymentModel,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

_ACTIVE_STATUS_VALUES = tuple(sorted(status.value for status in ACTIVE_PAYMENT_STATUSES))


def _to_payment(model: PaymentModel) -> Payment:
    return Payment(
        id=model.id,
        order_id=model.order_id,
        provider=ProviderName(model.provider),
        provider_payment_id=model.provider_payment_id,
        method=PaymentMethod(model.method),
        amount=model.amount,
        currency=model.currency,
        status=PaymentStatus(model.status),
        idempotency_key=model.idempotency_key,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyPaymentRepository:
    """Implementação do port `PaymentRepository`. Nunca comita."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, payment: Payment) -> None:
        self._session.add(
            PaymentModel(
                id=payment.id,
                order_id=payment.order_id,
                provider=payment.provider.value,
                provider_payment_id=payment.provider_payment_id,
                method=payment.method.value,
                amount=payment.amount,
                currency=payment.currency,
                status=payment.status.value,
                idempotency_key=payment.idempotency_key,
                created_at=payment.created_at,
                updated_at=payment.updated_at,
            )
        )
        # `flush` explícito: é aqui que os índices únicos parciais reprovam uma
        # segunda tentativa ativa, ainda dentro da transação de quem chamou.
        await self._session.flush()

    async def get(self, payment_id: UUID) -> Payment | None:
        stmt = sa.select(PaymentModel).where(PaymentModel.id == payment_id)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_payment(model) if model is not None else None

    async def get_for_update(self, payment_id: UUID) -> Payment | None:
        stmt = sa.select(PaymentModel).where(PaymentModel.id == payment_id).with_for_update()
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_payment(model) if model is not None else None

    async def get_active_for_order(self, order_id: UUID) -> Payment | None:
        stmt = sa.select(PaymentModel).where(
            PaymentModel.order_id == order_id,
            PaymentModel.status.in_(_ACTIVE_STATUS_VALUES),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_payment(model) if model is not None else None

    async def get_approved_for_order(self, order_id: UUID) -> Payment | None:
        stmt = sa.select(PaymentModel).where(
            PaymentModel.order_id == order_id,
            PaymentModel.status == PaymentStatus.APPROVED.value,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_payment(model) if model is not None else None

    async def get_latest_for_order(self, order_id: UUID) -> Payment | None:
        """Tentativa mais recente do Order (§13).

        `id` como critério de desempate mantém o resultado determinístico caso
        dois registros compartilhem o mesmo `created_at` — o que os
        invariantes de §13 não permitem, mas que a consulta não deve depender
        de supor.
        """
        stmt = (
            sa.select(PaymentModel)
            .where(PaymentModel.order_id == order_id)
            .order_by(PaymentModel.created_at.desc(), PaymentModel.id.desc())
            .limit(1)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_payment(model) if model is not None else None

    async def find_by_provider_payment_id(
        self, *, provider: ProviderName, provider_payment_id: str
    ) -> Payment | None:
        stmt = sa.select(PaymentModel).where(
            PaymentModel.provider == provider.value,
            PaymentModel.provider_payment_id == provider_payment_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_payment(model) if model is not None else None

    async def update(self, payment: Payment) -> None:
        stmt = (
            sa.update(PaymentModel)
            .where(PaymentModel.id == payment.id)
            .values(
                status=payment.status.value,
                provider_payment_id=payment.provider_payment_id,
                updated_at=payment.updated_at,
            )
        )
        await self._session.execute(stmt)


class SqlAlchemyPaymentEventRepository:
    """Implementação do port `PaymentEventRepository`. Nunca comita."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, event: PaymentEvent) -> bool:
        """`INSERT ... ON CONFLICT DO NOTHING`: `False` se já existia.

        A deduplicação é a constraint `UNIQUE (provider, provider_event_id)`.
        Nenhuma consulta prévia decide isso — uma verificação seguida de
        inserção teria janela de corrida entre dois webhooks simultâneos.
        """
        stmt = (
            pg_insert(PaymentEventModel)
            .values(
                id=event.id,
                payment_id=event.payment_id,
                provider=event.provider.value,
                provider_event_id=event.provider_event_id,
                reported_status=event.reported_status.value,
                payload=event.payload,
                received_at=event.received_at,
            )
            .on_conflict_do_nothing(index_elements=["provider", "provider_event_id"])
            .returning(PaymentEventModel.id)
        )
        inserted = (await self._session.execute(stmt)).scalar_one_or_none()
        return inserted is not None
