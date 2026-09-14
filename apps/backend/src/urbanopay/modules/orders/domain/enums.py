"""Enums do domínio de Orders (SPEC-003 §4, §6, §14).

Enums de `Approval` e de `Payment` vivem nos seus próprios módulos e não
colidem com `OrderStatus` (SPEC-003 §6).
"""

from __future__ import annotations

from enum import StrEnum

from urbanopay.modules.orders.domain.errors import UnsupportedOperationTypeError


class OperationType(StrEnum):
    """Tipo de operação transacional (SPEC-003 §4).

    `TICKET_PURCHASE` existe no enum porque a SPEC o define, mas **não é
    implementável no MVP**: depende de um catálogo sem especificação (A-05).
    A recusa é explícita em `OperationType.require_supported`, nunca silenciosa.
    """

    RECHARGE = "RECHARGE"
    TICKET_PURCHASE = "TICKET_PURCHASE"

    def require_supported(self) -> None:
        """Recusa explicitamente o que não é implementável no MVP (§1.1)."""
        if self is not OperationType.RECHARGE:
            raise UnsupportedOperationTypeError


class OrderStatus(StrEnum):
    """Estados do Order (SPEC-003 §6).

    Não existe `APPROVED` nem `FAILED`: ambos foram removidos por não
    possuírem caminho válido de entrada em nenhuma SPEC. A aprovação
    administrativa é `Approval.status = APPROVED`; o pagamento aprovado é
    `Payment.status = APPROVED`; o encerramento por falha é coberto por
    `CANCELLED`, `EXPIRED` e `FULFILLMENT_FAILED`.

    `FULFILLING`, `COMPLETED` e `FULFILLMENT_FAILED` são alcançados pela
    SPEC-005; esta SPEC termina em `PAID`.
    """

    DRAFT = "DRAFT"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    CONFIRMED = "CONFIRMED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    FULFILLING = "FULFILLING"
    COMPLETED = "COMPLETED"
    FULFILLMENT_FAILED = "FULFILLMENT_FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CancellationReason(StrEnum):
    """Origem do cancelamento (SPEC-003 §7, §14).

    Existe para que a rejeição de aprovação **nunca** seja apresentada como
    cancelamento solicitado pelo cliente.
    """

    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"


# Moeda única do MVP (SPEC-003 §4). Não existe operação multimoeda.
CURRENCY_BRL = "BRL"
