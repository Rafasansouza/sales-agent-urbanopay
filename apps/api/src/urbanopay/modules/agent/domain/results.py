"""Envelope de resultado de tool (SPEC-004 §17, §21).

Toda tool devolve a mesma estrutura. Resultado nunca é string solta quando a
aplicação possui semântica estruturada: o modelo recebe **fatos**, e a prosa é
trabalho dele.

O envelope é também onde a proibição de PII deixa de ser recomendação e vira
código: `data` é construída exclusivamente por presenters, com tipos
serializáveis, e nada além deles pode entrar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

JsonScalar = str | int | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
ToolData = Mapping[str, JsonValue]
"""Dados do envelope.

Deliberadamente restrito a escalares, listas e dicionários: um `Decimal`, um
`UUID`, um `datetime` ou uma entidade de domínio **não** cabem aqui. A
conversão é responsabilidade dos presenters — valor monetário vira string
decimal, identificador vira string opaca, instante vira ISO 8601.
"""

OK_CODE = "OK"


class ResultType(StrEnum):
    """Classe do resultado, para o modelo saber o que recebeu."""

    FARE_CALCULATION = "FARE_CALCULATION"
    AUTHENTICATION_CHALLENGE = "AUTHENTICATION_CHALLENGE"
    AUTHENTICATION_VERIFICATION = "AUTHENTICATION_VERIFICATION"
    AUTHENTICATION_STATUS = "AUTHENTICATION_STATUS"
    CARD_LIST = "CARD_LIST"
    CARD_DETAILS = "CARD_DETAILS"
    CARD_BALANCE = "CARD_BALANCE"
    QUOTE = "QUOTE"
    ORDER = "ORDER"
    APPROVAL_STATUS = "APPROVAL_STATUS"
    PAYMENT = "PAYMENT"
    PAYMENT_STATUS = "PAYMENT_STATUS"
    FULFILLMENT_STATUS = "FULFILLMENT_STATUS"
    RECEIPT = "RECEIPT"
    ERROR = "ERROR"


class NextAction(StrEnum):
    """Próximo passo determinístico sugerido à orquestração.

    É orientação de fluxo, não permissão: nada aqui autoriza efeito algum. Os
    valores terminais — `STOP`, `HUMAN_REVIEW`, `AWAIT_HUMAN_APPROVAL`,
    `WAIT_RECONCILIATION` — encerram a automação financeira do turno.
    """

    CONTINUE = "CONTINUE"
    AUTHENTICATE = "AUTHENTICATE"
    RESTART_AUTH = "RESTART_AUTH"
    RETRY_DOCUMENT = "RETRY_DOCUMENT"
    RETRY_OTP = "RETRY_OTP"
    SELECT_CARD = "SELECT_CARD"
    ASK_TRIP = "ASK_TRIP"
    ASK_AMOUNT = "ASK_AMOUNT"
    RECREATE_QUOTE = "RECREATE_QUOTE"
    RECREATE_ORDER = "RECREATE_ORDER"
    REFRESH_ORDER = "REFRESH_ORDER"
    CONFIRM_ORDER = "CONFIRM_ORDER"
    AWAIT_HUMAN_APPROVAL = "AWAIT_HUMAN_APPROVAL"
    AWAIT_PAYMENT = "AWAIT_PAYMENT"
    RETRY_PAYMENT_LATER = "RETRY_PAYMENT_LATER"
    WAIT_RECONCILIATION = "WAIT_RECONCILIATION"
    CHECK_FULFILLMENT = "CHECK_FULFILLMENT"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    WAIT = "WAIT"
    STOP = "STOP"


class GuardCode(StrEnum):
    """Códigos de guarda da orquestração (SPEC-004 §20, A-20).

    São distintos dos erros de domínio: descrevem por que uma invocação foi
    recusada **antes** de qualquer serviço ser chamado. Nenhum deles cria,
    altera ou encerra estado financeiro.
    """

    TOOL_NOT_AUTHORIZED = "TOOL_NOT_AUTHORIZED"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    TOOL_LIMIT_EXCEEDED = "TOOL_LIMIT_EXCEEDED"
    NO_PENDING_CONFIRMATION = "NO_PENDING_CONFIRMATION"
    CONFIRMATION_CONTEXT_MISMATCH = "CONFIRMATION_CONTEXT_MISMATCH"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Resultado de uma invocação de tool.

    `ok=False` cobre tanto recusa de guarda quanto erro de domínio: para a
    orquestração, os dois significam "o efeito pretendido não aconteceu", e é
    `code` que distingue o motivo. O que **nunca** acontece é o inverso —
    exceção desconhecida jamais produz `ok=True` (§20).
    """

    ok: bool
    result_type: ResultType
    code: str
    data: ToolData = field(default_factory=dict)
    next_action: NextAction | None = None

    @classmethod
    def success(
        cls,
        result_type: ResultType,
        data: ToolData,
        *,
        next_action: NextAction | None = None,
    ) -> ToolResult:
        return cls(
            ok=True, result_type=result_type, code=OK_CODE, data=data, next_action=next_action
        )

    @classmethod
    def failure(
        cls,
        code: str,
        *,
        next_action: NextAction,
        result_type: ResultType = ResultType.ERROR,
        data: ToolData | None = None,
    ) -> ToolResult:
        return cls(
            ok=False,
            result_type=result_type,
            code=code,
            data=data if data is not None else {},
            next_action=next_action,
        )
