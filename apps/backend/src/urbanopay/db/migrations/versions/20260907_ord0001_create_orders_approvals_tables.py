"""Cria as tabelas de Quote, Order, Approval e idempotência (SPEC-003).

Revision ID: ord0001
Revises: idc0001
Create Date: 2026-09-07

Escrita à mão, revisão humana obrigatória (ADR-012). Somente estruturas da
SPEC-003 relativas a Quote, Order e Approval — `payments` e `payment_events`
vivem em `pay0001`. Nenhum seed.

A tabela `idempotency_records` é **transversal** (SPEC-003 §11) e não pertence
a nenhum módulo de domínio; nasce aqui porque `create_order` é a primeira
operação que a consome. Os registros ficam no PostgreSQL, nunca no Redis
(ADR-009).

Decisões materializadas como constraint, não apenas como código:

- `quotes` **sem coluna de status**: validade derivada de `expires_at`,
  consumo derivado da existência de um Order que a referencia;
- `uq_orders_quote_id`: uma Quote gera no máximo um Order, para que um único
  consentimento de valor não produza dois pedidos pagáveis;
- `ck_orders_total_matches_parts`: coerência aritmética de dinheiro no banco;
- `ck_orders_cancellation_reason_requires_cancelled`: motivo de cancelamento
  só existe em Order cancelado;
- `uq_approvals_order_id`: uma aprovação por Order — sem isso, duas
  confirmações concorrentes criariam dois pedidos de decisão;
- `ck_approvals_decision_audit_complete`: todo estado terminal tem ator e
  instante (§7); `PENDING` não tem nenhum dos dois;
- `ck_idempotency_records_completed_at_matches_status`: não existe registro
  concluído sem instante de conclusão.

O limiar de aprovação de R$ 200,00 **não** é constraint de banco, por decisão:
a SPEC-003 §7 exige que ele viva encapsulado em `ApprovalPolicy`, e replicá-lo
aqui criaria uma segunda fonte da mesma regra.

Nenhum estado do Order sem caminho de entrada: `ck_orders_status_valid` lista
exatamente os dez estados da §6 — `APPROVED` e `FAILED` foram removidos do
enum e por isso não aparecem aqui.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "ord0001"
down_revision: str | None = "idc0001"
branch_labels: str | None = None
depends_on: str | None = None

_OPERATION_TYPES = "'RECHARGE', 'TICKET_PURCHASE'"
_ORDER_STATUSES = (
    "'DRAFT', 'REQUIRES_APPROVAL', 'CONFIRMED', 'PAYMENT_PENDING', 'PAID', "
    "'FULFILLING', 'COMPLETED', 'FULFILLMENT_FAILED', 'CANCELLED', 'EXPIRED'"
)
_CANCELLATION_REASONS = "'CUSTOMER_REQUEST', 'APPROVAL_REJECTED'"


def upgrade() -> None:
    op.create_table(
        "quotes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column("fare_profile", sa.Text(), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quotes")),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name=op.f("fk_quotes_customer_id_customers")
        ),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], name=op.f("fk_quotes_card_id_cards")),
        sa.CheckConstraint(
            f"operation_type IN ({_OPERATION_TYPES})", name=op.f("ck_quotes_operation_valid")
        ),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_quotes_currency_valid")),
        sa.CheckConstraint("subtotal >= 0", name=op.f("ck_quotes_subtotal_non_negative")),
        sa.CheckConstraint("discount_amount >= 0", name=op.f("ck_quotes_discount_non_negative")),
        sa.CheckConstraint("total >= 0", name=op.f("ck_quotes_total_non_negative")),
        sa.CheckConstraint(
            "discount_amount <= subtotal", name=op.f("ck_quotes_discount_within_subtotal")
        ),
        sa.CheckConstraint(
            "total = subtotal - discount_amount", name=op.f("ck_quotes_total_matches_parts")
        ),
    )
    op.create_index("ix_quotes_customer_id", "quotes", ["customer_id"])

    op.create_table(
        "quote_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_items")),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name=op.f("fk_quote_items_quote_id_quotes"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_quote_items_quantity_positive")),
        sa.CheckConstraint(
            "unit_amount >= 0", name=op.f("ck_quote_items_unit_amount_non_negative")
        ),
        sa.CheckConstraint(
            "total_amount = unit_amount * quantity",
            name=op.f("ck_quote_items_total_matches_quantity"),
        ),
    )
    op.create_index("ix_quote_items_quote_id", "quote_items", ["quote_id"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("quote_id", name=op.f("uq_orders_quote_id")),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name=op.f("fk_orders_customer_id_customers")
        ),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], name=op.f("fk_orders_card_id_cards")),
        sa.ForeignKeyConstraint(
            ["quote_id"], ["quotes.id"], name=op.f("fk_orders_quote_id_quotes")
        ),
        sa.CheckConstraint(
            f"operation_type IN ({_OPERATION_TYPES})", name=op.f("ck_orders_operation_valid")
        ),
        sa.CheckConstraint(f"status IN ({_ORDER_STATUSES})", name=op.f("ck_orders_status_valid")),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_orders_currency_valid")),
        sa.CheckConstraint("subtotal >= 0", name=op.f("ck_orders_subtotal_non_negative")),
        sa.CheckConstraint("discount_amount >= 0", name=op.f("ck_orders_discount_non_negative")),
        sa.CheckConstraint("total >= 0", name=op.f("ck_orders_total_non_negative")),
        sa.CheckConstraint(
            "discount_amount <= subtotal", name=op.f("ck_orders_discount_within_subtotal")
        ),
        sa.CheckConstraint(
            "total = subtotal - discount_amount", name=op.f("ck_orders_total_matches_parts")
        ),
        sa.CheckConstraint(
            f"cancellation_reason IS NULL OR cancellation_reason IN ({_CANCELLATION_REASONS})",
            name=op.f("ck_orders_cancellation_reason_valid"),
        ),
        sa.CheckConstraint(
            "cancellation_reason IS NULL OR status = 'CANCELLED'",
            name=op.f("ck_orders_cancellation_reason_requires_cancelled"),
        ),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_status_expires_at", "orders", ["status", "expires_at"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_items_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_items_quantity_positive")),
        sa.CheckConstraint(
            "unit_amount >= 0", name=op.f("ck_order_items_unit_amount_non_negative")
        ),
        sa.CheckConstraint(
            "total_amount = unit_amount * quantity",
            name=op.f("ck_order_items_total_matches_quantity"),
        ),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
        sa.UniqueConstraint("order_id", name=op.f("uq_approvals_order_id")),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_approvals_order_id_orders")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name=op.f("ck_approvals_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND decided_at IS NULL AND decided_by IS NULL)"
            " OR (status <> 'PENDING' AND decided_at IS NOT NULL AND decided_by IS NOT NULL)",
            name=op.f("ck_approvals_decision_audit_complete"),
        ),
    )
    op.create_index("ix_approvals_status_requested_at", "approvals", ["status", "requested_at"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("response_reference", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_records")),
        sa.UniqueConstraint("operation", "key", name=op.f("uq_idempotency_records_operation_key")),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')",
            name=op.f("ck_idempotency_records_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'IN_PROGRESS' AND completed_at IS NULL)"
            " OR (status <> 'IN_PROGRESS' AND completed_at IS NOT NULL)",
            name=op.f("ck_idempotency_records_completed_at_matches_status"),
        ),
    )
    op.create_index(
        "ix_idempotency_records_status_updated_at",
        "idempotency_records",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    # Ordem inversa da criação, respeitando as dependências de chave
    # estrangeira. Reversível por decisão (ADR-012).
    op.drop_index("ix_idempotency_records_status_updated_at", table_name="idempotency_records")
    op.drop_table("idempotency_records")

    op.drop_index("ix_approvals_status_requested_at", table_name="approvals")
    op.drop_table("approvals")

    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")

    op.drop_index("ix_orders_status_expires_at", table_name="orders")
    op.drop_index("ix_orders_customer_id", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_quote_items_quote_id", table_name="quote_items")
    op.drop_table("quote_items")

    op.drop_index("ix_quotes_customer_id", table_name="quotes")
    op.drop_table("quotes")
