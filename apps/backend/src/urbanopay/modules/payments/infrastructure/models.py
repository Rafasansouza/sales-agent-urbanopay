"""Modelos ORM do módulo payments (SPEC-003 §9, §12; ADR-012).

Aqui vivem as constraints que sustentam as invariantes financeiras. Elas não
substituem as verificações do serviço de aplicação — existem justamente para
sobreviver a um defeito nele:

- **no máximo um `APPROVED` por Order** (índice único parcial);
- **no máximo uma tentativa ativa por Order** (`CREATED`/`PENDING`, índice
  único parcial) — é o que barra duas cobranças simultâneas;
- **uma idempotency key produz um único Payment** (índice único), o que
  materializa a regra do retry técnico: mesma key, nenhum Payment novo;
- **um identificador externo pertence a um único Payment** por provider;
- **webhook duplicado é registrado uma única vez**
  (`UNIQUE (provider, provider_event_id)`).

Duas invariantes **não** são expressáveis em `CHECK` porque cruzam tabelas:
`payment.amount == order.total` e `Order PAID ⇔ existe Payment APPROVED`.
Ambas são garantidas pelo serviço de aplicação e cobertas por teste — a
ausência de constraint é limitação conhecida, não descuido.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from urbanopay.db.base import Base

_PAYMENT_STATUSES = "'CREATED', 'PENDING', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED', 'FAILED'"
_PROVIDERS = "'FAKE', 'MERCADOPAGO'"


class PaymentModel(Base):
    """Tentativa comercial de pagamento (SPEC-003 §9, §13)."""

    __tablename__ = "payments"
    __table_args__ = (
        sa.CheckConstraint(f"status IN ({_PAYMENT_STATUSES})", name="status_valid"),
        sa.CheckConstraint(f"provider IN ({_PROVIDERS})", name="provider_valid"),
        sa.CheckConstraint("method IN ('PIX')", name="method_valid"),
        sa.CheckConstraint("currency = 'BRL'", name="currency_valid"),
        sa.CheckConstraint("amount > 0", name="amount_positive"),
        # Uma key produz um único Payment (§13.1).
        sa.Index("uq_payments_idempotency_key", "idempotency_key", unique=True),
        # No máximo um Payment APPROVED por Order (§13).
        sa.Index(
            "uq_payments_approved_per_order",
            "order_id",
            unique=True,
            postgresql_where=sa.text("status = 'APPROVED'"),
        ),
        # No máximo uma tentativa ativa por Order (§9).
        sa.Index(
            "uq_payments_active_per_order",
            "order_id",
            unique=True,
            postgresql_where=sa.text("status IN ('CREATED', 'PENDING')"),
        ),
        # Um identificador externo pertence a um único Payment por provider.
        sa.Index(
            "uq_payments_provider_payment_id",
            "provider",
            "provider_payment_id",
            unique=True,
            postgresql_where=sa.text("provider_payment_id IS NOT NULL"),
        ),
        sa.Index("ix_payments_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("orders.id"))
    provider: Mapped[str] = mapped_column(sa.Text())
    # Nulo enquanto o provider não confirmou a criação — inclusive no caso de
    # timeout (§9.1). O código copia-e-cola do Pix NÃO é persistido.
    provider_payment_id: Mapped[str | None] = mapped_column(sa.Text())
    method: Mapped[str] = mapped_column(sa.Text())
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    currency: Mapped[str] = mapped_column(sa.Text())
    status: Mapped[str] = mapped_column(sa.Text())
    idempotency_key: Mapped[str] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))


class PaymentEventModel(Base):
    """Evento de provider recebido por webhook ou consulta ativa (§12).

    `payload` guarda apenas o conteúdo **redigido** pela allowlist do domínio.
    Nunca token, secret, credencial ou PII desnecessária.
    """

    __tablename__ = "payment_events"
    __table_args__ = (
        # Deduplicação de webhook como constraint de banco, não verificação em
        # memória: é o que garante efeito único sob concorrência real.
        sa.UniqueConstraint("provider", "provider_event_id"),
        sa.CheckConstraint(
            f"reported_status IN ({_PAYMENT_STATUSES})", name="reported_status_valid"
        ),
        sa.CheckConstraint(f"provider IN ({_PROVIDERS})", name="provider_valid"),
        sa.Index("ix_payment_events_payment_id", "payment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("payments.id"))
    provider: Mapped[str] = mapped_column(sa.Text())
    provider_event_id: Mapped[str] = mapped_column(sa.Text())
    reported_status: Mapped[str] = mapped_column(sa.Text())
    payload: Mapped[dict[str, str]] = mapped_column(JSONB())
    received_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
