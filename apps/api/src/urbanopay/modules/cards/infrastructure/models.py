"""Modelo ORM do módulo cards (SPEC-002 §2; ADR-012).

Minimização aprovada: não existe coluna de número completo — apenas
`card_last4` para apresentação mascarada. A identidade oficial é o UUID.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from urbanopay.db.base import Base


class CardModel(Base):
    """Cartão de transporte (SPEC-002 §2)."""

    __tablename__ = "cards"
    __table_args__ = (
        sa.CheckConstraint("fare_profile IN ('INTEGRAL', 'MEIA')", name="profile_valid"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'BLOCKED', 'EXPIRED', 'CANCELLED')", name="status_valid"
        ),
        sa.CheckConstraint("card_last4 ~ '^[0-9]{4}$'", name="last4_format"),
        # Aprovada no plano (ponto aberto do ADR-012): o MVP apenas credita;
        # se débito for especificado, a constraint é revisitada por decisão
        # documental.
        sa.CheckConstraint("balance >= 0", name="balance_non_negative"),
        sa.Index("ix_cards_customer_id", "customer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("customers.id"))
    card_last4: Mapped[str] = mapped_column(sa.Text())
    fare_profile: Mapped[str] = mapped_column(sa.Text())
    balance: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    status: Mapped[str] = mapped_column(sa.Text())
    # Informativo: `status` é a única autoridade operacional (ver docstring de
    # Card no domínio). Nenhuma regra funcional deriva desta coluna.
    expires_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
