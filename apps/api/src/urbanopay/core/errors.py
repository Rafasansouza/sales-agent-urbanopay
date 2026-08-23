"""Envelope de erro da API.

Fonte: ADR-006 — "erros possuem `error.code` estável e `trace_id`", e "sem
stack traces/secrets em respostas".

Escopo desta camada: apenas o **formato** do erro e a classe base. Os códigos
de erro de domínio pertencem às SPECs e serão definidos nos módulos
correspondentes:

- SPEC-001 §11 — erros do Fare Engine;
- SPEC-002 §3 — resultados de identificação;
- SPEC-003 §16 — erros de Order e Payment.

Nenhum código de domínio é declarado aqui.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detalhe do erro exposto ao cliente.

    `code` é estável e destinado a consumo programático; `message` é destinada
    a leitura humana e nunca contém stack trace, query, secret ou PII.
    """

    code: str = Field(description="Código estável do erro, para consumo programático")
    message: str = Field(description="Mensagem legível, sem dado sensível")


class ErrorResponse(BaseModel):
    """Corpo padrão de resposta de erro da API.

    `trace_id` permite correlacionar a falha com traces e logs (ADR-008) sem
    expor detalhe interno.
    """

    error: ErrorDetail
    trace_id: str | None = Field(
        default=None,
        description="Identificador de correlação do trace, quando disponível",
    )


class AppError(Exception):
    """Erro de aplicação com código estável.

    Módulos de domínio devem derivar desta classe usando exclusivamente os
    códigos definidos em suas SPECs. Um código que não existe em documento
    aceito é invenção de regra e não deve ser criado.
    """

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    message: str = "Erro interno."

    def __init__(
        self,
        message: str | None = None,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        # `context` é destinado a log estruturado interno e nunca é serializado
        # na resposta HTTP. Não coloque PII nem secret aqui.
        self.context = context or {}
        super().__init__(self.message)

    def to_response(self, trace_id: str | None = None) -> ErrorResponse:
        return ErrorResponse(
            error=ErrorDetail(code=self.code, message=self.message),
            trace_id=trace_id,
        )
