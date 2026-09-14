"""Cria as tabelas de identidade e cartões (SPEC-002).

Revision ID: idc0001
Revises: fare0002
Create Date: 2026-09-07

Escrita à mão, revisão humana obrigatória (ADR-012). Somente estruturas da
SPEC-002 — nenhuma tabela de outras SPECs, nenhum seed (identidades de
demonstração são fixtures de teste, decisão aprovada).

Decisões de minimização aprovadas no plano:

- `customers` sem e-mail/telefone (campos conceituais de §2 sem consumidor) e
  com `cpf_hash` (HMAC-SHA256 com segredo) em vez de CPF;
- `cards` sem número completo: apenas `card_last4` para apresentação
  mascarada (`****NNNN`, §6) — a identidade oficial é o UUID interno;
- `auth_challenges.session_id`: vínculo challenge↔sessão, necessário para
  consumo atômico e supersede (aprovado);
- índice único parcial (1 challenge PENDING por sessão) é última defesa de
  integridade — a serialização normal vem do lock da sessão na aplicação.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "idc0001"
down_revision: str | None = "fare0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cpf_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("cpf_hash", name=op.f("uq_customers_cpf_hash")),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'BLOCKED', 'INACTIVE')",
            name=op.f("ck_customers_status_valid"),
        ),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_customers_name_not_blank")),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("authenticated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name=op.f("fk_sessions_customer_id_customers")
        ),
        sa.CheckConstraint(
            "(NOT authenticated) OR customer_id IS NOT NULL",
            name=op.f("ck_sessions_authenticated_has_customer"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_sessions_expiry_after_creation")
        ),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"])

    op.create_table(
        "auth_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("otp_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_challenges")),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_auth_challenges_customer_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_auth_challenges_session_id_sessions"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'VERIFIED', 'EXPIRED', 'BLOCKED')",
            name=op.f("ck_auth_challenges_status_valid"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_auth_challenges_attempts_non_negative")),
        sa.CheckConstraint(
            "attempts <= max_attempts", name=op.f("ck_auth_challenges_attempts_within_max")
        ),
        sa.CheckConstraint(
            "max_attempts > 0", name=op.f("ck_auth_challenges_max_attempts_positive")
        ),
    )
    op.create_index(
        "uq_auth_challenges_pending_session",
        "auth_challenges",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("card_last4", sa.Text(), nullable=False),
        sa.Column("fare_profile", sa.Text(), nullable=False),
        sa.Column("balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cards")),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name=op.f("fk_cards_customer_id_customers")
        ),
        sa.CheckConstraint(
            "fare_profile IN ('INTEGRAL', 'MEIA')", name=op.f("ck_cards_profile_valid")
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'BLOCKED', 'EXPIRED', 'CANCELLED')",
            name=op.f("ck_cards_status_valid"),
        ),
        sa.CheckConstraint("card_last4 ~ '^[0-9]{4}$'", name=op.f("ck_cards_last4_format")),
        sa.CheckConstraint("balance >= 0", name=op.f("ck_cards_balance_non_negative")),
    )
    op.create_index(op.f("ix_cards_customer_id"), "cards", ["customer_id"])


def downgrade() -> None:
    # Ordem reversa das dependências de FK. Nenhum dado de referência a
    # preservar: esta revision não possui seed.
    op.drop_table("cards")
    op.drop_table("auth_challenges")
    op.drop_table("sessions")
    op.drop_table("customers")
