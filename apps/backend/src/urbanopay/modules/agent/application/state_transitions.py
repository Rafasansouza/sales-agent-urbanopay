"""Transição do estado conversacional a partir de um resultado de tool.

**Único lugar** onde o estado muda. Os handlers apenas leem: se cada um
pudesse escrever, a regra de "qual Order está aguardando confirmação" ficaria
espalhada, e é exatamente essa regra que impede um "sim" de confirmar a compra
errada.

Função pura: recebe estado e resultado, devolve estado novo. Nada aqui consulta
banco, e nada aqui decide negócio — o que se guarda são **referências** ao que
o backend já decidiu.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from urbanopay.modules.agent.domain.catalog import ToolName
from urbanopay.modules.agent.domain.conversation import (
    ConversationPhase,
    ConversationState,
    PendingConfirmation,
)
from urbanopay.modules.cards.domain.enums import CardStatus
from urbanopay.modules.orders.domain.enums import OrderStatus

if TYPE_CHECKING:
    from datetime import datetime

    from urbanopay.modules.agent.domain.results import ToolData, ToolResult


def _text(data: ToolData, key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _identifier(data: ToolData, key: str) -> UUID | None:
    raw = _text(data, key)
    if raw is None:
        return None
    try:
        return UUID(raw)
    except ValueError:  # pragma: no cover - presenters só emitem UUID válido
        return None


def apply_result(
    state: ConversationState, tool: ToolName, result: ToolResult, *, now: datetime
) -> ConversationState:
    """Estado após uma tool call.

    A contagem do turno acontece **sempre**, inclusive em recusa: o limite de
    §14 existe para conter laços, e um laço de chamadas que falham é
    exatamente o caso que ele precisa conter.

    Resultado sem sucesso não move nada além do contador. Uma falha não
    seleciona cartão, não abre confirmação e não avança fase.
    """
    updated = state.counted_tool_call(tool, result.code)
    if not result.ok:
        return updated
    return _apply_success(updated, tool, result, now=now)


def _apply_success(
    state: ConversationState, tool: ToolName, result: ToolResult, *, now: datetime
) -> ConversationState:
    data = result.data

    if tool is ToolName.CALCULATE_TRIP_FARE:
        return state.with_phase(ConversationPhase.CALCULATION)

    if tool is ToolName.START_AUTHENTICATION:
        # O desafio existe: a próxima mensagem do cliente carrega o OTP e
        # precisa da interceptação determinística de §13.1.
        return state.with_phase(ConversationPhase.AWAITING_OTP)

    if tool is ToolName.VERIFY_OTP:
        return state.with_phase(ConversationPhase.CARD_SELECTION)

    if tool is ToolName.GET_CARD_DETAILS:
        return _select_card_if_usable(state, data)

    if tool is ToolName.CREATE_RECHARGE_QUOTE:
        return _after_quote(state, data)

    if tool is ToolName.CREATE_ORDER:
        return _after_order(state, data, now=now)

    if tool is ToolName.CONFIRM_ORDER:
        return _after_confirmation(state, data)

    if tool is ToolName.CREATE_PAYMENT:
        payment_id = _identifier(data, "payment_id")
        moved = state.with_phase(ConversationPhase.PAYMENT)
        return moved.with_payment(payment_id) if payment_id is not None else moved

    return state


def _select_card_if_usable(state: ConversationState, data: ToolData) -> ConversationState:
    """Seleciona o cartão consultado, **se ele for utilizável**.

    Um cartão bloqueado ou expirado não vira seleção: selecioná-lo faria a
    simulação tarifária seguinte tentar resolver o perfil oficial de um cartão
    inutilizável e falhar por um motivo que o cliente não pediu.
    """
    card_id = _identifier(data, "card_id")
    if card_id is None or _text(data, "status") != CardStatus.ACTIVE.value:
        return state
    return state.with_selected_card(card_id)


def _after_quote(state: ConversationState, data: ToolData) -> ConversationState:
    updated = state.with_phase(ConversationPhase.QUOTE)
    quote_id = _identifier(data, "quote_id")
    if quote_id is not None:
        updated = updated.with_quote(quote_id)
    card_id = _identifier(data, "card_id")
    if card_id is not None:
        # A Quote só nasce sobre cartão ACTIVE do titular: a seleção aqui é
        # consequência de uma validação que já aconteceu.
        updated = updated.with_selected_card(card_id)
    return updated


def _after_order(state: ConversationState, data: ToolData, *, now: datetime) -> ConversationState:
    """Abre o contexto de confirmação (§9.1).

    A partir daqui existe **uma** Order confirmável, e o total apresentado
    fica registrado apenas para compor a frase — nunca para decidir.
    """
    order_id = _identifier(data, "order_id")
    total = _text(data, "total")
    if order_id is None or total is None:  # pragma: no cover - presenter garante
        return state
    return state.with_phase(ConversationPhase.ORDER_CONFIRMATION).awaiting_confirmation(
        PendingConfirmation(order_id=order_id, display_total=total, presented_at=now)
    )


def _after_confirmation(state: ConversationState, data: ToolData) -> ConversationState:
    """Consome a confirmação e roteia pelo destino que o backend decidiu.

    `REQUIRES_APPROVAL` leva à fase de aprovação e **encerra** a automação
    financeira: nada nesta camada aprova, e o único caminho adiante é a decisão
    humana (A-07).
    """
    consumed = state.confirmed()
    if _text(data, "status") == OrderStatus.REQUIRES_APPROVAL.value:
        return consumed.with_phase(ConversationPhase.APPROVAL)
    return consumed.with_phase(ConversationPhase.PAYMENT)
