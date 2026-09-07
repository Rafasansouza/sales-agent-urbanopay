"""Modelos ORM do módulo fulfillment (SPEC-005 §7.1, §13.1; ADR-012).

Modelos de **persistência**: nenhuma regra de negócio, nenhum arredondamento.
`Numeric(12, 2, asdecimal=True)` apenas armazena.

A constraint mais importante do módulo é
`uq_card_ledger_entries_recharge_per_order`: **um crédito de recarga por
Order**. Ela é a barreira que sobrevive a um defeito da aplicação — mesmo que
o serviço perca o lock, perca a verificação de idempotência e tente creditar
duas vezes, o banco recusa.

`Order COMPLETED ⇔ existe ledger` cruza tabelas e não é expressável em
`CHECK`: fica garantida pelo serviço e coberta por teste, com consulta de
consistência dedicada (§12.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from urbanopay.db.base import Base

_FULFILLMENT_STATUSES = "'PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'RECONCILIATION_REQUIRED'"
_FULFILLMENT_TYPES = "'RECHARGE', 'TICKET_ISSUANCE'"
_FAILURE_CLASSES = "'RETRYABLE', 'NON_RETRYABLE', 'UNKNOWN_OUTCOME'"
_TERMINAL_FAILURE_STATUSES = "'FAILED', 'RECONCILIATION_REQUIRED'"
_OPERATION_TYPES = "'RECHARGE', 'TICKET_PURCHASE'"


class FulfillmentModel(Base):
    """Execução da entrega de um Order pago (SPEC-005 §5)."""

    __tablename__ = "fulfillments"
    __table_args__ = (
        # Um fulfillment por Order. Revisitar quando `TICKET_ISSUANCE` existir:
        # bilhete admite N por Order, conforme `quantity` do OrderItem (§9).
        sa.UniqueConstraint("order_id"),
        sa.CheckConstraint(f"status IN ({_FULFILLMENT_STATUSES})", name="status_valid"),
        sa.CheckConstraint(f"fulfillment_type IN ({_FULFILLMENT_TYPES})", name="type_valid"),
        sa.CheckConstraint(
            f"failure_class IS NULL OR failure_class IN ({_FAILURE_CLASSES})",
            name="failure_class_valid",
        ),
        # `completed_at` existe se e somente se o estado é COMPLETED.
        sa.CheckConstraint(
            "(status = 'COMPLETED' AND completed_at IS NOT NULL)"
            " OR (status <> 'COMPLETED' AND completed_at IS NULL)",
            name="completed_at_matches_status",
        ),
        # Metadados de falha só existem em estado de falha, e nesses estados
        # existem os dois: motivo sem classe (ou o inverso) é registro pela
        # metade numa trilha de auditoria financeira.
        sa.CheckConstraint(
            f"(status IN ({_TERMINAL_FAILURE_STATUSES})"
            " AND failure_reason IS NOT NULL AND failure_class IS NOT NULL)"
            f" OR (status NOT IN ({_TERMINAL_FAILURE_STATUSES})"
            " AND failure_reason IS NULL AND failure_class IS NULL)",
            name="failure_metadata_matches_status",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="updated_after_created"),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="completed_after_created",
        ),
        sa.Index("ix_fulfillments_status", "status"),
        sa.Index("ix_fulfillments_card_id", "card_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("orders.id"))
    # Nulo enquanto o Payment aprovado não foi resolvido — o caso de
    # inconsistência da §11.1, em que o Order está PAID sem Payment APPROVED.
    payment_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("payments.id"))
    card_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cards.id"))
    fulfillment_type: Mapped[str] = mapped_column(sa.Text())
    status: Mapped[str] = mapped_column(sa.Text())
    failure_reason: Mapped[str | None] = mapped_column(sa.Text())
    failure_class: Mapped[str | None] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True))


class CardLedgerEntryModel(Base):
    """Movimento de saldo do cartão (SPEC-005 §7.1). **Imutável.**

    No recorte `RECHARGE` esta tabela é também a materialização da
    `RechargeTransaction` conceitual da §4 (decisão A-16) — daí `balance_before`
    e `balance_after` viverem aqui.
    """

    __tablename__ = "card_ledger_entries"
    __table_args__ = (
        # ⬇ A invariante central da SPEC-005: um efeito financeiro por Order.
        sa.Index(
            "uq_card_ledger_entries_recharge_per_order",
            "order_id",
            unique=True,
            postgresql_where=sa.text("entry_type = 'RECHARGE_CREDIT'"),
        ),
        sa.CheckConstraint("entry_type IN ('RECHARGE_CREDIT')", name="entry_type_valid"),
        sa.CheckConstraint("currency = 'BRL'", name="currency_valid"),
        sa.CheckConstraint("amount > 0", name="amount_positive"),
        sa.CheckConstraint("balance_before >= 0", name="balance_before_non_negative"),
        sa.CheckConstraint("balance_after >= 0", name="balance_after_non_negative"),
        # Aritmética exata do crédito, verificada pelo banco.
        sa.CheckConstraint("balance_after = balance_before + amount", name="balance_arithmetic"),
        sa.Index("ix_card_ledger_entries_card_id", "card_id"),
        sa.Index("ix_card_ledger_entries_fulfillment_id", "fulfillment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    fulfillment_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("fulfillments.id"))
    order_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("orders.id"))
    card_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("cards.id"))
    entry_type: Mapped[str] = mapped_column(sa.Text())
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    currency: Mapped[str] = mapped_column(sa.Text())
    balance_before: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    balance_after: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))


class ReceiptModel(Base):
    """Comprovante simulado (SPEC-005 §13.1).

    Minimização: `card_last4` e valores. Nenhum CPF, nome, e-mail ou payload
    de provider. O número completo do cartão não existe no sistema (SPEC-002).
    """

    __tablename__ = "receipts"
    __table_args__ = (
        sa.UniqueConstraint("order_id"),
        sa.UniqueConstraint("fulfillment_id"),
        sa.CheckConstraint("document_kind IN ('SIMULATED_NON_FISCAL')", name="document_kind_valid"),
        sa.CheckConstraint(f"operation_type IN ({_OPERATION_TYPES})", name="operation_valid"),
        sa.CheckConstraint("currency = 'BRL'", name="currency_valid"),
        sa.CheckConstraint("amount > 0", name="amount_positive"),
        sa.CheckConstraint("card_last4 ~ '^[0-9]{4}$'", name="last4_format"),
        sa.CheckConstraint("btrim(disclaimer_version) <> ''", name="disclaimer_version_present"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("orders.id"))
    # Não nulo: o comprovante existe somente no sucesso, e sucesso exige
    # Payment aprovado.
    payment_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("payments.id"))
    fulfillment_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("fulfillments.id"))
    card_last4: Mapped[str] = mapped_column(sa.Text())
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    currency: Mapped[str] = mapped_column(sa.Text())
    operation_type: Mapped[str] = mapped_column(sa.Text())
    document_kind: Mapped[str] = mapped_column(sa.Text())
    # Persistida para que o documento histórico continue explicitamente não
    # fiscal mesmo que a redação do aviso mude (§13.1).
    disclaimer_version: Mapped[str] = mapped_column(sa.Text())
    issued_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
