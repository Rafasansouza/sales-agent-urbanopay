"""Máquina de estados do Order (SPEC-003 §14).

Funções puras: recebem um `Order`, devolvem um `Order` novo. Nenhuma faz I/O,
nenhuma consulta configuração, nenhuma depende de relógio implícito — o
instante é sempre parâmetro.

Duas camadas de garantia, deliberadamente redundantes:

1. `_ALLOWED_TRANSITIONS` descreve o grafo da §14 e nada além dele;
2. cada função de transição expressa **quem** pode dispará-la.

A segunda camada existe porque o grafo, sozinho, não distingue
`DRAFT → CANCELLED` (pedido do cliente) de `REQUIRES_APPROVAL → CANCELLED`
(rejeição de aprovação). Sem ela, uma tool de cancelamento poderia cancelar um
Order aguardando aprovação e registrar o motivo errado.
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from urbanopay.modules.orders.domain.enums import CancellationReason, OrderStatus
from urbanopay.modules.orders.domain.errors import (
    InvalidOrderStateError,
    InvalidOrderStateTransitionError,
    OrderAlreadyPaidError,
    OrderRequiresApprovalError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from urbanopay.modules.orders.domain.entities import Order

# Grafo exato da SPEC-003 §14. `PAID → FULFILLING → COMPLETED |
# FULFILLMENT_FAILED` é documentado aqui porque pertence à máquina, mas é
# executado pela SPEC-005.
_ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.DRAFT: frozenset(
        {
            OrderStatus.CONFIRMED,
            OrderStatus.REQUIRES_APPROVAL,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.REQUIRES_APPROVAL: frozenset({OrderStatus.CONFIRMED, OrderStatus.CANCELLED}),
    OrderStatus.CONFIRMED: frozenset({OrderStatus.PAYMENT_PENDING}),
    OrderStatus.PAYMENT_PENDING: frozenset({OrderStatus.PAID, OrderStatus.CONFIRMED}),
    OrderStatus.PAID: frozenset({OrderStatus.FULFILLING}),
    OrderStatus.FULFILLING: frozenset({OrderStatus.COMPLETED, OrderStatus.FULFILLMENT_FAILED}),
    OrderStatus.COMPLETED: frozenset(),
    # Reentrada por comando explícito (SPEC-003 §14, SPEC-005 §5.1): um
    # fulfillment em FAILED ou RECONCILIATION_REQUIRED deixa o Order aqui, e
    # sem esta aresta um cartão reativado nunca receberia o crédito de um
    # Order já pago. Nunca automática, nunca gera nova cobrança.
    OrderStatus.FULFILLMENT_FAILED: frozenset({OrderStatus.FULFILLING}),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}

# Visão pública somente-leitura do grafo. Existe para que o teste de
# alcançabilidade percorra exatamente a mesma estrutura que as transições
# usam — um grafo duplicado no teste poderia divergir do de produção.
ALLOWED_TRANSITIONS: Mapping[OrderStatus, frozenset[OrderStatus]] = MappingProxyType(
    _ALLOWED_TRANSITIONS
)

# Estados sem saída na §14. `PAID` NÃO é terminal (segue para fulfillment),
# mas é irreversível: reembolso está fora do escopo do MVP.
TERMINAL_STATUSES = frozenset(
    status for status, targets in _ALLOWED_TRANSITIONS.items() if not targets
)


def is_transition_allowed(current: OrderStatus, target: OrderStatus) -> bool:
    """Consulta o grafo da §14, sem efeito colateral."""
    return target in _ALLOWED_TRANSITIONS[current]


def ensure_transition_allowed(current: OrderStatus, target: OrderStatus) -> None:
    """Recusa transição fora do grafo com `INVALID_ORDER_STATE_TRANSITION`."""
    if not is_transition_allowed(current, target):
        raise InvalidOrderStateTransitionError


def _transition(
    order: Order,
    target: OrderStatus,
    at: datetime,
    *,
    cancellation_reason: CancellationReason | None = None,
) -> Order:
    ensure_transition_allowed(order.status, target)
    return replace(
        order,
        status=target,
        cancellation_reason=cancellation_reason or order.cancellation_reason,
        updated_at=at,
    )


def confirm(order: Order, at: datetime) -> Order:
    """Confirmação explícita do cliente (§8) — sempre a partir de `DRAFT`.

    É o **primeiro** dos consentimentos necessários. O destino depende de
    `requires_approval`, congelado na criação:

    - `false` ⇒ `CONFIRMED` (elegível para Payment);
    - `true`  ⇒ `REQUIRES_APPROVAL` (aguardando decisão humana).

    `DRAFT` expirado não é confirmável (`ORDER_EXPIRED`, §5.1). A verificação
    de expiração vem antes da de estado para que um Order expirado produza
    `ORDER_EXPIRED`, e não `INVALID_ORDER_STATE`.
    """
    order.ensure_not_expired(at)
    if order.status is not OrderStatus.DRAFT:
        raise InvalidOrderStateError
    target = OrderStatus.REQUIRES_APPROVAL if order.requires_approval else OrderStatus.CONFIRMED
    return _transition(order, target, at)


def cancel_by_customer(order: Order, at: datetime) -> Order:
    """Cancelamento pelo cliente — **somente** em `DRAFT` (§14).

    `REQUIRES_APPROVAL`, `CONFIRMED`, `PAYMENT_PENDING` e `PAID` não admitem
    cancelamento pelo cliente no MVP. Em `PAID` o erro é `ORDER_ALREADY_PAID`,
    mais informativo que uma transição inválida genérica.
    """
    if order.status is OrderStatus.PAID:
        raise OrderAlreadyPaidError
    if order.status is not OrderStatus.DRAFT:
        raise InvalidOrderStateError
    return _transition(
        order,
        OrderStatus.CANCELLED,
        at,
        cancellation_reason=CancellationReason.CUSTOMER_REQUEST,
    )


def expire(order: Order, at: datetime) -> Order:
    """Expiração por TTL — aplicável **somente** a `DRAFT` (§5.1)."""
    if order.status is not OrderStatus.DRAFT:
        raise InvalidOrderStateError
    return _transition(order, OrderStatus.EXPIRED, at)


def apply_approval_granted(order: Order, at: datetime) -> Order:
    """`Approval APPROVED` ⇒ `REQUIRES_APPROVAL → CONFIRMED` (§7)."""
    if order.status is not OrderStatus.REQUIRES_APPROVAL:
        raise InvalidOrderStateError
    return _transition(order, OrderStatus.CONFIRMED, at)


def apply_approval_rejected(order: Order, at: datetime) -> Order:
    """`Approval REJECTED` ⇒ `REQUIRES_APPROVAL → CANCELLED` (§7).

    O motivo é registrado como `APPROVAL_REJECTED`: a rejeição administrativa
    nunca é apresentada como cancelamento solicitado pelo cliente.
    """
    if order.status is not OrderStatus.REQUIRES_APPROVAL:
        raise InvalidOrderStateError
    return _transition(
        order,
        OrderStatus.CANCELLED,
        at,
        cancellation_reason=CancellationReason.APPROVAL_REJECTED,
    )


def start_payment(order: Order, at: datetime) -> Order:
    """`CONFIRMED → PAYMENT_PENDING` na criação do Payment (§14).

    `CONFIRMED` é o **único** estado pagável. Um Order já pago produz
    `ORDER_ALREADY_PAID`; um Order aguardando decisão humana produz
    `ORDER_REQUIRES_APPROVAL` — ambos mais precisos que transição inválida.
    """
    if order.status is OrderStatus.PAID:
        raise OrderAlreadyPaidError
    if order.status is OrderStatus.REQUIRES_APPROVAL:
        raise OrderRequiresApprovalError
    if order.status is not OrderStatus.CONFIRMED:
        raise InvalidOrderStateError
    return _transition(order, OrderStatus.PAYMENT_PENDING, at)


def mark_paid(order: Order, at: datetime) -> Order:
    """`PAYMENT_PENDING → PAID` (§14).

    Alcançável **exclusivamente** a partir de um `Payment APPROVED`
    estabelecido pelo provider ou pelo backend. Nenhuma tool e nenhuma
    mensagem de usuário chega aqui: quem chama é o aplicador de estado de
    pagamento.

    Idempotente por conveniência do aplicador: um Order já `PAID` é devolvido
    inalterado, porque webhook e polling convergem no mesmo ponto e podem
    entregar o mesmo fato duas vezes (§12).
    """
    if order.status is OrderStatus.PAID:
        return order
    if order.status is not OrderStatus.PAYMENT_PENDING:
        raise InvalidOrderStateError
    return _transition(order, OrderStatus.PAID, at)


def start_fulfillment(order: Order, at: datetime) -> Order:
    """`PAID → FULFILLING` no início do fulfillment (SPEC-005 §5.2).

    Em `RECHARGE` esta transição e as seguintes ocorrem na **mesma
    transação**, então `FULFILLING` não é observável de fora. Ainda assim ela
    existe: o grafo da §14 não admite `PAID → COMPLETED` direto, e criar esse
    atalho exigiria alterar a máquina de estados aceita.

    Aceita também `FULFILLMENT_FAILED` como origem: é a reentrada por comando
    explícito prevista em SPEC-005 §5.1.

    Idempotente: um Order já em `FULFILLING` é devolvido inalterado, para que
    uma reentrada não precise distinguir os dois casos.
    """
    if order.status is OrderStatus.FULFILLING:
        return order
    if order.status not in (OrderStatus.PAID, OrderStatus.FULFILLMENT_FAILED):
        raise InvalidOrderStateError
    return _transition(order, OrderStatus.FULFILLING, at)


def complete_fulfillment(order: Order, at: datetime) -> Order:
    """`FULFILLING → COMPLETED` (SPEC-005 §5.2).

    Encerra a jornada do Order. Alcançável **exclusivamente** a partir de um
    `Fulfillment COMPLETED`, isto é, de um efeito comercial já aplicado e
    registrado em ledger na mesma transação.

    Idempotente: webhook e reentrada podem entregar o mesmo fato duas vezes.
    """
    if order.status is OrderStatus.COMPLETED:
        return order
    if order.status is not OrderStatus.FULFILLING:
        raise InvalidOrderStateError
    return _transition(order, OrderStatus.COMPLETED, at)


def fail_fulfillment(order: Order, at: datetime) -> Order:
    """`FULFILLING → FULFILLMENT_FAILED` (SPEC-005 §5.2).

    Cobre tanto `Fulfillment FAILED` quanto `RECONCILIATION_REQUIRED`: o Order
    guarda apenas o estado coarse-grained da jornada, e a distinção fina fica
    no Fulfillment, que é a autoridade detalhada.

    **Não** gera nova cobrança e **não** reverte o pagamento: o Payment
    permanece aprovado (SPEC-003 §15).
    """
    if order.status is OrderStatus.FULFILLMENT_FAILED:
        return order
    if order.status is not OrderStatus.FULFILLING:
        raise InvalidOrderStateError
    return _transition(order, OrderStatus.FULFILLMENT_FAILED, at)


def release_for_new_attempt(order: Order, at: datetime) -> Order:
    """`PAYMENT_PENDING → CONFIRMED` após terminal não aprovado (§13.2).

    Habilita **nova tentativa comercial**, que exigirá novo `payment_id` e
    nova idempotency key. Não é retry técnico: retry técnico reusa o mesmo
    Payment e a mesma key, sem passar por aqui (§13.1).

    Idempotente pelo mesmo motivo de `mark_paid`: se o Order já voltou a
    `CONFIRMED`, um segundo evento terminal do mesmo Payment não é erro.
    """
    if order.status is OrderStatus.CONFIRMED:
        return order
    if order.status is OrderStatus.PAID:
        raise OrderAlreadyPaidError
    if order.status is not OrderStatus.PAYMENT_PENDING:
        raise InvalidOrderStateError
    return _transition(order, OrderStatus.CONFIRMED, at)
