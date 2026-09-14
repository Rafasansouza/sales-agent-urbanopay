"""Webhook de pagamento (SPEC-003 §12; ADR-002, ADR-007, SPEC-005 §10.1).

**Este endpoint não passa pelo LLM e não passa pelo grafo.** Ele entra direto
no `PaymentService`, que é a única autoridade capaz de estabelecer
`Payment APPROVED`.

Idempotência: a unicidade `(provider, provider_event_id)` de `payment_events`,
garantida por constraint de banco com `ON CONFLICT DO NOTHING` (A-15). Evento
repetido é registrado uma vez e **nenhum efeito é reaplicado**.

Depois do commit financeiro — e somente depois — o coordenador pós-pagamento
recebe o `order_id` e chama `fulfill_order` (SPEC-005 §10.1, A-19). Falha de
entrega não gera nova cobrança.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from urbanopay.api.container import AppContainer
from urbanopay.api.v1.agent import get_container
from urbanopay.modules.payments.domain.enums import PaymentStatus, ProviderName

router = APIRouter(prefix="/payments", tags=["payments"])


class WebhookRequest(BaseModel):
    """Evento do provider.

    `reported_status` é **validado contra o enum** antes de chegar ao serviço:
    um endpoint público não pode aceitar status arbitrário. E mesmo válido, ele
    não é aplicado cegamente — o `PaymentService` decide, sob lock, com regras
    monotônicas, e estado terminal nunca regride.
    """

    model_config = ConfigDict(extra="forbid")

    provider: ProviderName = ProviderName.FAKE
    provider_event_id: str = Field(min_length=1, max_length=200)
    provider_payment_id: str = Field(min_length=1, max_length=200)
    reported_status: PaymentStatus
    payload: dict[str, Any] = Field(default_factory=dict)


class WebhookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    duplicate: bool
    requires_reconciliation: bool = False
    payment_status: str | None = None
    fulfillment_status: str | None = None


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Recebe evento de pagamento do provider",
)
async def payment_webhook(
    payload: WebhookRequest,
    container: Annotated[AppContainer, Depends(get_container)],
) -> WebhookResponse:
    """Aplica o evento e, se o Order converteu para `PAID`, dispara a entrega."""
    result = await container.payments.process_webhook(
        provider=payload.provider,
        provider_event_id=payload.provider_event_id,
        provider_payment_id=payload.provider_payment_id,
        reported_status=payload.reported_status,
        payload=payload.payload,
    )

    fulfillment_status: str | None = None
    payment = result.payment
    if payment is not None and result.applied:
        # Somente depois do commit financeiro, e somente para o efeito que de
        # fato foi aplicado agora: um webhook duplicado (`applied=False`) nunca
        # redispara entrega.
        delivered = await container.coordinator.on_payment_settled(
            order_id=payment.order_id, payment_status=payment.status
        )
        if delivered is not None:
            fulfillment_status = delivered.fulfillment.status.value

    return WebhookResponse(
        accepted=True,
        duplicate=result.duplicate,
        requires_reconciliation=result.requires_reconciliation,
        payment_status=payment.status.value if payment is not None else None,
        fulfillment_status=fulfillment_status,
    )
