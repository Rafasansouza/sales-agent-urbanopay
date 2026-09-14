"""Interceptação determinística de entrada sensível (SPEC-004 §13.1).

"Evitar CPF e OTP no prompt" não é contrato suficiente: numa autenticação
conversacional, o cliente **digita** esses valores. A defesa é de fluxo, não de
prompt.

```text
mensagem sensível do usuário
  → handler determinístico (este módulo)
    → tool SENSITIVE_INPUT → serviço de identity
      → histórico/estado redigido
        → somente então, se necessário, o LLM
```

Consequência que justifica `phase` ser campo persistido (ADR-014): **depois de
um restart, a fase precisa continuar conhecida**. Sem ela, a mensagem seguinte
— que contém o CPF ou o OTP — seguiria o caminho normal até o provider.

Nunca trafegam nem são persistidos: CPF cru, OTP cru, hash de CPF, hash de OTP,
segredo ou token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from urbanopay_agent.domain.catalog import ToolCaller, ToolName
from urbanopay_agent.domain.conversation import (
    DOCUMENT_REDACTION_MARKER,
    OTP_REDACTION_MARKER,
    SENSITIVE_INPUT_PHASES,
    ConversationPhase,
)

if TYPE_CHECKING:
    from urbanopay_agent.application.executor import ToolExecutor
    from urbanopay_agent.domain.conversation import ConversationState
    from urbanopay_agent.domain.results import ToolResult

_MARKER_BY_PHASE = {
    ConversationPhase.AWAITING_DOCUMENT: DOCUMENT_REDACTION_MARKER,
    ConversationPhase.AWAITING_OTP: OTP_REDACTION_MARKER,
}

_TOOL_BY_PHASE = {
    ConversationPhase.AWAITING_DOCUMENT: ToolName.START_AUTHENTICATION,
    ConversationPhase.AWAITING_OTP: ToolName.VERIFY_OTP,
}

_FIELD_BY_PHASE = {
    ConversationPhase.AWAITING_DOCUMENT: "document",
    ConversationPhase.AWAITING_OTP: "otp",
}


@dataclass(frozen=True, slots=True)
class SensitiveInputOutcome:
    """Resultado da interceptação.

    `redacted_message` é o que pode seguir para o modelo e para qualquer log:
    o valor original **não existe** fora da chamada ao serviço de identity.
    """

    result: ToolResult
    state: ConversationState
    redacted_message: str


def is_sensitive(state: ConversationState) -> bool:
    """Se a próxima mensagem do cliente carrega CPF ou OTP."""
    return state.phase in SENSITIVE_INPUT_PHASES


def redact(state: ConversationState, message: str) -> str:
    """Substitui a mensagem pelo marcador quando a fase é sensível.

    Usado também fora do caminho feliz — em log e em telemetria — para que a
    redação não dependa de o fluxo ter chegado até o handler.
    """
    marker = _MARKER_BY_PHASE.get(state.phase)
    return marker if marker is not None else message


async def handle(
    executor: ToolExecutor, *, state: ConversationState, message: str
) -> SensitiveInputOutcome:
    """Processa a entrada sensível **antes** de qualquer chamada ao provider.

    A tool é invocada como `ORCHESTRATOR`: `start_authentication` e
    `verify_otp` são `SENSITIVE_INPUT` e nunca aparecem no schema entregue ao
    modelo (SPEC-004 §7.1).
    """
    phase = state.phase
    tool = _TOOL_BY_PHASE[phase]
    outcome = await executor.execute(
        state=state,
        tool_name=tool.value,
        arguments={_FIELD_BY_PHASE[phase]: message.strip()},
        caller=ToolCaller.ORCHESTRATOR,
    )
    return SensitiveInputOutcome(
        result=outcome.result,
        state=outcome.state,
        redacted_message=_MARKER_BY_PHASE[phase],
    )
