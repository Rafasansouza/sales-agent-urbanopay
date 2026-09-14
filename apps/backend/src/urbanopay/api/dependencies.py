"""Dependências da camada HTTP (ADR-006, ADR-017).

Ponto único que alcança o container montado no lifespan. Ele vive no `backend`
porque é o backend que monta — o agente e os domínios não conhecem o
composition root, e é isso que mantém a direção de dependência numa seta só.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from urbanopay.api.container import AppContainer

if TYPE_CHECKING:
    from urbanopay_agent.api import ConversationGateway


def get_container(request: Request) -> AppContainer:
    """Container montado no lifespan da aplicação."""
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, AppContainer):  # pragma: no cover - defensivo
        raise RuntimeError("Container da aplicacao nao foi inicializado.")
    return container


def get_conversation_gateway(request: Request) -> ConversationGateway:
    """Colaboradores que o endpoint de conversa precisa alcançar."""
    return get_container(request).conversation_gateway()
