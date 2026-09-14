"""Cria as tabelas de Payment e PaymentEvent (SPEC-003 §9, §12).

Revision ID: pay0001
Revises: ord0001
Create Date: 2026-09-07

Escrita à mão, revisão humana obrigatória (ADR-012). Nenhum seed, nenhuma
credencial, nenhum dado de provider real.

Esta migration materializa as invariantes financeiras que o banco **pode**
garantir, para que sobrevivam a um defeito de aplicação:

- `uq_payments_approved_per_order` — no máximo um Payment `APPROVED` por
  Order. É a barreira final contra cobrança duplicada;
- `uq_payments_active_per_order` — no máximo uma tentativa ativa
  (`CREATED`/`PENDING`) por Order. Dois `create_payment` concorrentes não
  conseguem criar duas cobranças, mesmo que o lock de aplicação falhe;
- `uq_payments_idempotency_key` — uma idempotency key produz um único
  Payment, o que materializa a regra do retry técnico (§13.1): mesma key,
  nenhum Payment novo;
- `uq_payments_provider_payment_id` — um identificador externo pertence a um
  único Payment por provider;
- `uq_payment_events_provider_provider_event_id` — webhook duplicado é
  registrado uma única vez, e portanto produz efeito único (§12).

Os três primeiros são **índices únicos parciais**: a unicidade vale apenas
para as linhas no estado relevante, o que é exatamente o que a SPEC pede — um
Order pode ter `1..N` Payments, desde que no máximo um aprovado e no máximo um
ativo.

Duas invariantes **não** são expressáveis aqui porque cruzam tabelas:
`payment.amount == order.total` e `Order PAID ⇔ existe Payment APPROVED`.
Ambas ficam garantidas pelo serviço de aplicação e cobertas por teste;
a ausência de constraint é limitação conhecida e registrada.

`payment_events.payload` recebe apenas conteúdo **redigido** por allowlist no
domínio: nunca token, secret, credencial ou PII desnecessária. O código
copia-e-cola do Pix também não é persistido em `payments`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "pay0001"
down_revision: str | None = "ord0001"
branch_labels: str | None = None
depends_on: str | None = None

_PAYMENT_STATUSES = "'CREATED', 'PENDING', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED', 'FAILED'"
_PROVIDERS = "'FAKE', 'MERCADOPAGO'"


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_payment_id", sa.Text(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_payments_order_id_orders")
        ),
        sa.CheckConstraint(
            f"status IN ({_PAYMENT_STATUSES})", name=op.f("ck_payments_status_valid")
        ),
        sa.CheckConstraint(f"provider IN ({_PROVIDERS})", name=op.f("ck_payments_provider_valid")),
        sa.CheckConstraint("method IN ('PIX')", name=op.f("ck_payments_method_valid")),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_payments_currency_valid")),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payments_amount_positive")),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index("uq_payments_idempotency_key", "payments", ["idempotency_key"], unique=True)
    op.create_index(
        "uq_payments_approved_per_order",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.create_index(
        "uq_payments_active_per_order",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('CREATED', 'PENDING')"),
    )
    op.create_index(
        "uq_payments_provider_payment_id",
        "payments",
        ["provider", "provider_payment_id"],
        unique=True,
        postgresql_where=sa.text("provider_payment_id IS NOT NULL"),
    )

    op.create_table(
        "payment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_event_id", sa.Text(), nullable=False),
        sa.Column("reported_status", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_events")),
        sa.UniqueConstraint(
            "provider",
            "provider_event_id",
            name=op.f("uq_payment_events_provider_provider_event_id"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_payment_events_payment_id_payments")
        ),
        sa.CheckConstraint(
            f"reported_status IN ({_PAYMENT_STATUSES})",
            name=op.f("ck_payment_events_reported_status_valid"),
        ),
        sa.CheckConstraint(
            f"provider IN ({_PROVIDERS})", name=op.f("ck_payment_events_provider_valid")
        ),
    )
    op.create_index("ix_payment_events_payment_id", "payment_events", ["payment_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_events_payment_id", table_name="payment_events")
    op.drop_table("payment_events")

    op.drop_index("uq_payments_provider_payment_id", table_name="payments")
    op.drop_index("uq_payments_active_per_order", table_name="payments")
    op.drop_index("uq_payments_approved_per_order", table_name="payments")
    op.drop_index("uq_payments_idempotency_key", table_name="payments")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_table("payments")
