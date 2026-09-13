"""Estado interno do grafo (ADR-014, framework independence).

`GraphState` é tipo **do adaptador**. Ele existe apenas dentro desta pasta e
não atravessa a fronteira: `domain`, `application`, contratos de tool e o
modelo de persistência não o conhecem.

A direção importa. O `ConversationState` — contrato da aplicação — **entra** no
grafo; o `GraphState` **não sai**. Trocar o orquestrador no futuro é reescrever
esta pasta, sem migração de dado e sem tocar no resto.

Note também o que não está aqui: histórico de mensagens. A conversa não guarda
o que foi dito (ADR-014), e o estado do turno morre com o turno.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from urbanopay.modules.agent.domain.conversation import ConversationState
    from urbanopay.modules.agent.domain.results import ToolResult
    from urbanopay.providers.llm import TurnUnderstanding


class GraphState(TypedDict, total=False):
    """Estado de um turno em execução.

    `total=False` porque os campos são preenchidos node a node: `understanding`
    só existe depois de `understand`, `results` depois de `act`, `reply`
    depois de `respond`.
    """

    message: str
    """Mensagem do cliente **já redigida**, quando a fase era sensível (§13.1).

    CPF e OTP nunca chegam aqui: o handler determinístico os consome antes, e o
    que entra no grafo é `[DOCUMENT_REDACTED]` ou `[OTP_REDACTED]`.
    """

    conversation: ConversationState

    authenticated: bool
    """Verdade da sessão de `identity`, relida pelo chamador a cada turno.

    Não é derivada do estado conversacional: guardar identidade ali criaria uma
    segunda autoridade, que sobreviveria à expiração da sessão (SPEC-004 §3.1).
    """

    understanding: TurnUnderstanding
    results: list[ToolResult]
    reply: str
