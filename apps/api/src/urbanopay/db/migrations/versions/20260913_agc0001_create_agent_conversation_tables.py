"""Cria as tabelas da camada conversacional.

Revision ID: agc0001
Revises: ful0001
Create Date: 2026-09-13

Fonte: ADR-014 (application-owned conversational state persistence), ADR-012.

Head verificado antes de escrever esta revision: `alembic heads` devolvia
`ful0001`, conforme o ADR-014 exige — a cadeia não foi assumida.

Duas tabelas, ambas da aplicação e ambas versionadas aqui. **Nenhum schema é
criado por runtime ou por framework**: não existe checkpointer nativo do
LangGraph, não existe `setup()` e não existe `create_all()`.

O que esta migration deliberadamente **não** cria: coluna monetária, JSONB,
texto livre de mensagem, CPF, OTP, hash ou qualquer status de agregado. A
ausência é o controle de PII e de autoridade — sem coluna onde caibam, não há
caminho pelo qual entrem.

`agent_turn_requests` resolve D-6 do ADR-014: idempotência do request HTTP, que
é preocupação distinta das keys de negócio e **não** reutiliza
`idempotency_records`, que é auditoria de comando de domínio (A-13).

Downgrade é seguro porque nenhum dado autoritativo mora aqui: apagar as duas
tabelas não faz o sistema perder fato algum.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "agc0001"
down_revision: str | None = "ful0001"
branch_labels: str | None = None
depends_on: str | None = None

_PHASES = (
    "DISCOVERY",
    "CALCULATION",
    "RECOMMENDATION",
    "AUTHENTICATION",
    "AWAITING_DOCUMENT",
    "AWAITING_OTP",
    "CARD_SELECTION",
    "QUOTE",
    "ORDER_CONFIRMATION",
    "APPROVAL",
    "PAYMENT",
    "FULFILLMENT",
    "POST_SALE",
    "COMPLETED",
    "ERROR",
)


def upgrade() -> None:
    phases = ", ".join(f"'{phase}'" for phase in _PHASES)

    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Única FK: âncora de identidade e ownership. Os demais identificadores
        # são referências de navegação, revalidadas contra os módulos donos a
        # cada uso — FK sobre elas imporia integridade que o desenho recusa.
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("selected_card_id", sa.Uuid(), nullable=True),
        sa.Column("current_quote_id", sa.Uuid(), nullable=True),
        sa.Column("current_order_id", sa.Uuid(), nullable=True),
        sa.Column("current_payment_id", sa.Uuid(), nullable=True),
        sa.Column("pending_confirmation_order_id", sa.Uuid(), nullable=True),
        sa.Column("pending_confirmation_presented_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(f"phase IN ({phases})", name="phase_valid"),
        sa.CheckConstraint(
            "(pending_confirmation_order_id IS NULL) = (pending_confirmation_presented_at IS NULL)",
            name="pending_confirmation_pair",
        ),
        # SPEC-004 §9.1 no banco: a confirmação pendente sempre vincula o Order
        # corrente. É a defesa em constraint contra um "sim" confirmar outra
        # Order — inclusive uma Order válida do mesmo cliente.
        sa.CheckConstraint(
            "pending_confirmation_order_id IS NULL"
            " OR pending_confirmation_order_id = current_order_id",
            name="pending_confirmation_binds_current_order",
        ),
        sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_agent_conversations_session_id_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_conversations")),
    )
    op.create_index("ix_agent_conversations_session_id", "agent_conversations", ["session_id"])
    op.create_index("ix_agent_conversations_expires_at", "agent_conversations", ["expires_at"])

    op.create_table(
        "agent_turn_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_turn_requests")),
        sa.UniqueConstraint(
            "conversation_id",
            "request_id",
            name=op.f("uq_agent_turn_requests_conversation_id_request_id"),
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_turn_requests")
    op.drop_index("ix_agent_conversations_expires_at", table_name="agent_conversations")
    op.drop_index("ix_agent_conversations_session_id", table_name="agent_conversations")
    op.drop_table("agent_conversations")
