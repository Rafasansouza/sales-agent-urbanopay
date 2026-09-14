"""Lógica pura de decisão da autenticação — testável sem I/O.

As funções recebem entidades e devolvem novas entidades (imutabilidade via
`dataclasses.replace`) junto do desfecho tipado. A aplicação persiste os
resultados dentro da fronteira transacional.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from urbanopay.modules.identity.domain.enums import ChallengeStatus
from urbanopay.modules.identity.domain.results import VerificationStatus

if TYPE_CHECKING:
    from datetime import datetime, timedelta
    from uuid import UUID

    from urbanopay.modules.identity.domain.entities import OTPChallenge, Session
    from urbanopay.modules.identity.domain.value_objects import IdentityHasher


def evaluate_otp_attempt(
    challenge: OTPChallenge,
    provided_otp: str,
    hasher: IdentityHasher,
    at: datetime,
) -> tuple[VerificationStatus, OTPChallenge]:
    """Avalia uma tentativa de OTP e devolve o desfecho + challenge atualizado.

    Regras (SPEC-002 §2, §4):

    - expirado ⇒ `OTP_EXPIRED`, challenge vira `EXPIRED` (nenhuma tentativa
      é contabilizada);
    - hash correto ⇒ `AUTHENTICATED`, challenge vira `VERIFIED` (uso único);
    - hash incorreto ⇒ tentativa contabilizada; ao atingir `max_attempts` o
      challenge vira `BLOCKED`, senão permanece `PENDING`.

    Pré-condição: `challenge.status is PENDING` — o repositório só entrega
    desafios pendentes; qualquer outro estado aqui é bug.
    """
    if challenge.status is not ChallengeStatus.PENDING:
        raise ValueError(f"Challenge {challenge.id} não está PENDING ({challenge.status}).")

    if challenge.is_expired(at):
        return VerificationStatus.OTP_EXPIRED, replace(challenge, status=ChallengeStatus.EXPIRED)

    if hasher.verify_otp(challenge.id, provided_otp, challenge.otp_hash):
        return (
            VerificationStatus.AUTHENTICATED,
            replace(challenge, status=ChallengeStatus.VERIFIED),
        )

    attempts = challenge.attempts + 1
    if attempts >= challenge.max_attempts:
        return (
            VerificationStatus.CHALLENGE_BLOCKED,
            replace(challenge, attempts=attempts, status=ChallengeStatus.BLOCKED),
        )
    return VerificationStatus.OTP_INVALID, replace(challenge, attempts=attempts)


def authenticate_session(
    session: Session,
    customer_id: UUID,
    at: datetime,
    ttl: timedelta,
) -> Session:
    """Vincula o customer e autentica a MESMA sessão (decisão aprovada).

    Re-autenticação por fluxo completo de OTP é permitida e revincula o
    customer — é o mesmo caminho de confiança da primeira autenticação; o que
    a SPEC proíbe são atalhos (`authenticate_as`/`change_customer`, §11).
    """
    return replace(
        session,
        customer_id=customer_id,
        authenticated=True,
        expires_at=at + ttl,
    )


def touch_session(session: Session, at: datetime, ttl: timedelta) -> Session:
    """Renova a janela deslizante de inatividade (SPEC-002 §2)."""
    return replace(session, expires_at=at + ttl)
