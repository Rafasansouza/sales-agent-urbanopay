"""Execução de tool: a fronteira entre o modelo e o domínio (SPEC-004 §13, §20).

Pipeline fixo, na ordem:

```text
nome → registry → visibilidade → limite de turno → autenticação
     → contexto → schema → serviço de aplicação → presenter
     → ToolResult → transição de estado → telemetria sanitizada
```

A ordem não é estética. A autenticação vem **antes** da validação de schema
para que uma chamada anônima malformada não receba uma resposta diferente de
uma chamada anônima bem formada — a mensagem de erro nunca é canal de
informação sobre o outro lado da fronteira.

Nada aqui resolve nome por `getattr`, por import dinâmico ou por qualquer
fallback. Nome que não está no registry não executa.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from urbanopay.modules.agent.application.error_mapping import map_domain_error
from urbanopay.modules.agent.application.registry import (
    AuthenticationRequirement,
    ContextRequirement,
    get_spec,
    is_callable_by,
)
from urbanopay.modules.agent.application.state_transitions import apply_result
from urbanopay.modules.agent.application.telemetry import (
    record_tool_call,
    record_unexpected_error,
)
from urbanopay.modules.agent.application.tools import ToolContext
from urbanopay.modules.agent.domain.catalog import UNAVAILABLE_TOOLS, ToolCaller
from urbanopay.modules.agent.domain.errors import (
    AgentGuardError,
    NoPendingConfirmationError,
    ToolLimitExceededError,
    ToolNotAuthorizedError,
    ToolUnavailableError,
)
from urbanopay.modules.agent.domain.results import GuardCode, NextAction, ToolResult
from urbanopay.modules.identity.domain.errors import SessionExpiredError, SessionNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from uuid import UUID

    from urbanopay.modules.agent.application.registry import ToolSpec
    from urbanopay.modules.agent.domain.conversation import ConversationState
    from urbanopay.modules.agent.infrastructure.composition import AgentServices

DEFAULT_MAX_TOOL_CALLS_PER_TURN: Final = 5
"""Teto de tool calls por turno (SPEC-004 §14, sugestão inicial da SPEC).

