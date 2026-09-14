"""Contrato de execução de um turno (SPEC-004; ADR-014).

Este port é a fronteira que mantém o framework de orquestração substituível.
`ConversationService` depende **dele**, não do LangGraph: trocar o orquestrador
no futuro é reescrever o adaptador, sem tocar em `application`, em `domain` ou
nos dados de `agent_conversations` (ADR-014, framework independence).

`TurnOutcome` é o resultado de um turno completo. Ele carrega o **estado novo**
em vez de mutar o recebido, pelo mesmo motivo de `ExecutionOutcome`: o
`ConversationState` é imutável de ponta a ponta, e quem decide o que fazer com
o resultado é o chamador.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from urbanopay.modules.agent.domain.conversation import ConversationState
    from urbanopay.modules.agent.domain.results import NextAction, ToolResult


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """O que um turno produziu.

    `reply` é a única prosa do sistema, e ela é composta pelo modelo a partir
    de fatos estruturados — nunca copiada de um envelope de tool, que por
    contrato não carrega texto pronto (SPEC-004 §21).
    """

    state: ConversationState
    reply: str
    results: tuple[ToolResult, ...] = field(default_factory=tuple)

    @property
    def next_action(self) -> NextAction | None:
        """Próximo passo sugerido pelo último resultado, se houve algum."""
        return self.results[-1].next_action if self.results else None

    @property
    def last_code(self) -> str | None:
        return self.results[-1].code if self.results else None


class TurnRunner(Protocol):
    """Executa um turno de conversa sobre um estado carregado.

    Implementado pelo adaptador de grafo, em `infrastructure`. Nenhum tipo do
    framework aparece nesta assinatura.
    """

    async def run(
        self,
        *,
        state: ConversationState,
        message: str,
        authenticated: bool = False,
        skip_action: bool = False,
    ) -> TurnOutcome:
        """Executa um turno.

        `authenticated` é a verdade da sessão de `identity`, relida pelo
        chamador: o estado conversacional não guarda identidade, para que não
        exista uma segunda autoridade sobrevivendo à expiração da sessão.

        `skip_action` indica que o efeito do turno já aconteceu fora do grafo
        — é o caso da entrada sensível, em que o handler determinístico já
        consumiu CPF ou OTP e resta apenas compor a resposta.
        """
        ...
