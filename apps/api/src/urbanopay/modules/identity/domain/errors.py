"""Erros semânticos do domínio de identidade.

Erros puros: código estável + mensagem, sem HTTP e sem PII. A SPEC-002 não
enumera uma taxonomia completa de erros (diferente da SPEC-001 §11); os
códigos abaixo são o conjunto mínimo aprovado no plano da SPEC-002.

Distinção deliberada: credencial incorreta ESPERADA (OTP errado, CPF não
encontrado) é resultado tipado de fluxo (`results.py`), nunca exceção — a
SPEC-002 §3 os define como resultados.
"""

from __future__ import annotations

from typing import ClassVar


class IdentityError(Exception):
    """Base dos erros de identidade. Mensagens nunca contêm PII."""

    code: ClassVar[str]
    default_message: ClassVar[str]

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class SessionNotFoundError(IdentityError):
    code = "SESSION_NOT_FOUND"
    default_message = "Sessão inexistente."


class SessionExpiredError(IdentityError):
    code = "SESSION_EXPIRED"
    default_message = "Sessão expirada."


class NotAuthenticatedError(IdentityError):
    code = "NOT_AUTHENTICATED"
    default_message = "A operação exige sessão autenticada."


class AuthenticationChallengeNotFoundError(IdentityError):
    code = "AUTHENTICATION_CHALLENGE_NOT_FOUND"
    default_message = "Não há desafio de autenticação pendente para a sessão."
