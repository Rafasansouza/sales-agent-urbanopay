"""Serviços de aplicação da identidade (SPEC-002 §3, §4).

Orquestram os ports dentro da fronteira transacional (`IdentityUnitOfWork`);
commit sempre explícito; nenhum acesso a `AsyncSession`.

Regras transversais:

- o instante `now` é resolvido UMA vez por operação e usado em todas as
  verificações de expiração, renovações e criações;
- ordem de lock: Session ANTES de OTPChallenge;
- nada aqui registra ou expõe OTP, CPF, hashes ou segredo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from urbanopay.modules.identity.domain.entities import OTPChallenge, Session
from urbanopay.modules.identity.domain.enums import ChallengeStatus, CustomerStatus
from urbanopay.modules.identity.domain.errors import (
    AuthenticationChallengeNotFoundError,
    NotAuthenticatedError,
    SessionExpiredError,
    SessionNotFoundError,
)
from urbanopay.modules.identity.domain.results import (
    AuthenticatedCustomer,
    AuthenticationStatus,
    IdentificationStatus,
    StartAuthenticationResult,
    VerificationResult,
    VerificationStatus,
)
from urbanopay.modules.identity.domain.services import (
    authenticate_session,
    evaluate_otp_attempt,
    touch_session,
)
from urbanopay.modules.identity.domain.value_objects import normalize_document

if TYPE_CHECKING:
    from urbanopay.modules.identity.domain.ports import IdentityUnitOfWork, OtpGenerator
    from urbanopay.modules.identity.domain.value_objects import IdentityHasher


def _now(at: datetime | None) -> datetime:
    reference = at if at is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        raise ValueError("O instante de referência deve ser timezone-aware.")
    return reference


class SessionService:
    """Ciclo de vida da sessão conversacional."""

    def __init__(self, uow: IdentityUnitOfWork, session_ttl: timedelta) -> None:
        self._uow = uow
        self._ttl = session_ttl

    async def create_anonymous_session(self, at: datetime | None = None) -> Session:
        """Cria a sessão anônima (PRD §8, passo 1)."""
        now = _now(at)
        session = Session(
            id=uuid.uuid4(),
            customer_id=None,
            authenticated=False,
            created_at=now,
            expires_at=now + self._ttl,
        )
        async with self._uow:
            await self._uow.sessions.add(session)
            await self._uow.commit()
        return session

    async def get_authentication_status(
        self, session_id: uuid.UUID, at: datetime | None = None
    ) -> AuthenticationStatus:
        """Estado da sessão, sem renovar a janela (consulta não é atividade)."""
        now = _now(at)
        async with self._uow:
            session = await self._uow.sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError
        if session.is_expired(now):
            raise SessionExpiredError
        return AuthenticationStatus(
            session_id=session.id,
            authenticated=session.authenticated,
            customer_id=session.customer_id,
            expires_at=session.expires_at,
        )

    async def require_authenticated(
        self, session_id: uuid.UUID, at: datetime | None = None
    ) -> AuthenticatedCustomer:
        """Resolve a identidade autenticada e renova a janela de inatividade.

        É o portão determinístico da matriz de autorização (§9): operação
        protegida sempre passa por aqui antes de tocar `cards` ou os módulos
        transacionais futuros.
        """
        now = _now(at)
        async with self._uow:
            session = await self._uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError
            if session.is_expired(now):
                raise SessionExpiredError
            if not session.authenticated or session.customer_id is None:
                raise NotAuthenticatedError

            await self._uow.sessions.update(touch_session(session, now, self._ttl))
            await self._uow.commit()

        return AuthenticatedCustomer(session_id=session.id, customer_id=session.customer_id)


class AuthenticationService:
    """Identificação por documento e verificação de OTP (SPEC-002 §3, §4)."""

    def __init__(
        self,
        uow: IdentityUnitOfWork,
        hasher: IdentityHasher,
        otp_generator: OtpGenerator,
        *,
        otp_ttl: timedelta,
        otp_max_attempts: int,
        session_ttl: timedelta,
    ) -> None:
        self._uow = uow
        self._hasher = hasher
        self._otp_generator = otp_generator
        self._otp_ttl = otp_ttl
        self._otp_max_attempts = otp_max_attempts
        self._session_ttl = session_ttl

    async def start_authentication(
        self,
        session_id: uuid.UUID,
        document: str,
        at: datetime | None = None,
    ) -> StartAuthenticationResult:
        """Identifica o cliente (§3) e cria o desafio de OTP (§4).

        Transação única sob lock da sessão: a serialização de chamadas
        concorrentes vem do lock, não do índice único parcial — que permanece
        apenas como última defesa de integridade.
        """
        now = _now(at)
        async with self._uow:
            session = await self._uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError
            if session.is_expired(now):
                raise SessionExpiredError

            # Qualquer uso da sessão é atividade: renova a janela.
            await self._uow.sessions.update(touch_session(session, now, self._session_ttl))

            normalized = normalize_document(document)
            if normalized is None:
                await self._uow.commit()
                return StartAuthenticationResult(status=IdentificationStatus.INVALID_DOCUMENT)

            customer = await self._uow.customers.find_by_cpf_hash(self._hasher.hash_cpf(normalized))
            # INACTIVE responde como inexistente: §3 não define resultado
            # próprio para INACTIVE, e tratá-lo como ausente evita revelar o
            # estado da conta (decisão registrada no plano aprovado).
            if customer is None or customer.status is CustomerStatus.INACTIVE:
                await self._uow.commit()
                return StartAuthenticationResult(status=IdentificationStatus.CUSTOMER_NOT_FOUND)
            if customer.status is CustomerStatus.BLOCKED:
                await self._uow.commit()
                return StartAuthenticationResult(status=IdentificationStatus.CUSTOMER_BLOCKED)

            # Supersede: o desafio anterior da sessão deixa de valer.
            await self._uow.challenges.expire_pending_for_session(session_id)

            challenge_id = uuid.uuid4()
            otp = self._otp_generator.generate()
            challenge = OTPChallenge(
                id=challenge_id,
                customer_id=customer.id,
                session_id=session_id,
                otp_hash=self._hasher.hash_otp(challenge_id, otp),
                expires_at=now + self._otp_ttl,
                attempts=0,
                max_attempts=self._otp_max_attempts,
                status=ChallengeStatus.PENDING,
                created_at=now,
            )
            await self._uow.challenges.add(challenge)
            await self._uow.commit()

        return StartAuthenticationResult(
            status=IdentificationStatus.CUSTOMER_FOUND,
            challenge_id=challenge.id,
            challenge_expires_at=challenge.expires_at,
        )

    async def verify_otp(
        self,
        session_id: uuid.UUID,
        otp: str,
        at: datetime | None = None,
    ) -> VerificationResult:
        """Consome o desafio pendente da sessão (§4) — uso único e atômico.

        Transação única com locks na ordem global: Session → OTPChallenge.
        Duas verificações simultâneas nunca autenticam com o mesmo desafio: a
        primeira o transiciona sob lock; a segunda não encontra PENDING.
        """
        now = _now(at)
        async with self._uow:
            session = await self._uow.sessions.get_for_update(session_id)
            if session is None:
                raise SessionNotFoundError
            if session.is_expired(now):
                raise SessionExpiredError

            challenge = await self._uow.challenges.get_pending_for_session_for_update(session_id)
            if challenge is None:
                raise AuthenticationChallengeNotFoundError

            status, updated_challenge = evaluate_otp_attempt(challenge, otp, self._hasher, now)
            await self._uow.challenges.update(updated_challenge)

            if status is VerificationStatus.AUTHENTICATED:
                await self._uow.sessions.update(
                    authenticate_session(session, challenge.customer_id, now, self._session_ttl)
                )
            else:
                # Tentativa falha ainda é atividade da sessão.
                await self._uow.sessions.update(touch_session(session, now, self._session_ttl))

            await self._uow.commit()

        if status is VerificationStatus.AUTHENTICATED:
            return VerificationResult(status=status, customer_id=challenge.customer_id)
        if status is VerificationStatus.OTP_INVALID:
            return VerificationResult(
                status=status, attempts_remaining=updated_challenge.attempts_remaining
            )
        return VerificationResult(status=status)
