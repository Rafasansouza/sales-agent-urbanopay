"""Erros de guarda da orquestração (SPEC-004 §20, A-20).

Separados dos erros de domínio de propósito. Um erro de domínio diz que uma
operação **não pôde acontecer**; um erro de guarda diz que a operação **não foi
sequer tentada**, porque a invocação não passou na fronteira.

Nenhum deles cria, altera ou encerra estado financeiro, e nenhum define status
HTTP: a tradução para transporte pertence à camada HTTP, que não existe nesta
etapa.
"""

from __future__ import annotations

from typing import ClassVar

from urbanopay.modules.agent.domain.results import GuardCode, NextAction


class AgentGuardError(Exception):
    """Recusa da fronteira de orquestração, antes de qualquer serviço."""

    code: ClassVar[GuardCode]
    next_action: ClassVar[NextAction]


class ToolNotAuthorizedError(AgentGuardError):
    """Nome não registrado, ou registrado em nível não permitido ao chamador.

    Cobre indistintamente três casos — nome inexistente, nome `BACKEND_ONLY` e
    tool visível apenas à orquestração invocada pelo modelo. A
    indistinguibilidade é intencional: a recusa não informa o que existe do
    outro lado da fronteira.
    """

    code = GuardCode.TOOL_NOT_AUTHORIZED
    next_action = NextAction.STOP


class ToolUnavailableError(AgentGuardError):
    """Tool declarada em SPEC-004 §7 e bloqueada por questão aberta (§7.3).

    O bloqueio é **nomeado** no resultado. Recusar dizendo qual decisão falta é
    diferente de fingir que a capacidade não foi prometida.
    """

    code = GuardCode.TOOL_UNAVAILABLE
    next_action = NextAction.STOP

    def __init__(self, blocker: str) -> None:
        self.blocker = blocker
        super().__init__(f"Tool indisponivel: bloqueada por {blocker}.")


class ToolLimitExceededError(AgentGuardError):
    """Excedido o teto de tool calls do turno (SPEC-004 §14)."""

    code = GuardCode.TOOL_LIMIT_EXCEEDED
    next_action = NextAction.STOP


class NoPendingConfirmationError(AgentGuardError):
    """Falta o contexto de orquestração que o comando exige (§9.1).

    Dois casos: `confirm_order` sem Order aguardando confirmação, e
    `create_payment` sem Order confirmado no contexto comercial. Em ambos, um
    "sim" solto ou uma tool call fora de hora não encontra o que executar.
    """

    code = GuardCode.NO_PENDING_CONFIRMATION
    next_action = NextAction.STOP


class ConfirmationContextMismatchError(AgentGuardError):
    """A invocação tentou vincular recurso diferente do que o contexto guarda.

    É a defesa contra confirmar ou pagar a Order errada — inclusive quando o
    identificador proposto é válido e pertence ao mesmo cliente.
    """

    code = GuardCode.CONFIRMATION_CONTEXT_MISMATCH
    next_action = NextAction.STOP
