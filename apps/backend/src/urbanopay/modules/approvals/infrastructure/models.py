"""Modelo ORM do módulo approvals (SPEC-003 §7; ADR-012).

Invariantes garantidas pelo banco:

- **uma** aprovação por Order: `UNIQUE (order_id)`. O MVP não prevê reabertura
  de aprovação, e sem essa constraint duas confirmações concorrentes poderiam
  criar dois pedidos de decisão para o mesmo Order;
- domínio fechado de `status`;
- coerência de auditoria: `PENDING` não tem decisão registrada, e todo estado
  terminal tem **ator e instante** (§7).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from urbanopay.db.base import Base


class ApprovalModel(Base):
    """Pedido de aprovação humana de um Order (SPEC-003 §7)."""

    __tablename__ = "approvals"
    __table_args__ = (
        sa.UniqueConstraint("order_id"),
        sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="status_valid"),
        sa.CheckConstraint(
            "(status = 'PENDING' AND decided_at IS NULL AND decided_by IS NULL)"
            " OR (status <> 'PENDING' AND decided_at IS NOT NULL AND decided_by IS NOT NULL)",
            name="decision_audit_complete",
        ),
        sa.Index("ix_approvals_status_requested_at", "status", "requested_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("orders.id"))
    status: Mapped[str] = mapped_column(sa.Text())
    requested_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True))
    # Identificador opaco de operador. Nunca nome, e-mail ou CPF.
    decided_by: Mapped[str | None] = mapped_column(sa.Text())
