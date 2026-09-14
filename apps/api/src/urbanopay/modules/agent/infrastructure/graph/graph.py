"""Grafo do Sales Agent (ADR-002, ADR-003, ADR-014).

**Um único agente conversacional em runtime** (ADR-003). Não existe Fare Agent,
Card Agent nem Payment Agent: os domínios são serviços determinísticos
alcançados por tools.

O grafo é compilado **sem checkpointer** (ADR-014). A durabilidade é da
aplicação: o `ConversationService` carrega o estado, invoca o grafo para o turno
inteiro e persiste o snapshot no fim. Não se usa `interrupt`/`resume` — a
confirmação do passageiro é fronteira de turno, e a aprovação humana é
assíncrona e acontece fora do grafo (A-07).

```text
START → understand → [precisa autenticar?] ┬→ act → respond → END
                                           └────────→ respond → END
```

`understand` e `respond` são os **únicos** nodes que falam com o modelo. `act` é
inteiramente determinístico: ele executa os playbooks, que decidem quais tools
rodam e em que ordem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from urbanopay.modules.agent.application.turn import TurnOutcome
from urbanopay.modules.agent.domain.conversation import SENSITIVE_INPUT_PHASES
from urbanopay.modules.agent.infrastructure.graph.playbooks import TurnPlaybook
from urbanopay.modules.agent.infrastructure.graph.state import GraphState
from urbanopay.providers.llm import TurnContext, TurnFact, TurnUnderstanding

if TYPE_CHECKING:
    from collections.abc import Sequence

    from urbanopay.modules.agent.application.executor import ToolExecutor
    from urbanopay.modules.agent.domain.conversation import ConversationState
    from urbanopay.modules.agent.domain.results import ToolResult
    from urbanopay.providers.llm import LLMProvider

_UNDERSTAND: Final = "understand"
_ACT: Final = "act"
_RESPOND: Final = "respond"


def _context(state: ConversationState, *, authenticated: bool) -> TurnContext:
    """Contexto entregue ao modelo — mínimo, e sem autoridade.

    Repare no que **não** vai: identificadores internos, saldo, `fare_profile`
    oficial, status de Order, Payment ou Fulfillment, CPF, nome. Status e
    valores chegam ao modelo apenas como fatos de tool já sanitizados, nunca
    como contexto que ele possa tomar por memória confiável (SPEC-004 §3.1).

    `authenticated` **não** vem do estado conversacional, que não é autoridade
    de identidade (SPEC-004 §3.1): ele é relido da sessão de `identity` pelo
    chamador e apenas repassado. Guardá-lo aqui criaria uma segunda autoridade,
    que sobreviveria à expiração da sessão.
    """
    pending = state.pending_confirmation
    return TurnContext(
        phase=state.phase.value,
        authenticated=authenticated,
        has_selected_card=state.selected_card_id is not None,
        has_pending_confirmation=pending is not None,
        awaiting_confirmation_total=pending.display_total if pending is not None else None,
    )


def _facts(results: Sequence[ToolResult]) -> list[TurnFact]:
    """Converte envelopes de tool em fatos para o modelo.

    O conteúdo já passou pelos presenters: valor monetário como string
    decimal, identificador opaco, instante ISO 8601, e nada de entidade de
    domínio, CPF, OTP, hash, idempotency key ou payload de provider.
    """
    return [
        TurnFact(
            tool=result.result_type.value,
            ok=result.ok,
            code=result.code,
            result_type=result.result_type.value,
            data=dict(result.data),
        )
        for result in results
    ]


class LangGraphTurnRunner:
    """Implementa `TurnRunner` sobre o LangGraph.

    Esta classe é a fronteira: para fora dela saem `TurnOutcome`,
    `ConversationState` e `ToolResult` — nunca um tipo do framework.
    """

    def __init__(
        self,
        *,
        executor: ToolExecutor,
        llm: LLMProvider,
        max_llm_calls_per_turn: int = 4,
    ) -> None:
        self._executor = executor
        self._llm = llm
        self._max_llm_calls = max_llm_calls_per_turn
        self._graph = self._build()

    # --- nodes -------------------------------------------------------------

    async def _understand(self, state: GraphState) -> GraphState:
        """Interpretação: o único ponto em que a fala do cliente vira estrutura.

        Em fase sensível a mensagem já chega redigida, então o modelo nunca vê
        CPF nem OTP — e, por isso mesmo, este node não é sequer alcançado no
        caminho de entrada sensível (o `ConversationService` o resolve antes).
        """
        understanding = await self._llm.understand(
            message=state["message"],
            context=_context(
                state["conversation"], authenticated=state.get("authenticated", False)
            ),
        )
        return {"understanding": understanding}

    async def _act(self, state: GraphState) -> GraphState:
        """Execução determinística. Nenhuma decisão aqui é do modelo."""
        playbook = TurnPlaybook(self._executor, state["conversation"])
        await playbook.run(state.get("understanding") or TurnUnderstanding())
        return {"conversation": playbook.state, "results": list(playbook.results)}

    async def _respond(self, state: GraphState) -> GraphState:
        """Composição da resposta a partir de fatos — nunca de memória."""
        reply = await self._llm.compose_reply(
            message=state["message"],
            context=_context(
                state["conversation"], authenticated=state.get("authenticated", False)
            ),
            facts=_facts(state.get("results") or []),
        )
        return {"reply": reply.message}

    @staticmethod
    def _needs_authentication(state: GraphState) -> str:
        """Aresta condicional: quando **não** há ação a executar neste turno.

        Dois casos, e ambos terminam em resposta direta:

        - a fase já é `AWAITING_DOCUMENT`/`AWAITING_OTP`: a próxima mensagem é
          que traz o dado, e ela será interceptada antes do modelo;
        - `skip_action`: o turno **foi** a entrada sensível. O resultado da
          autenticação já é o desfecho, e reexecutar o playbook sobre
          `[OTP_REDACTED]` classificaria um marcador como se fosse fala do
          cliente.
        """
        if state.get("skip_action"):
            return _RESPOND
        return _RESPOND if state["conversation"].phase in SENSITIVE_INPUT_PHASES else _ACT

    # --- montagem ----------------------------------------------------------

    def _build(self) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
        builder: StateGraph[GraphState, None, GraphState, GraphState] = StateGraph(GraphState)
        builder.add_node(_UNDERSTAND, self._understand)
        builder.add_node(_ACT, self._act)
        builder.add_node(_RESPOND, self._respond)

        builder.add_edge(START, _UNDERSTAND)
        builder.add_conditional_edges(
            _UNDERSTAND, self._needs_authentication, {_ACT: _ACT, _RESPOND: _RESPOND}
        )
        builder.add_edge(_ACT, _RESPOND)
        builder.add_edge(_RESPOND, END)

        # Sem checkpointer, por decisão (ADR-014): a durabilidade pertence à
        # aplicação, e o grafo executa um turno de cada vez.
        return builder.compile()

    # --- port --------------------------------------------------------------

    async def run(
        self,
        *,
        state: ConversationState,
        message: str,
        authenticated: bool = False,
        skip_action: bool = False,
    ) -> TurnOutcome:
        """Executa o turno completo e devolve o contrato da aplicação."""
        final = await self._graph.ainvoke(
            {
                "message": message,
                "conversation": state,
                "authenticated": authenticated,
                "skip_action": skip_action,
                "results": [],
            }
        )
        return TurnOutcome(
            state=final["conversation"],
            reply=final.get("reply", ""),
            results=tuple(final.get("results") or []),
        )
