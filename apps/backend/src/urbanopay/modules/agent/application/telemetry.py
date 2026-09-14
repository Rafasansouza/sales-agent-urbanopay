"""Telemetria sanitizada das tool calls (SPEC-004 §15, ADR-008).

Escopo desta etapa: **apenas log estruturado**, sobre a infraestrutura que já
existe. Langfuse e OpenTelemetry não entram — não estão no lock, e o modo de
implantação do Langfuse segue aberto em H-04. Instrumentar antes de decidir
produziria dependência sem consumidor.

O que este módulo registra é uma **allowlist**, não uma redação a posteriori.
A diferença importa: filtrar o que se sabe ser perigoso deixa passar o que
ainda não se pensou. Aqui, um campo só existe no log se estiver escrito abaixo.

Nunca registrados: argumentos crus de tool, CPF, OTP, hash, saldo, valor
monetário, payload de provider, QR code, idempotency key, credencial e stack
trace.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from urbanopay.modules.agent.domain.catalog import ToolCaller
    from urbanopay.modules.agent.domain.conversation import ConversationState
    from urbanopay.modules.agent.domain.results import ToolResult

_LOGGER = logging.getLogger("urbanopay.agent.tools")

_SAFE_RESOURCE_KEYS = ("order_id", "payment_id", "fulfillment_id", "receipt_id", "quote_id")
"""Identificadores opacos que podem ser correlacionados (ADR-008).

`card_id` fica de fora: correlacionar entrega e pagamento não exige apontar
para o instrumento do cliente.
"""


def _safe_resources(result: ToolResult) -> dict[str, Any]:
    return {
        key: value for key in _SAFE_RESOURCE_KEYS if isinstance(value := result.data.get(key), str)
    }


def record_tool_call(
    *,
    state: ConversationState,
    tool_name: str,
    caller: ToolCaller,
    result: ToolResult,
    duration_ms: float,
) -> None:
    """Registra uma tool call concluída.

    `conversation_id` e `session_id` são identificadores opacos e internos —
    é o que permite reconstruir uma jornada sem saber quem é o cliente.
    """
    _LOGGER.info(
        "tool_call",
        extra={
            "conversation_id": str(state.conversation_id),
            "session_id": str(state.session_id),
            "phase": state.phase.value,
            "tool": tool_name,
            "caller": caller.value,
            "ok": result.ok,
            "result_type": result.result_type.value,
            "code": result.code,
            "next_action": result.next_action.value if result.next_action else None,
            "duration_ms": round(duration_ms, 3),
            **_safe_resources(result),
        },
    )


def record_unexpected_error(
    *, state: ConversationState, tool_name: str, exc: BaseException
) -> None:
    """Registra uma exceção não mapeada.

    Apenas o **tipo** da exceção. A mensagem pode conter dado de entrada, e o
    stack trace não vai para log estruturado nem, em hipótese alguma, para a
    resposta (ADR-006).
    """
    _LOGGER.error(
        "tool_unexpected_error",
        extra={
            "conversation_id": str(state.conversation_id),
            "tool": tool_name,
            "exception_type": type(exc).__name__,
        },
    )
