"""Entidades do domínio de fulfillment (SPEC-005 §4.1, §6, §7, §13).

Domínio puro e imutável: nenhum import de SQLAlchemy e nenhuma dependência de
outro domínio. As transições vivem em `state_machine.py`.

Dinheiro é sempre `Decimal`. Este módulo **não arredonda**: o crédito é
exatamente `order.total`, já congelado, e a aritmética do ledger é soma exata.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from urbanopay.modules.fulfillment.domain.enums import (
    DocumentKind,
    FailureClass,
    FulfillmentStatus,
    FulfillmentType,
    LedgerEntryType,
)

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class Fulfillment:
    """Execução da entrega de um Order pago (SPEC-005 §5).

    Autoridade **detalhada** do processo; o Order guarda o estado
    coarse-grained da jornada (§5.2).

    `payment_id` é registrado para auditoria: responde "qual Payment
    autorizou" sem depender de join reverso, e é derivado do Payment
    `APPROVED` do Order — nunca recebido de quem chama.
    """

    id: UUID
    order_id: UUID
    payment_id: UUID | None
    card_id: UUID
    fulfillment_type: FulfillmentType
    status: FulfillmentStatus
    failure_reason: str | None
    failure_class: FailureClass | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @property
    def is_completed(self) -> bool:
        return self.status is FulfillmentStatus.COMPLETED

    def with_status(
        self,
        status: FulfillmentStatus,
        at: datetime,
        *,
        payment_id: UUID | None = None,
        failure_reason: str | None = None,
        failure_class: FailureClass | None = None,
    ) -> Fulfillment:
        """Nova instância com o estado aplicado.

        Não valida a transição: isso é responsabilidade de
        `state_machine.transition`, o único ponto autorizado a decidir.
        """
        completed_at = at if status is FulfillmentStatus.COMPLETED else self.completed_at
        return replace(
            self,
            status=status,
            payment_id=payment_id or self.payment_id,
            failure_reason=failure_reason,
            failure_class=failure_class,
            updated_at=at,
            completed_at=completed_at,
        )


@dataclass(frozen=True, slots=True)
class CardLedgerEntry:
    """Movimento de saldo do cartão (SPEC-005 §7.1).

    **Imutável por contrato**: existe criação, não existe alteração. É a prova
    física de que um Order pago produziu no máximo um efeito financeiro — e,
    no recorte `RECHARGE`, é também a materialização da `RechargeTransaction`
    conceitual da §4 (decisão A-16), o que explica `balance_before` e
    `balance_after` viverem aqui.
    """

    id: UUID
    fulfillment_id: UUID
    order_id: UUID
    card_id: UUID
    entry_type: LedgerEntryType
    amount: Decimal
    currency: str
    balance_before: Decimal
    balance_after: Decimal
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Receipt:
    """Comprovante simulado (SPEC-005 §13.1).

    Snapshot imutável, emitido **somente** no sucesso atômico do fulfillment.

    Minimização: `card_last4` é o suficiente para apresentação mascarada — o
    número completo não existe no sistema (SPEC-002). Nenhum CPF, nome, e-mail
    ou payload de provider é persistido.

    `disclaimer_version` fica gravada para que o documento histórico continue
    explicitamente não fiscal mesmo que a redação do aviso mude.
    """

    id: UUID
    order_id: UUID
    payment_id: UUID | None
    fulfillment_id: UUID
    card_last4: str
    amount: Decimal
    currency: str
    operation_type: str
    document_kind: DocumentKind
    disclaimer_version: str
    issued_at: datetime

    @property
    def masked_card(self) -> str:
        """Apresentação mascarada no formato da SPEC-002 §6 (`****4821`)."""
        return f"****{self.card_last4}"


@dataclass(frozen=True, slots=True)
class CreditApplication:
    """Resultado puro do cálculo de crédito, antes de qualquer persistência.

    Existe para que a aritmética do saldo seja calculada e verificada em um
    único lugar do domínio, e o mesmo par `(balance_before, balance_after)`
    alimente o ledger e a atualização do cartão. Duas contas separadas
    poderiam divergir.
    """

    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal

    @classmethod
    def credit(cls, *, balance_before: Decimal, amount: Decimal) -> CreditApplication:
        """Soma exata, sem arredondamento (§7.1)."""
        return cls(
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_before + amount,
        )
