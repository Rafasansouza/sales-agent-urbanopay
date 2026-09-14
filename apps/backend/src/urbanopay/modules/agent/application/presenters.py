"""Conversão de entidade de domínio em dados de envelope (SPEC-004 §21).

Este é o **único** ponto por onde dado de domínio atravessa para o lado do
modelo, e por isso é onde a minimização deixa de ser recomendação e vira
código. Funções puras, sem I/O: dá para provar por teste que nenhum campo
proibido sai daqui.

Nunca atravessam: entidade ou dataclass de domínio inteira, objeto ORM, CPF,
OTP, hash, idempotency key, `provider_payment_id`, payload de provider,
`decided_by` de aprovação, credencial ou stack trace.

Regras de serialização (ADR-006): valor monetário em **string decimal**,
instante em ISO 8601, identificador em string opaca.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

    from urbanopay.modules.agent.domain.results import JsonValue, ToolData
    from urbanopay.modules.approvals.domain.results import ApprovalDecision
    from urbanopay.modules.cards.domain.entities import Card
    from urbanopay.modules.fare.domain.value_objects import FareCalculation
    from urbanopay.modules.fulfillment.domain.entities import Fulfillment, Receipt
    from urbanopay.modules.identity.domain.results import (
        AuthenticationStatus,
        StartAuthenticationResult,
        VerificationResult,
    )
    from urbanopay.modules.orders.domain.entities import Order, Quote
    from urbanopay.modules.payments.domain.entities import Payment
    from urbanopay.modules.payments.domain.results import (
        OrderPaymentStatus,
        PaymentCreationResult,
    )

_CENTS = Decimal("0.01")


def money(value: Decimal) -> str:
    """Valor monetário como string decimal de duas casas.

    O `quantize` **não é uma decisão de arredondamento**: os valores que
    chegam aqui já vêm com duas casas por construção — `NUMERIC(12,2)` no
    banco, validação de domínio na entrada e `ROUND_HALF_UP` já aplicado pelo
    Fare Engine. Ele apenas normaliza a escala textual, para que `21.5` e
    `21.50` não produzam duas representações do mesmo valor.
    """
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


def instant(value: datetime) -> str:
    """Instante em ISO 8601 (ADR-006)."""
    return value.isoformat()


def opaque(value: UUID) -> str:
    """Identificador como string opaca (ADR-006)."""
    return str(value)


def _optional_instant(value: datetime | None) -> str | None:
    return instant(value) if value is not None else None


def _optional_opaque(value: UUID | None) -> str | None:
    return opaque(value) if value is not None else None


# --- fare (SPEC-001) ---------------------------------------------------------


def fare_calculation(
    calculation: FareCalculation, *, profile_source: str, profile_verified: bool
) -> ToolData:
    """Breakdown tarifário oficial.

    `profile_source` e `profile_verified` viajam junto porque a diferença
    entre perfil declarado e perfil do cartão é justamente o que o cliente não
    pode decidir (SPEC-002 §8): o resultado precisa dizer de onde veio o
    perfil que produziu aquele número.

    `fare_id` e `rule_id` ficam de fora: são referências de auditoria interna,
    e o modelo não tem o que fazer com elas.
    """
    segments: list[JsonValue] = [
        {
            "mode": segment.mode.value,
            "line_code": segment.line_code,
            "fare_amount": money(segment.fare_amount),
        }
        for segment in calculation.segments
    ]
    data: dict[str, JsonValue] = {
        "fare_profile": calculation.fare_profile.value,
        "profile_source": profile_source,
        "profile_verified": profile_verified,
        "trip_type": calculation.trip_type.value,
        "segments": segments,
        "subtotal": money(calculation.subtotal),
        "total": money(calculation.total),
        "currency": calculation.currency,
        "discount": None,
    }
    if calculation.discount is not None:
        data["discount"] = {
            "type": calculation.discount.type.value,
            "percentage": money(calculation.discount.percentage),
            "amount": money(calculation.discount.amount),
        }
    return data


# --- identity (SPEC-002) -----------------------------------------------------


def start_authentication(result: StartAuthenticationResult) -> ToolData:
    """Resultado da identificação.

    `challenge_id` **não** sai: o desafio pertence à sessão e é resolvido
    server-side por `verify_otp`. Expor o identificador não habilitaria nada e
    ampliaria a superfície.
    """
    return {
        "identification_status": result.status.value,
        "challenge_expires_at": _optional_instant(result.challenge_expires_at),
    }


def verification(result: VerificationResult) -> ToolData:
    """Resultado da verificação de OTP.

    Nem o OTP nem o `customer_id` saem daqui: o primeiro nunca é exposto
    (SPEC-002 §4), e o segundo é derivado da sessão a cada operação, não
    transportado pela conversa.
    """
    return {
        "verification_status": result.status.value,
        "authenticated": result.status.value == "AUTHENTICATED",
        "attempts_remaining": result.attempts_remaining,
    }


def authentication_status(status: AuthenticationStatus) -> ToolData:
    return {
        "authenticated": status.authenticated,
        "expires_at": instant(status.expires_at),
    }


# --- cards (SPEC-002) --------------------------------------------------------


def card(entity: Card) -> ToolData:
    """Cartão sem saldo.

    Saldo é dado sensível (SPEC-002 §12) e tem tool própria: incluí-lo aqui
    faria toda listagem carregar informação que a maioria das conversas não
    pede. O número completo não existe no sistema — só `masked_number`.
    """
    return {
        "card_id": opaque(entity.id),
        "masked_number": entity.masked_number,
        "fare_profile": entity.fare_profile.value,
        "status": entity.status.value,
    }


def card_list(entities: Sequence[Card]) -> ToolData:
    cards: list[JsonValue] = [dict(card(entity)) for entity in entities]
    return {"cards": cards, "count": len(cards)}


def card_balance(entity: Card, balance: Decimal) -> ToolData:
    return {
        "card_id": opaque(entity.id),
        "masked_number": entity.masked_number,
        "balance": money(balance),
        "currency": "BRL",
    }


# --- orders e approvals (SPEC-003) -------------------------------------------


def quote(entity: Quote, *, profile_signal: str | None) -> ToolData:
    """Orçamento.

    `profile_signal` carrega `FARE_PROFILE_CHANGED` quando o perfil declarado
    divergiu do oficial (A-11). Em `RECHARGE` a divergência não altera o valor
    — que é escolha do cliente —, mas o cliente precisa saber que o perfil
    usado é o do cartão, e não o que ele afirmou.
    """
    return {
        "quote_id": opaque(entity.id),
        "card_id": opaque(entity.card_id),
        "operation_type": entity.operation_type.value,
        "fare_profile": entity.fare_profile,
        "profile_signal": profile_signal,
        "total": money(entity.total),
        "currency": entity.currency,
        "expires_at": instant(entity.expires_at),
    }


def order(entity: Order) -> ToolData:
    """Order.

    `requires_approval` é congelado na criação (SPEC-003 §5) e viaja junto do
    status justamente para que a conversa não precise deduzir do valor se
    haverá aprovação — deduzir seria reimplementar a `ApprovalPolicy` no lado
    errado da fronteira.
    """
    return {
        "order_id": opaque(entity.id),
        "card_id": opaque(entity.card_id),
        "operation_type": entity.operation_type.value,
        "status": entity.status.value,
        "total": money(entity.total),
        "currency": entity.currency,
        "requires_approval": entity.requires_approval,
        "expires_at": instant(entity.expires_at),
        "cancellation_reason": (
            entity.cancellation_reason.value if entity.cancellation_reason is not None else None
        ),
    }


def approval(decision: ApprovalDecision) -> ToolData:
    """Estado da aprovação humana.

    `decided_by` **não** sai: o ator é identificador opaco de operador, existe
    para auditoria (SPEC-003 §7) e não tem função na conversa.
    """
    return {
        "order_id": opaque(decision.order_id),
        "requires_approval": decision.requires_approval,
        "approval_status": decision.status.value if decision.status is not None else None,
        "requested_at": _optional_instant(decision.requested_at),
        "decided_at": _optional_instant(decision.decided_at),
    }


# --- payments (SPEC-003) -----------------------------------------------------


def _payment_core(entity: Payment) -> dict[str, JsonValue]:
    """Campos comuns de um Payment.

    Ficam de fora `idempotency_key` e `provider_payment_id`: a primeira é
    mecanismo de controle que o modelo nunca deve ver nem escolher (§9.1); o
    segundo é referência externa sem uso conversacional.
    """
    return {
        "payment_id": opaque(entity.id),
        "order_id": opaque(entity.order_id),
        "status": entity.status.value,
        "method": entity.method.value,
        "amount": money(entity.amount),
        "currency": entity.currency,
    }


def payment_creation(result: PaymentCreationResult) -> ToolData:
    """Cobrança criada.

    `qr_code` é o único dado transitório de provider que atravessa: ele existe
    para ser apresentado ao cliente. Nunca é persistido e nunca é registrado
    em log.
    """
    data = _payment_core(result.payment)
    data["qr_code"] = result.qr_code
    data["already_existed"] = result.already_existed
    return data


def payment_status(status: OrderPaymentStatus) -> ToolData:
    """Situação de pagamento de um Order.

    `latest is None` significa que nenhuma cobrança foi criada — estado
    perfeitamente normal de um Order recém-confirmado, e distinto de erro.
    """
    if status.latest is None:
        return {
            "order_id": opaque(status.order_id),
            "payment_id": None,
            "status": None,
            "has_active_attempt": False,
        }
    data = _payment_core(status.latest)
    data["has_active_attempt"] = status.has_active_attempt
    return data


# --- fulfillment e pós-venda (SPEC-005) --------------------------------------


def fulfillment(entity: Fulfillment) -> ToolData:
    """Estado da entrega.

    `failure_reason` é um código curto e estável (`CARD_NOT_ACTIVE`,
    `ORDER_PAID_WITHOUT_APPROVED_PAYMENT`), nunca texto livre ou dado do
    cliente.
    """
    return {
        "order_id": opaque(entity.order_id),
        "fulfillment_id": opaque(entity.id),
        "fulfillment_type": entity.fulfillment_type.value,
        "status": entity.status.value,
        "failure_reason": entity.failure_reason,
        "completed_at": _optional_instant(entity.completed_at),
    }


def receipt(entity: Receipt) -> ToolData:
    """Comprovante simulado.

    `document_kind` e `disclaimer_version` viajam sempre: o documento é
    explicitamente não fiscal (SPEC-005 §13.1), e essa qualificação não pode
    depender de o modelo lembrar de dizê-la.
    """
    return {
        "receipt_id": opaque(entity.id),
        "order_id": opaque(entity.order_id),
        "fulfillment_id": opaque(entity.fulfillment_id),
        "payment_id": _optional_opaque(entity.payment_id),
        "masked_card": entity.masked_card,
        "amount": money(entity.amount),
        "currency": entity.currency,
        "operation_type": entity.operation_type,
        "document_kind": entity.document_kind.value,
        "disclaimer_version": entity.disclaimer_version,
        "issued_at": instant(entity.issued_at),
    }
