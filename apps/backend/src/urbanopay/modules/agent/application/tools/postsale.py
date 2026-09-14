"""Tools de pós-venda (SPEC-005 §14, §15; SPEC-004 §7).

Somente leitura, sempre filtradas por titularidade. Nenhuma tool daqui executa,
reprocessa ou repara entrega: `fulfill_order` é `BACKEND_ONLY` e o disparo
pertence à camada de composição (SPEC-005 §10.1).

Diante de `RECONCILIATION_REQUIRED`, a automação **para**. Não há retentativa,
não há troca de cartão, não há estorno — e a resolução administrativa continua
aberta em A-18.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from urbanopay.modules.agent.application import presenters
from urbanopay.modules.agent.domain.results import NextAction, ResultType, ToolResult
from urbanopay.modules.fulfillment.domain.enums import FulfillmentStatus

if TYPE_CHECKING:
    from collections.abc import Mapping

    from urbanopay.modules.agent.application.schemas import OrderInput
    from urbanopay.modules.agent.application.tools import ToolContext

_FULFILLMENT_NEXT: Final[Mapping[FulfillmentStatus, NextAction]] = {
    FulfillmentStatus.PENDING: NextAction.WAIT,
    FulfillmentStatus.PROCESSING: NextAction.WAIT,
    FulfillmentStatus.COMPLETED: NextAction.CONTINUE,
    # Os dois desfechos sem efeito financeiro exigem gente, não automação.
    FulfillmentStatus.FAILED: NextAction.HUMAN_REVIEW,
    FulfillmentStatus.RECONCILIATION_REQUIRED: NextAction.HUMAN_REVIEW,
}


async def get_fulfillment_status(ctx: ToolContext, payload: OrderInput) -> ToolResult:
    """Estado da entrega de um Order do próprio cliente (SPEC-005 §14)."""
    fulfillment = await ctx.services.fulfillment.get_fulfillment_status(
        customer_id=ctx.require_customer(), order_id=payload.order_id
    )
    return ToolResult.success(
        ResultType.FULFILLMENT_STATUS,
        presenters.fulfillment(fulfillment),
        next_action=_FULFILLMENT_NEXT[fulfillment.status],
    )


async def get_receipt(ctx: ToolContext, payload: OrderInput) -> ToolResult:
    """Comprovante simulado, disponível somente após `COMPLETED` (§13).

    Antes disso o serviço responde `RECEIPT_NOT_AVAILABLE` — nunca um
    documento provisório: comprovante emitido antes do efeito seria prova de
    algo que não aconteceu.
    """
    receipt = await ctx.services.fulfillment.get_receipt(
        customer_id=ctx.require_customer(), order_id=payload.order_id
    )
    return ToolResult.success(
        ResultType.RECEIPT,
        presenters.receipt(receipt),
        next_action=NextAction.CONTINUE,
    )
