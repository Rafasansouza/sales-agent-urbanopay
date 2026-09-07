"""Máquina de estados do Fulfillment (SPEC-005 §5.1).

Funções puras: recebem um `Fulfillment`, devolvem um novo. Nenhuma faz I/O e o
instante é sempre parâmetro.

Grafo, exatamente o da §5.1:

```text
(inexistente) ──> PENDING
PENDING       ──> PROCESSING
PROCESSING   ─┬─> COMPLETED
              ├─> FAILED
              └─> RECONCILIATION_REQUIRED
FAILED                  ──> PROCESSING   (comando EXPLÍCITO)
RECONCILIATION_REQUIRED ──> PROCESSING   (comando EXPLÍCITO)
COMPLETED                                (terminal)
```

Duas decisões merecem destaque, porque parecem defeito e não são:

**`PENDING` e `PROCESSING` não são observáveis em `RECHARGE`.** As três
transições até `COMPLETED` acontecem na mesma transação. Isso é deliberado:
comitar no meio criaria uma janela em que existe fulfillment iniciado sem
efeito financeiro — exatamente o estado parcial que a SPEC proíbe. Os estados
existem com transição válida e ganham observabilidade quando houver etapa
externa.

**`COMPLETED` é terminal, inclusive diante de inconsistência.** A detecção de
um fulfillment `COMPLETED` sem ledger (§12.1) **reporta** o achado e não
transiciona: `Order COMPLETED` também é terminal em SPEC-003 §14, e regredir
estado terminal contradiz a máquina de estados aceita.

Reentrada a partir de `FAILED` ou `RECONCILIATION_REQUIRED` existe para que um
dado corrigido — um cartão reativado, por exemplo — possa ser processado por
comando explícito. Nunca por retentativa automática.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from urbanopay.modules.fulfillment.domain.enums import FailureClass, FulfillmentStatus
from urbanopay.modules.fulfillment.domain.errors import (
    EffectConflictError,
    FulfillmentError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from urbanopay.modules.fulfillment.domain.entities import Fulfillment

_ALLOWED_TRANSITIONS: dict[FulfillmentStatus, frozenset[FulfillmentStatus]] = {
    FulfillmentStatus.PENDING: frozenset({FulfillmentStatus.PROCESSING}),
    FulfillmentStatus.PROCESSING: frozenset(
        {
            FulfillmentStatus.COMPLETED,
            FulfillmentStatus.FAILED,
            FulfillmentStatus.RECONCILIATION_REQUIRED,
        }
    ),
    FulfillmentStatus.FAILED: frozenset({FulfillmentStatus.PROCESSING}),
    FulfillmentStatus.RECONCILIATION_REQUIRED: frozenset({FulfillmentStatus.PROCESSING}),
    FulfillmentStatus.COMPLETED: frozenset(),
}

# Visão pública somente-leitura: o teste de alcançabilidade percorre a mesma
# estrutura que as transições usam, para que não possam divergir.
ALLOWED_TRANSITIONS: Mapping[FulfillmentStatus, frozenset[FulfillmentStatus]] = MappingProxyType(
    _ALLOWED_TRANSITIONS
)

TERMINAL_STATUSES = frozenset({FulfillmentStatus.COMPLETED})


class InvalidFulfillmentTransitionError(FulfillmentError):
    """Transição fora do grafo da §5.1.

    Reutiliza `EFFECT_CONFLICT`, código já aprovado: uma transição inválida de
    fulfillment é sempre a tentativa de aplicar um efeito incompatível com a
    evidência persistida. Nenhum código novo é introduzido.
    """

    code = EffectConflictError.code
    default_message = "Transição de entrega inválida para este pedido."


def is_transition_allowed(current: FulfillmentStatus, target: FulfillmentStatus) -> bool:
    """Consulta o grafo da §5.1, sem efeito colateral."""
    return target in _ALLOWED_TRANSITIONS[current]


def ensure_transition_allowed(current: FulfillmentStatus, target: FulfillmentStatus) -> None:
    """Recusa transição fora do grafo."""
    if not is_transition_allowed(current, target):
        raise InvalidFulfillmentTransitionError


def start_processing(
    fulfillment: Fulfillment, at: datetime, *, payment_id: UUID | None = None
) -> Fulfillment:
    """`PENDING | FAILED | RECONCILIATION_REQUIRED → PROCESSING`.

    Limpa metadados de falha da tentativa anterior: eles descrevem o desfecho
    daquela execução, e mantê-los durante uma nova daria a impressão de que a
    atual já falhou.

    Um fulfillment já `COMPLETED` **não** volta a processar — o chamador deve
    tratar isso como replay antes de chegar aqui.
    """
    ensure_transition_allowed(fulfillment.status, FulfillmentStatus.PROCESSING)
    return fulfillment.with_status(
        FulfillmentStatus.PROCESSING,
        at,
        payment_id=payment_id,
        failure_reason=None,
        failure_class=None,
    )


def complete(fulfillment: Fulfillment, at: datetime) -> Fulfillment:
    """`PROCESSING → COMPLETED`, com `completed_at` registrado.

    Alcançável somente depois de o efeito comercial ter sido aplicado e
    registrado em ledger na mesma transação.
    """
    ensure_transition_allowed(fulfillment.status, FulfillmentStatus.COMPLETED)
    return fulfillment.with_status(FulfillmentStatus.COMPLETED, at)


def fail(
    fulfillment: Fulfillment,
    at: datetime,
    *,
    reason: str,
    failure_class: FailureClass,
) -> Fulfillment:
    """`PROCESSING → FAILED`: falha conhecida, sem efeito aplicado."""
    ensure_transition_allowed(fulfillment.status, FulfillmentStatus.FAILED)
    return fulfillment.with_status(
        FulfillmentStatus.FAILED,
        at,
        failure_reason=reason,
        failure_class=failure_class,
    )


def require_reconciliation(fulfillment: Fulfillment, at: datetime, *, reason: str) -> Fulfillment:
    """`PROCESSING → RECONCILIATION_REQUIRED`: evidência inconsistente.

    Classificada como `UNKNOWN_OUTCOME` de propósito. Os documentos aceitos
    não sustentam que um cartão `BLOCKED`, `EXPIRED` ou `CANCELLED` seja
    irreversível, então tratar o caso como falha definitiva seria decidir
    regra de negócio sem requisito. O estado fica conhecido e auditável, com
    zero efeito financeiro, aguardando decisão humana (A-18).
    """
    ensure_transition_allowed(fulfillment.status, FulfillmentStatus.RECONCILIATION_REQUIRED)
    return fulfillment.with_status(
        FulfillmentStatus.RECONCILIATION_REQUIRED,
        at,
        failure_reason=reason,
        failure_class=FailureClass.UNKNOWN_OUTCOME,
    )
