"""Reconciliação do contexto conversacional contra o backend (ADR-014).

> **O `ConversationState` nunca vence o backend.**

Divergência **não é erro**: é o caso esperado, porque o webhook avança o Order
enquanto a conversa dorme. Ela se resolve sempre a favor do domínio, e o estado
conversacional nunca move o domínio para trás.

Função pura, de propósito: recebe o estado e o status relido, devolve estado
novo. Nada aqui consulta banco, nada aqui escreve e nada aqui decide negócio —
o que se ajusta são **referências** ao que o backend já decidiu. Isso a torna
testável por unit test, que é o que `.claude/rules/testing.md` exige de regra
determinística.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from urbanopay_agent.domain.conversation import ConversationPhase, ConversationState
from urbanopay_domains.orders.domain.enums import OrderStatus

if TYPE_CHECKING:
    from collections.abc import Mapping

# Para onde a conversa vai quando o Order está em cada estado. O Order é a
# espinha da jornada: enquanto ele existe, é ele que diz onde estamos.
_PHASE_FOR_ORDER: Final[Mapping[OrderStatus, ConversationPhase]] = {
    OrderStatus.DRAFT: ConversationPhase.ORDER_CONFIRMATION,
    OrderStatus.REQUIRES_APPROVAL: ConversationPhase.APPROVAL,
    OrderStatus.CONFIRMED: ConversationPhase.PAYMENT,
    OrderStatus.PAYMENT_PENDING: ConversationPhase.PAYMENT,
    OrderStatus.PAID: ConversationPhase.FULFILLMENT,
    OrderStatus.FULFILLING: ConversationPhase.FULFILLMENT,
    OrderStatus.COMPLETED: ConversationPhase.POST_SALE,
    OrderStatus.FULFILLMENT_FAILED: ConversationPhase.POST_SALE,
    OrderStatus.CANCELLED: ConversationPhase.DISCOVERY,
    OrderStatus.EXPIRED: ConversationPhase.DISCOVERY,
}

# Estados em que a jornada comercial acabou: as referências de Quote, Order e
# Payment deixam de descrever algo em curso e são limpas, para que a próxima
# intenção do cliente comece limpa em vez de herdar um pedido morto.
_TERMINAL_FOR_JOURNEY: Final[frozenset[OrderStatus]] = frozenset(
    {OrderStatus.CANCELLED, OrderStatus.EXPIRED}
)


def reconcile(state: ConversationState, order_status: OrderStatus | None) -> ConversationState:
    """Alinha a conversa ao estado persistido do Order.

    `order_status is None` significa que a conversa não referencia Order algum
    — nada a reconciliar, e a fase corrente continua valendo.

    A confirmação pendente sobrevive **apenas** enquanto o Order estiver em
    `DRAFT`, que é o único estado confirmável (SPEC-003 §14). Em qualquer outro,
    ela é consumida ou obsoleta, e mantê-la deixaria um "sim" tardio encontrar
    contexto aberto para algo que já andou.
    """
    if order_status is None:
        return state

    updated = state
    if order_status is not OrderStatus.DRAFT and state.pending_confirmation is not None:
        updated = updated.confirmed()

    if order_status in _TERMINAL_FOR_JOURNEY:
        updated = updated.without_journey_references()

    return updated.with_phase(_PHASE_FOR_ORDER[order_status])
