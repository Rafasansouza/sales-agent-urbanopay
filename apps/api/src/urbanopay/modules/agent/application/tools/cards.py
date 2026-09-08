"""Tools de cartão (SPEC-002 §5, §6, §7; SPEC-004 §7).

Todas exigem sessão autenticada e todas operam sobre cartão **do próprio
cliente**: a titularidade é aplicada no backend, em consulta única, e um cartão
de terceiro responde `CARD_NOT_ACCESSIBLE` sem revelar se existe.

O número completo do cartão não existe no sistema (SPEC-002 §2): o que sai daqui
é sempre `card_id` + `masked_number`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from urbanopay.modules.agent.application import presenters
from urbanopay.modules.agent.domain.results import NextAction, ResultType, ToolResult

if TYPE_CHECKING:
    from urbanopay.modules.agent.application.schemas import CardInput, NoInput
    from urbanopay.modules.agent.application.tools import ToolContext


async def get_customer_cards(ctx: ToolContext, payload: NoInput) -> ToolResult:
    """Cartões do cliente autenticado (SPEC-002 §9).

    Sem saldo: saldo é dado sensível com tool própria, e trazê-lo em toda
    listagem violaria a minimização sem servir à maioria das conversas.
    """
    del payload
    cards = await ctx.services.cards.list_cards(ctx.require_customer())
    return ToolResult.success(
        ResultType.CARD_LIST,
        presenters.card_list(cards),
        next_action=NextAction.SELECT_CARD,
    )


async def get_card_details(ctx: ToolContext, payload: CardInput) -> ToolResult:
    """Detalhes de um cartão do próprio cliente (SPEC-002 §5)."""
    card = await ctx.services.cards.get_card(ctx.require_customer(), payload.card_id)
    return ToolResult.success(
        ResultType.CARD_DETAILS,
        presenters.card(card),
        next_action=NextAction.CONTINUE,
    )


async def get_card_balance(ctx: ToolContext, payload: CardInput) -> ToolResult:
    """Saldo oficial do cartão (SPEC-002 §7).

    Usa a leitura completa do cartão porque o resultado precisa do
    `masked_number` junto do valor — `CardService.get_card_balance` é
    exatamente `get_card(...).balance`, e duas consultas para o mesmo fato só
    acrescentariam ida ao banco.

    §7 não restringe a leitura a cartão `ACTIVE`: o titular pode consultar o
    saldo de um cartão bloqueado.
    """
    card = await ctx.services.cards.get_card(ctx.require_customer(), payload.card_id)
    return ToolResult.success(
        ResultType.CARD_BALANCE,
        presenters.card_balance(card, card.balance),
        next_action=NextAction.CONTINUE,
    )
