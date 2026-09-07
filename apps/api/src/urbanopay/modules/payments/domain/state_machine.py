"""Aplicador monotônico de estado de Payment (SPEC-003 §9, §12).

Este módulo é o **único** ponto autorizado a decidir se um estado externo pode
ser aplicado a um Payment. Webhook e consulta ativa (polling/reconciliação)
convergem aqui — é isso que garante que os dois caminhos nunca produzam
resultados diferentes para o mesmo fato (§12).

Regras, todas puras:

1. estado igual ao atual não é mudança — é repetição do mesmo fato;
2. estado terminal **nunca** regride e **nunca** é substituído por outro
   terminal: evento fora de ordem é ignorado, não aplicado;
3. `CREATED → PENDING` e `CREATED|PENDING → terminal` são as únicas
   progressões válidas. `PENDING → CREATED` é regressão e é ignorada.

Ignorar em vez de recusar com exceção é deliberado: um webhook fora de ordem é
um fato normal da integração, não um erro do sistema. Mas o caso em que o
provider reporta `APPROVED` sobre um terminal não aprovado é sinalizado para
reconciliação — ali pode existir dinheiro recebido que o nosso estado não
reflete, e silenciar isso seria perder dinheiro de vista.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from urbanopay.modules.payments.domain.enums import PaymentStatus

if TYPE_CHECKING:
    from datetime import datetime

    from urbanopay.modules.payments.domain.entities import Payment

# Progressões válidas a partir de cada estado não terminal.
_ALLOWED_TARGETS: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    PaymentStatus.CREATED: frozenset(
        {
            PaymentStatus.PENDING,
            PaymentStatus.APPROVED,
            PaymentStatus.REJECTED,
            PaymentStatus.CANCELLED,
            PaymentStatus.EXPIRED,
            PaymentStatus.FAILED,
        }
    ),
    PaymentStatus.PENDING: frozenset(
        {
            PaymentStatus.APPROVED,
            PaymentStatus.REJECTED,
            PaymentStatus.CANCELLED,
            PaymentStatus.EXPIRED,
            PaymentStatus.FAILED,
        }
    ),
}


class ApplicationOutcome(StrEnum):
    """Desfecho da tentativa de aplicar um estado externo."""

    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    IGNORED_TERMINAL = "IGNORED_TERMINAL"
    IGNORED_NOT_MONOTONIC = "IGNORED_NOT_MONOTONIC"


@dataclass(frozen=True, slots=True)
class StatusApplication:
    """Resultado da aplicação: o Payment resultante e o que aconteceu."""

    payment: Payment
    outcome: ApplicationOutcome
    reported_status: PaymentStatus

    @property
    def changed(self) -> bool:
        """`True` somente quando há novo estado a persistir e propagar."""
        return self.outcome is ApplicationOutcome.APPLIED

    @property
    def requires_reconciliation(self) -> bool:
        """`True` quando o provider afirma `APPROVED` sobre terminal não aprovado.

        Divergência que pode significar dinheiro recebido sem `Order PAID`.
        Nunca é resolvida automaticamente aplicando o `APPROVED`: a decisão
        exige reconciliação, porque o caminho inverso — aprovar por causa de um
        evento fora de ordem — é justamente o que produziria efeito financeiro
        indevido.
        """
        return (
            self.outcome is ApplicationOutcome.IGNORED_TERMINAL
            and self.reported_status is PaymentStatus.APPROVED
        )


def apply_provider_status(
    payment: Payment,
    reported_status: PaymentStatus,
    at: datetime,
    *,
    provider_payment_id: str | None = None,
) -> StatusApplication:
    """Aplica um estado reportado pelo provider, de forma monotônica."""
    learned_external_id = (
        provider_payment_id is not None and provider_payment_id != payment.provider_payment_id
    )

    if payment.status is reported_status:
        # Mesmo fato novamente. Ainda assim vale registrar o identificador
        # externo, se esta é a primeira vez que ele chega.
        if learned_external_id:
            return StatusApplication(
                payment=payment.with_status(
                    reported_status, at, provider_payment_id=provider_payment_id
                ),
                outcome=ApplicationOutcome.APPLIED,
                reported_status=reported_status,
            )
        return StatusApplication(
            payment=payment,
            outcome=ApplicationOutcome.DUPLICATE,
            reported_status=reported_status,
        )

    if payment.is_terminal:
        return StatusApplication(
            payment=payment,
            outcome=ApplicationOutcome.IGNORED_TERMINAL,
            reported_status=reported_status,
        )

    if reported_status not in _ALLOWED_TARGETS[payment.status]:
        return StatusApplication(
            payment=payment,
            outcome=ApplicationOutcome.IGNORED_NOT_MONOTONIC,
            reported_status=reported_status,
        )

    return StatusApplication(
        payment=payment.with_status(reported_status, at, provider_payment_id=provider_payment_id),
        outcome=ApplicationOutcome.APPLIED,
        reported_status=reported_status,
    )
