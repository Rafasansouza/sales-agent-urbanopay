"""Transporte HTTP da conversa (SPEC-004 §22, Etapa 3; ADR-006).

Router fino: valida entrada, delega ao `ConversationService` e formata saída.
Nenhuma regra de negócio aqui.

O que a resposta **não** carrega, por contrato: identificador de Quote, Payment
ou Fulfillment, valor monetário autoritativo, status de agregado, CPF, OTP,
número de cartão e qualquer detalhe interno. A prosa vem do modelo, composta a
partir de fatos já sanitizados pelos presenters.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from urbanopay.api.container import AppContainer
from urbanopay.modules.agent.domain.errors import (
    CONVERSATION_CONFLICT,
    ConversationConflictError,
)

router = APIRouter(prefix="/agent", tags=["agent"])


def get_container(request: Request) -> AppContainer:
    """Container montado no lifespan da aplicação."""
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, AppContainer):  # pragma: no cover - defensivo
        raise RuntimeError("Container da aplicacao nao foi inicializado.")
    return container


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


class MessageResponse(BaseModel):
    """Resposta de um turno."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    session_id: UUID
    phase: str
    message: str
    code: str | None = None
    next_action: str | None = None


@router.post(
    "/messages",
    response_model=MessageResponse,
    summary="Envia uma mensagem ao Sales Agent",
)
async def post_message(
    payload: MessageRequest,
    container: Annotated[AppContainer, Depends(get_container)],
) -> JSONResponse:
    """Processa um turno de conversa.

    **Idempotência de request** (ADR-014, D-6): com `request_id` e uma conversa
    já existente, um retry devolve a resposta anterior em vez de executar um
    segundo turno. Isso não substitui idempotência de negócio — Order,
    confirmação e cobrança continuam protegidos por keys derivadas de evidência
    persistida e por constraints de banco. O que se evita aqui é custo de LLM
    duplicado e duas respostas divergentes para a mesma mensagem.

    **Conflito de turno concorrente** responde `409`: a escrita perdedora é
    descartada, nunca mesclada. Mesclar contextos divergentes é o que
    produziria a confirmação errada.
    """
    replay = await _replay(container, payload)
    if replay is not None:
        return JSONResponse(content=replay, status_code=status.HTTP_200_OK)

    try:
        turn = await container.conversations.handle_message(
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
                    "message": "Outro turno desta conversa esta em andamento. Tente novamente.",
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
    ).model_dump(mode="json")

    if payload.request_id:
        await container.turn_requests.remember(
            conversation_id=turn.conversation_id,
            request_id=payload.request_id,
            response_body=json.dumps(body),
            now=_now(),
        )
    return JSONResponse(content=body, status_code=status.HTTP_200_OK)


async def _replay(container: AppContainer, payload: MessageRequest) -> dict[str, object] | None:
    """Resposta anterior deste request, se houver.

    Exige `conversation_id`: sem conversa não há escopo de deduplicação, e um
    `request_id` global colidiria entre clientes distintos.
    """
    if not payload.request_id or payload.conversation_id is None:
        return None
    stored = await container.turn_requests.replay(
        conversation_id=payload.conversation_id, request_id=payload.request_id
    )
    if stored is None:
        return None
    decoded = json.loads(stored)
    return decoded if isinstance(decoded, dict) else None


def _now() -> datetime:
    return datetime.now(UTC)
