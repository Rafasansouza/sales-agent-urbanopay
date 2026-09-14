"""Entidades do domínio de identidade (SPEC-002 §2).

Puras e imutáveis; mutações produzem cópias via `dataclasses.replace` nas
funções de `services.py`. Campos derivados de segredo (`cpf_hash`,
`otp_hash`) ficam fora do `repr` — nunca aparecem em log, erro ou trace.

Decisões aprovadas no plano:

- Customer sem `email`/`phone`: são campos conceituais de §2 sem consumidor
  nesta SPEC — minimização (§12);
- Customer armazena `cpf_hash` (HMAC), nunca o CPF;
- OTPChallenge possui `session_id` (além da lista conceitual da SPEC):
  necessário para associar o desafio à sessão, impedir uso cruzado e garantir
  consumo atômico.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from urbanopay.modules.identity.domain.enums import ChallengeStatus, CustomerStatus

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class Customer:
    """Cliente identificável por CPF (via HMAC) — SPEC-002 §2."""

    id: UUID
    name: str
    cpf_hash: str = field(repr=False)
    status: CustomerStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Session:
    """Sessão conversacional (SPEC-002 §2).

    Nasce anônima (`customer_id is None`, `authenticated=False`). Após o OTP,
    a MESMA sessão passa a autenticada — decisão aprovada: o ID não muda no
    MVP (risco de session fixation registrado como evolução futura em
    docs/OPEN-QUESTIONS.md).

    `expires_at` é janela deslizante: §2 fala em "30 minutos de INATIVIDADE" —
    atividade renova a expiração.
    """

    id: UUID
    customer_id: UUID | None
    authenticated: bool
    created_at: datetime
    expires_at: datetime

    def is_expired(self, at: datetime) -> bool:
        return self.expires_at <= at


@dataclass(frozen=True, slots=True)
class OTPChallenge:
    """Desafio de OTP simulado (SPEC-002 §2, §4).

    Uso único: `PENDING → VERIFIED` acontece no máximo uma vez, sob lock.
    """

    id: UUID
    customer_id: UUID
    session_id: UUID
    otp_hash: str = field(repr=False)
    expires_at: datetime
    attempts: int
    max_attempts: int
    status: ChallengeStatus
    created_at: datetime

    def is_expired(self, at: datetime) -> bool:
        return self.expires_at <= at

    @property
    def attempts_remaining(self) -> int:
        return max(self.max_attempts - self.attempts, 0)
