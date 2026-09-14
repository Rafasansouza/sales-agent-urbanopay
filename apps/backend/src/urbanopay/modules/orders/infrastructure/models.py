"""Modelos ORM do módulo orders (SPEC-003 §4, §5; ADR-012).

Modelos de **persistência**, não de domínio: nenhuma regra de negócio,
nenhum arredondamento. `Numeric(12, 2, asdecimal=True)` apenas armazena.

As invariantes que o banco pode garantir estão aqui como constraints, e não
apenas em código — é o que sobrevive a um bug de aplicação:

- coerência aritmética `total = subtotal - discount_amount`;
- `orders.quote_id` **único**: uma Quote produz no máximo um Order, para que
  um único consentimento de valor não gere dois pedidos pagáveis;
- motivo de cancelamento existe **somente** em Order cancelado;
- domínio fechado de `status`, `operation_type` e `currency`.

O limiar de aprovação **não** é constraint de banco por decisão: a SPEC-003 §7
exige que ele viva encapsulado em `ApprovalPolicy`. Replicá-lo em `CHECK`
criaria uma segunda fonte da mesma regra, que passaria a divergir na primeira
alteração de política.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from urbanopay.db.base import Base

_OPERATION_TYPES = "'RECHARGE', 'TICKET_PURCHASE'"
_ORDER_STATUSES = (
    "'DRAFT', 'REQUIRES_APPROVAL', 'CONFIRMED', 'PAYMENT_PENDING', 'PAID', "
    "'FULFILLING', 'COMPLETED', 'FULFILLMENT_FAILED', 'CANCELLED', 'EXPIRED'"
)
_CANCELLATION_REASONS = "'CUSTOMER_REQUEST', 'APPROVAL_REJECTED'"


class QuoteModel(Base):
    """Orçamento (SPEC-003 §4).

    **Sem coluna de status**, por decisão documentada: a validade é derivada
    de `expires_at` e o consumo é o fato relacional de existir um Order que a
    referencia. Uma coluna de status seria uma segunda verdade a manter
    sincronizada com esses dois fatos.
    """

    __tablename__ = "quotes"
    __table_args__ = (
        sa.CheckConstraint(f"operation_type IN ({_OPERATION_TYPES})", name="operation_valid"),
        sa.CheckConstraint("currency = 'BRL'", name="currency_valid"),
        sa.CheckConstraint("subtotal >= 0", name="subtotal_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
        sa.CheckConstraint("total >= 0", name="total_non_negative"),
        sa.CheckConstraint("discount_amount <= subtotal", name="discount_within_subtotal"),
        sa.CheckConstraint("total = subtotal - discount_amount", name="total_matches_parts"),
        sa.Index("ix_quotes_customer_id", "customer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("customers.id"))
    card_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cards.id"))
    operation_type: Mapped[str] = mapped_column(sa.Text())
    # Snapshot de auditoria do perfil oficial vigente (§1.1), não insumo de
    # cálculo. Texto livre para não acoplar o histórico ao enum de `cards`.
    fare_profile: Mapped[str] = mapped_column(sa.Text())
    subtotal: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    discount_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    total: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    currency: Mapped[str] = mapped_column(sa.Text())
    expires_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))


class QuoteItemModel(Base):
    """Item congelado de um orçamento (§4).

    Snapshot mínimo: sem chave estrangeira para catálogo e sem `product_code`
    arbitrário — catálogo de produtos não possui especificação (A-05), e em
    `RECHARGE` o `operation_type` já identifica a operação.
    """

    __tablename__ = "quote_items"
    __table_args__ = (
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("unit_amount >= 0", name="unit_amount_non_negative"),
        sa.CheckConstraint("total_amount = unit_amount * quantity", name="total_matches_quantity"),
        sa.Index("ix_quote_items_quote_id", "quote_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    quote_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("quotes.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(sa.Text())
    quantity: Mapped[int] = mapped_column(sa.Integer())
    unit_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    total_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))


class OrderModel(Base):
    """Pedido (SPEC-003 §5, §6)."""

    __tablename__ = "orders"
    __table_args__ = (
        # Uma Quote gera no máximo um Order (§4).
        sa.UniqueConstraint("quote_id"),
        sa.CheckConstraint(f"operation_type IN ({_OPERATION_TYPES})", name="operation_valid"),
        sa.CheckConstraint(f"status IN ({_ORDER_STATUSES})", name="status_valid"),
        sa.CheckConstraint("currency = 'BRL'", name="currency_valid"),
        sa.CheckConstraint("subtotal >= 0", name="subtotal_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
        sa.CheckConstraint("total >= 0", name="total_non_negative"),
        sa.CheckConstraint("discount_amount <= subtotal", name="discount_within_subtotal"),
        sa.CheckConstraint("total = subtotal - discount_amount", name="total_matches_parts"),
        sa.CheckConstraint(
            f"cancellation_reason IS NULL OR cancellation_reason IN ({_CANCELLATION_REASONS})",
            name="cancellation_reason_valid",
        ),
        # Motivo de cancelamento só existe em Order cancelado. Evita que a
        # rejeição de aprovação apareça em Order que seguiu adiante.
        sa.CheckConstraint(
            "cancellation_reason IS NULL OR status = 'CANCELLED'",
            name="cancellation_reason_requires_cancelled",
        ),
        sa.Index("ix_orders_customer_id", "customer_id"),
        # Suporta a rotina de expiração de DRAFT (§5.1).
        sa.Index("ix_orders_status_expires_at", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("customers.id"))
    card_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cards.id"))
    quote_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("quotes.id"))
    operation_type: Mapped[str] = mapped_column(sa.Text())
    status: Mapped[str] = mapped_column(sa.Text())
    subtotal: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    discount_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    total: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    currency: Mapped[str] = mapped_column(sa.Text())
    requires_approval: Mapped[bool] = mapped_column(sa.Boolean())
    expires_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))


class OrderItemModel(Base):
    """Item congelado de um pedido (§5). Nunca atualizado após a criação."""

    __tablename__ = "order_items"
    __table_args__ = (
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("unit_amount >= 0", name="unit_amount_non_negative"),
        sa.CheckConstraint("total_amount = unit_amount * quantity", name="total_matches_quantity"),
        sa.Index("ix_order_items_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("orders.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(sa.Text())
    quantity: Mapped[int] = mapped_column(sa.Integer())
    unit_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    total_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
