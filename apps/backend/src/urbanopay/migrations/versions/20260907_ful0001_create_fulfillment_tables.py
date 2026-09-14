"""Cria as tabelas de Fulfillment, ledger do cartão e comprovante (SPEC-005).

Revision ID: ful0001
Revises: pay0001
Create Date: 2026-09-07

Escrita à mão, revisão humana obrigatória (ADR-012). Somente estruturas da
SPEC-005 no recorte `RECHARGE`. Nenhum seed.

Uma única revision porque as três tabelas formam **uma unidade**: elas nascem,
são escritas e são lidas na mesma transação de fulfillment.

Entidades da SPEC-005 §4 **não** materializadas aqui, por decisão registrada
em A-16 e em SPEC-005 §4.1: `RechargeTransaction` (representada pelo
`CardLedgerEntry` de tipo `RECHARGE_CREDIT`), `FulfillmentAttempt`,
`ReconciliationRecord` e `Ticket` — este último bloqueado por A-05.

A constraint decisiva desta migration é
`uq_card_ledger_entries_recharge_per_order`: **um crédito de recarga por
Order**. É a barreira que sobrevive a um defeito de aplicação — mesmo que o
serviço perca o lock e a verificação de idempotência, o banco recusa o
segundo crédito. Índice **parcial** de propósito: a unicidade vale para o
efeito de recarga, deixando espaço para outros tipos de movimento no futuro.

Duas invariantes cruzam tabelas e não são expressáveis em `CHECK` —
`ledger.amount == order.total` e `Order COMPLETED ⇔ existe ledger`. Ficam
garantidas pelo serviço de aplicação, cobertas por teste e observáveis pelas
consultas de consistência da §12.1. A ausência de constraint é limitação
conhecida, não descuido.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "ful0001"
down_revision: str | None = "pay0001"
branch_labels: str | None = None
depends_on: str | None = None

_FULFILLMENT_STATUSES = "'PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'RECONCILIATION_REQUIRED'"
_FULFILLMENT_TYPES = "'RECHARGE', 'TICKET_ISSUANCE'"
_FAILURE_CLASSES = "'RETRYABLE', 'NON_RETRYABLE', 'UNKNOWN_OUTCOME'"
_TERMINAL_FAILURE_STATUSES = "'FAILED', 'RECONCILIATION_REQUIRED'"
_OPERATION_TYPES = "'RECHARGE', 'TICKET_PURCHASE'"


def upgrade() -> None:
    op.create_table(
        "fulfillments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("fulfillment_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("failure_class", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fulfillments")),
        sa.UniqueConstraint("order_id", name=op.f("uq_fulfillments_order_id")),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_fulfillments_order_id_orders")
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_fulfillments_payment_id_payments")
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name=op.f("fk_fulfillments_card_id_cards")
        ),
        sa.CheckConstraint(
            f"status IN ({_FULFILLMENT_STATUSES})", name=op.f("ck_fulfillments_status_valid")
        ),
        sa.CheckConstraint(
            f"fulfillment_type IN ({_FULFILLMENT_TYPES})",
            name=op.f("ck_fulfillments_type_valid"),
        ),
        sa.CheckConstraint(
            f"failure_class IS NULL OR failure_class IN ({_FAILURE_CLASSES})",
            name=op.f("ck_fulfillments_failure_class_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETED' AND completed_at IS NOT NULL)"
            " OR (status <> 'COMPLETED' AND completed_at IS NULL)",
            name=op.f("ck_fulfillments_completed_at_matches_status"),
        ),
        sa.CheckConstraint(
            f"(status IN ({_TERMINAL_FAILURE_STATUSES})"
            " AND failure_reason IS NOT NULL AND failure_class IS NOT NULL)"
            f" OR (status NOT IN ({_TERMINAL_FAILURE_STATUSES})"
            " AND failure_reason IS NULL AND failure_class IS NULL)",
            name=op.f("ck_fulfillments_failure_metadata_matches_status"),
        ),
        sa.CheckConstraint(
            "updated_at >= created_at", name=op.f("ck_fulfillments_updated_after_created")
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name=op.f("ck_fulfillments_completed_after_created"),
        ),
    )
    op.create_index("ix_fulfillments_status", "fulfillments", ["status"])
    op.create_index("ix_fulfillments_card_id", "fulfillments", ["card_id"])

    op.create_table(
        "card_ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fulfillment_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("entry_type", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("balance_before", sa.Numeric(12, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_ledger_entries")),
        sa.ForeignKeyConstraint(
            ["fulfillment_id"],
            ["fulfillments.id"],
            name=op.f("fk_card_ledger_entries_fulfillment_id_fulfillments"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_card_ledger_entries_order_id_orders")
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["cards.id"], name=op.f("fk_card_ledger_entries_card_id_cards")
        ),
        sa.CheckConstraint(
            "entry_type IN ('RECHARGE_CREDIT')",
            name=op.f("ck_card_ledger_entries_entry_type_valid"),
        ),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_card_ledger_entries_currency_valid")),
        sa.CheckConstraint("amount > 0", name=op.f("ck_card_ledger_entries_amount_positive")),
        sa.CheckConstraint(
            "balance_before >= 0",
            name=op.f("ck_card_ledger_entries_balance_before_non_negative"),
        ),
        sa.CheckConstraint(
            "balance_after >= 0",
            name=op.f("ck_card_ledger_entries_balance_after_non_negative"),
        ),
        sa.CheckConstraint(
            "balance_after = balance_before + amount",
            name=op.f("ck_card_ledger_entries_balance_arithmetic"),
        ),
    )
    op.create_index("ix_card_ledger_entries_card_id", "card_ledger_entries", ["card_id"])
    op.create_index(
        "ix_card_ledger_entries_fulfillment_id", "card_ledger_entries", ["fulfillment_id"]
    )
    # A invariante central da SPEC-005: um efeito financeiro por Order.
    op.create_index(
        "uq_card_ledger_entries_recharge_per_order",
        "card_ledger_entries",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("entry_type = 'RECHARGE_CREDIT'"),
    )

    op.create_table(
        "receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("fulfillment_id", sa.Uuid(), nullable=False),
        sa.Column("card_last4", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column("document_kind", sa.Text(), nullable=False),
        sa.Column("disclaimer_version", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipts")),
        sa.UniqueConstraint("order_id", name=op.f("uq_receipts_order_id")),
        sa.UniqueConstraint("fulfillment_id", name=op.f("uq_receipts_fulfillment_id")),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_receipts_order_id_orders")
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_receipts_payment_id_payments")
        ),
        sa.ForeignKeyConstraint(
            ["fulfillment_id"],
            ["fulfillments.id"],
            name=op.f("fk_receipts_fulfillment_id_fulfillments"),
        ),
        sa.CheckConstraint(
            "document_kind IN ('SIMULATED_NON_FISCAL')",
            name=op.f("ck_receipts_document_kind_valid"),
        ),
        sa.CheckConstraint(
            f"operation_type IN ({_OPERATION_TYPES})", name=op.f("ck_receipts_operation_valid")
        ),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_receipts_currency_valid")),
        sa.CheckConstraint("amount > 0", name=op.f("ck_receipts_amount_positive")),
        sa.CheckConstraint("card_last4 ~ '^[0-9]{4}$'", name=op.f("ck_receipts_last4_format")),
        sa.CheckConstraint(
            "btrim(disclaimer_version) <> ''",
            name=op.f("ck_receipts_disclaimer_version_present"),
        ),
    )


def downgrade() -> None:
    # Ordem inversa da criação, respeitando as dependências de chave
    # estrangeira. Reversível por decisão (ADR-012).
    op.drop_table("receipts")

    op.drop_index("uq_card_ledger_entries_recharge_per_order", table_name="card_ledger_entries")
    op.drop_index("ix_card_ledger_entries_fulfillment_id", table_name="card_ledger_entries")
    op.drop_index("ix_card_ledger_entries_card_id", table_name="card_ledger_entries")
    op.drop_table("card_ledger_entries")

    op.drop_index("ix_fulfillments_card_id", table_name="fulfillments")
    op.drop_index("ix_fulfillments_status", table_name="fulfillments")
    op.drop_table("fulfillments")
