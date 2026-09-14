"""Resultados tipados dos fluxos de autenticação (SPEC-002 §3).

Credencial incorreta esperada é RESULTADO, não exceção: a SPEC define os
desfechos de identificação como resultados tipados, e as futuras tools
(SPEC-004) os devolverão ao agente. Exceções (`errors.py`) ficam para
violações de pré-condição (sessão inexistente/expirada etc.).

Nenhum resultado carrega OTP, CPF ou hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class IdentificationStatus(StrEnum):
    """Desfechos da identificação por documento (SPEC-002 §3)."""

    CUSTOMER_FOUND = "CUSTOMER_FOUND"
    CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
    INVALID_DOCUMENT = "INVALID_DOCUMENT"
    CUSTOMER_BLOCKED = "CUSTOMER_BLOCKED"


class VerificationStatus(StrEnum):
    """Desfechos da verificação de OTP."""

    AUTHENTICATED = "AUTHENTICATED"
    OTP_INVALID = "OTP_INVALID"
    OTP_EXPIRED = "OTP_EXPIRED"
    CHALLENGE_BLOCKED = "CHALLENGE_BLOCKED"


@dataclass(frozen=True, slots=True)
class StartAuthenticationResult:
    """Desfecho de `start_authentication`.

    `challenge_id`/`challenge_expires_at` presentes somente quando
    `CUSTOMER_FOUND`. O valor do OTP NUNCA está aqui — a exposição controlada
    para a jornada demonstrativa é decisão pendente da SPEC-004 (H-12).
    """

    status: IdentificationStatus
    challenge_id: UUID | None = None
    challenge_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Desfecho de `verify_otp`.

    `attempts_remaining` acompanha `OTP_INVALID`; `customer_id` acompanha
    `AUTHENTICATED`.
    """

    status: VerificationStatus
    attempts_remaining: int | None = None
    customer_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AuthenticationStatus:
    """Estado de autenticação da sessão (tool `get_authentication_status`)."""

    session_id: UUID
    authenticated: bool
    customer_id: UUID | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedCustomer:
    """Identidade resolvida de uma sessão autenticada.

    É o valor que a composição entrega aos módulos a jusante (`cards`) — um
    `customer_id` opaco, nunca a sessão nem dados pessoais.
    """

    session_id: UUID
    customer_id: UUID