Vive aqui, e não em `Settings`, porque é limite **da camada de tools** e tem
consumidor nesta etapa. Os limites de LLM — chamadas, tokens, custo — pertencem
à Etapa 2, junto do provider que os consome.
"""


class _ArgumentRejectedError(Exception):
    """Entrada reprovada pelo contrato da tool.

    Interna ao executor: existe apenas para carregar o `ToolSpec` até o ponto
    de tradução, sem que a `ValidationError` do Pydantic — que contém os
    argumentos recebidos — chegue perto do envelope ou do log.
    """

    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        super().__init__(spec.name.value)


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Resultado da execução e o estado resultante.

    O estado é devolvido em vez de mutado: o chamador decide o que fazer com
    ele, e um `ConversationState` continua imutável de ponta a ponta.
    """

    result: ToolResult
    state: ConversationState


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ToolExecutor:
    """Executa tools do catálogo fechado, aplicando a fronteira inteira."""

    def __init__(
        self,
        services: AgentServices,
        *,
        clock: Callable[[], datetime] = _utc_now,
        max_tool_calls_per_turn: int = DEFAULT_MAX_TOOL_CALLS_PER_TURN,
    ) -> None:
        self._services = services
        self._clock = clock
        self._max_tool_calls_per_turn = max_tool_calls_per_turn

    async def execute(
        self,
        *,
        state: ConversationState,
        tool_name: str,
        arguments: Mapping[str, object] | None = None,
        caller: ToolCaller = ToolCaller.LLM,
    ) -> ExecutionOutcome:
        """Executa uma tool e devolve envelope + estado."""
        started = time.perf_counter()
        spec = get_spec(tool_name)

        try:
            if spec is None:
                raise self._unresolved(tool_name)
            if not is_callable_by(spec, caller):
                # Tool existe, mas não para este chamador. A recusa é a mesma
                # de um nome inexistente, de propósito.
                raise ToolNotAuthorizedError
            if state.tool_calls_this_turn >= self._max_tool_calls_per_turn:
                raise ToolLimitExceededError

            customer_id = await self._resolve_identity(spec, state)
            self._require_context(spec, state)
            payload = self._validate(spec, arguments or {})

            ctx = ToolContext(services=self._services, state=state, customer_id=customer_id)
            result = await spec.handler(ctx, payload)
        except AgentGuardError as guard:
            result = ToolResult.failure(guard.code.value, next_action=guard.next_action)
        except Exception as exc:
            # Fronteira: nenhuma exceção escapa para o modelo. Desconhecida
            # vira INTERNAL_ERROR sanitizado — jamais sucesso (§20).
            result = self._from_exception(exc, state=state, tool_name=tool_name)

        updated = (
            apply_result(state, spec.name, result, now=self._clock()) if spec is not None else state
        )
        record_tool_call(
            state=updated,
            tool_name=tool_name,
            caller=caller,
            result=result,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return ExecutionOutcome(result=result, state=updated)

    # --- etapas do pipeline ----------------------------------------------

    @staticmethod
    def _unresolved(tool_name: str) -> AgentGuardError:
        """Nome fora do registry.

        Distingue dois casos, e apenas dois: tool **declarada e bloqueada** por
        questão aberta, que merece resposta honesta com o bloqueio nomeado; e
        todo o resto — inclusive `BACKEND_ONLY` e nomes inventados —, que
        recebe a mesma recusa indiferenciada.
        """
        blocker = UNAVAILABLE_TOOLS.get(tool_name)
        if blocker is not None:
            return ToolUnavailableError(blocker)
        return ToolNotAuthorizedError()

    async def _resolve_identity(self, spec: ToolSpec, state: ConversationState) -> UUID | None:
        """Portão de autenticação (SPEC-002 §9).

        `REQUIRED` resolve a identidade e **renova** a janela de inatividade —
        uso da sessão é atividade. `OPTIONAL` apenas observa, sem renovar, e
        trata sessão ausente ou expirada como anônima: simulação tarifária é
        informação pública, e recusá-la por sessão vencida não protegeria nada.
        """
        if spec.authentication is AuthenticationRequirement.REQUIRED:
            authenticated = await self._services.sessions.require_authenticated(state.session_id)
            return authenticated.customer_id
        if spec.authentication is AuthenticationRequirement.OPTIONAL:
            try:
                status = await self._services.sessions.get_authentication_status(state.session_id)
            except (SessionNotFoundError, SessionExpiredError):
                return None
            return status.customer_id if status.authenticated else None
        return None

    @staticmethod
    def _require_context(spec: ToolSpec, state: ConversationState) -> None:
        """Exigência de contexto comercial (§9.1).

        Sem o contexto não há o que executar: um "sim" solto não encontra Order
        aguardando confirmação, e um pedido de pagamento fora de jornada não
        encontra Order confirmado.
        """
        requirement = spec.context_requirement
        if requirement is ContextRequirement.PENDING_CONFIRMATION:
            if state.pending_confirmation is None:
                raise NoPendingConfirmationError
        elif requirement is ContextRequirement.CURRENT_ORDER and state.current_order_id is None:
            raise NoPendingConfirmationError

    @staticmethod
    def _validate(spec: ToolSpec, arguments: Mapping[str, object]) -> object:
        """Valida a entrada contra o contrato declarado.

        Falha estrutural é traduzida para o código semântico que a tool
        declara, e não para um código próprio (§20): para um identificador,
        "malformado" e "não é seu" devem ser indistinguíveis.
        """
        try:
            return spec.input_model.model_validate(dict(arguments))
        except ValidationError as exc:
            raise _ArgumentRejectedError(spec) from exc

    def _from_exception(
        self, exc: Exception, *, state: ConversationState, tool_name: str
    ) -> ToolResult:
        """Converte exceção em envelope. **Nunca** em sucesso (§20)."""
        if isinstance(exc, _ArgumentRejectedError):
            return ToolResult.failure(
                exc.spec.argument_error_code,
                next_action=exc.spec.argument_error_next_action,
            )
        mapped = map_domain_error(exc)
        if mapped is not None:
            code, next_action = mapped
            return ToolResult.failure(code, next_action=next_action)

        record_unexpected_error(state=state, tool_name=tool_name, exc=exc)
        return ToolResult.failure(GuardCode.INTERNAL_ERROR.value, next_action=NextAction.STOP)
