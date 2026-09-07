"""Modelos ORM do módulo identity (SPEC-002 §2; ADR-012).

Somente mapeamento de persistência — nenhuma regra de autenticação aqui.

Dados sensíveis: `cpf_hash` e `otp_hash` são derivados por HMAC (nunca os
valores originais) e mesmo assim não aparecem em `repr` das entidades de
domínio. As tabelas não armazenam CPF, OTP, e-mail ou telefone.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from urbanopay.db.base import Base


class CustomerModel(Base):
    """Cliente (SPEC-002 §2). CPF apenas como HMAC de lookup, único."""

    __tablename__ = "customers"
    __table_args__ = (
        sa.UniqueConstraint("cpf_hash"),
        sa.CheckConstraint("status IN ('ACTIVE', 'BLOCKED', 'INACTIVE')", name="status_valid"),
        sa.CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(sa.Text())
    cpf_hash: Mapped[str] = mapped_column(sa.Text())
    status: Mapped[str] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))


class SessionModel(Base):
    """Sessão conversacional (SPEC-002 §2)."""

    __tablename__ = "sessions"
    __table_args__ = (
        # Sessão autenticada sem customer é fisicamente impossível.
        sa.CheckConstraint(
            "(NOT authenticated) OR customer_id IS NOT NULL",
            name="authenticated_has_customer",
        ),
        sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        sa.Index("ix_sessions_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("customers.id"))
    authenticated: Mapped[bool] = mapped_column(sa.Boolean(), default=False)
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))


class AuthChallengeModel(Base):
    """Desafio de OTP (SPEC-002 §2, §4)."""

    __tablename__ = "auth_challenges"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('PENDING', 'VERIFIED', 'EXPIRED', 'BLOCKED')",
            name="status_valid",
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.CheckConstraint("attempts <= max_attempts", name="attempts_within_max"),
        sa.CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        # No máximo um desafio PENDING por sessão: última defesa de
        # integridade — a serialização normal vem do lock da sessão na
        # aplicação, não deste índice.
        sa.Index(
            "uq_auth_challenges_pending_session",
            "session_id",
            unique=True,
            postgresql_where=sa.text("status = 'PENDING'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("customers.id"))
    session_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("sessions.id"))
    otp_hash: Mapped[str] = mapped_column(sa.Text())
    expires_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    attempts: Mapped[int] = mapped_column(sa.Integer(), default=0)
    max_attempts: Mapped[int] = mapped_column(sa.Integer())
    status: Mapped[str] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
