"""Transporte HTTP da conversa (SPEC-004 §22, Etapa 3; ADR-006, ADR-017).

Router fino: valida entrada, delega ao `ConversationService` e formata saída.
Nenhuma regra de negócio aqui.

O router mora **no pacote do agente**, e não no backend: quem define o contrato
da conversa é quem implementa a conversa (ADR-017). Para que isso não recrie o
ciclo `agent → backend`, ele é uma **fábrica**: declara o que precisa — um
`ConversationGateway` — e recebe de quem monta a forma de obtê-lo.

O que a resposta **não** carrega, por contrato: identificador de Quote, Payment
ou Fulfillment, valor monetário autoritativo, status de agregado, CPF, OTP,
número de cartão e qualquer detalhe interno. A prosa vem do modelo, composta a
partir de fatos já sanitizados pelos presenters.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from urbanopay_agent.application.conversation_service import ConversationService
from urbanopay_agent.domain.errors import (
    CONVERSATION_CONFLICT,
    ConversationConflictError,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class TurnRequestStore(Protocol):
    """Deduplicação do request HTTP de conversa (ADR-014, D-6).

    Port declarado **aqui**, e não importado do backend: quem define o que a
    superfície de conversa precisa é ela mesma. Quem monta a aplicação fornece
    a implementação — e é isso que mantém a seta apontando numa direção só
    (ADR-017).
    """

    async def replay(self, *, conversation_id: UUID, request_id: str) -> str | None: ...

    async def remember(
        self, *, conversation_id: UUID, request_id: str, response_body: str, now: datetime
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ConversationGateway:
    """Tudo o que o endpoint de conversa alcança — e nada além disso."""

    conversations: ConversationService
    turn_requests: TurnRequestStore


class MessageRequest(BaseModel):
    """Uma mensagem do cliente."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None
    session_id: UUID | None = None
    request_id: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Identificador do request, para deduplicar retry HTTP. Distinto das "
            "idempotencias de negocio de create_order, confirm_order e create_payment."
        ),
    )


class OrderPanelSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    status: str
    total: str
    currency: str
    requires_approval: bool


class PixPanelSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: str
    status: str
    amount: str
    currency: str
    qr_code: str | None = None


class ReceiptPanelSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: str
    amount: str
    currency: str
    masked_card: str
    document_kind: str
    issued_at: str


class PanelSchema(BaseModel):
    """Fatos exibíveis do turno.

    Valor monetário é **string decimal** (ADR-006): ele existe para ser exibido,
    nunca somado. O frontend não calcula nada a partir daqui.
    """

    model_config = ConfigDict(extra="forbid")

    order: OrderPanelSchema | None = None
    pix: PixPanelSchema | None = None
    receipt: ReceiptPanelSchema | None = None
    fulfillment_status: str | None = None


class MessageResponse(BaseModel):
    """Resposta de um turno."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    session_id: UUID
    phase: str
    message: str
    code: str | None = None
    next_action: str | None = None
    panel: PanelSchema = PanelSchema()


def _now() -> datetime:
    return datetime.now(UTC)


async def _replay(
    gateway: ConversationGateway, payload: MessageRequest
) -> dict[str, object] | None:
    """Resposta anterior deste request, se houver.

    Exige `conversation_id`: sem conversa não há escopo de deduplicação, e um
    `request_id` global colidiria entre clientes distintos.
    """
    if not payload.request_id or payload.conversation_id is None:
        return None
    stored = await gateway.turn_requests.replay(
        conversation_id=payload.conversation_id, request_id=payload.request_id
    )
    if stored is None:
        return None
    decoded = json.loads(stored)
    return decoded if isinstance(decoded, dict) else None


def build_agent_router(provider: Callable[..., ConversationGateway]) -> APIRouter:
    """Monta o router do agente sobre um provedor de dependência.

    O agente **não conhece o composition root**. Sem esta inversão, `agent`
    importaria `backend` e o ciclo que o ADR-017 existe para evitar voltaria.
    """
    router = APIRouter(prefix="/agent", tags=["agent"])

    @router.post(
        "/messages",
        response_model=MessageResponse,
        summary="Envia uma mensagem ao Sales Agent",
    )
    async def post_message(
        payload: MessageRequest,
        # `Depends` no default, e não em `Annotated`: com
        # `from __future__ import annotations` a anotação vira string, e o
        # FastAPI a resolve no namespace do **módulo** — onde `provider`, que é
        # variável desta closure, não existe. O default é avaliado na hora, e
        # por isso funciona.
        gateway: ConversationGateway = Depends(provider),  # noqa: B008
    ) -> JSONResponse:
        """Processa um turno de conversa.

        **Idempotência de request** (ADR-014, D-6): com `request_id` e uma
        conversa já existente, um retry devolve a resposta anterior em vez de
        executar um segundo turno. Isso não substitui idempotência de negócio —
        Order, confirmação e cobrança continuam protegidos por keys derivadas de
        evidência persistida e por constraints de banco. O que se evita aqui é
        custo de LLM duplicado e duas respostas divergentes para a mesma
        mensagem.

        **Conflito de turno concorrente** responde `409`: a escrita perdedora é
        descartada, nunca mesclada. Mesclar contextos divergentes é o que
        produziria a confirmação errada.
        """
        replay = await _replay(gateway, payload)
        if replay is not None:
            return JSONResponse(content=replay, status_code=status.HTTP_200_OK)

        try:
            turn = await gateway.conversations.handle_message(
                message=payload.message,
                conversation_id=payload.conversation_id,
                session_id=payload.session_id,
            )
        except ConversationConflictError:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "error": {
                        "code": CONVERSATION_CONFLICT,
                        "message": (
                            "Outro turno desta conversa esta em andamento. Tente novamente."
                        ),
                    }
                },
            )

        body = MessageResponse(
            conversation_id=turn.conversation_id,
            session_id=turn.session_id,
            phase=turn.phase,
            message=turn.reply,
            code=turn.code,
            next_action=turn.next_action,
            panel=PanelSchema.model_validate(asdict(turn.panel)),
        ).model_dump(mode="json")

        if payload.request_id:
            await gateway.turn_requests.remember(
                conversation_id=turn.conversation_id,
                request_id=payload.request_id,
                response_body=json.dumps(body),
                now=_now(),
            )
        return JSONResponse(content=body, status_code=status.HTTP_200_OK)

    return router
