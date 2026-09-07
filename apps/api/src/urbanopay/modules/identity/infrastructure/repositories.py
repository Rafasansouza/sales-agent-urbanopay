"""Repositories SQLAlchemy do módulo identity (ADR-012).

Regras: API 2.0 explícita; devolvem entidades de domínio; nunca comitam;
nenhuma exceção carrega PII; `FOR UPDATE` onde o port exige lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from urbanopay.modules.identity.domain.entities import Customer, OTPChallenge, Session
from urbanopay.modules.identity.domain.enums import ChallengeStatus, CustomerStatus
from urbanopay.modules.identity.infrastructure.models import (
    AuthChallengeModel,
    CustomerModel,
    SessionModel,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def _to_customer(model: CustomerModel) -> Customer:
    return Customer(
        id=model.id,
        name=model.name,
        cpf_hash=model.cpf_hash,
        status=CustomerStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_session(model: SessionModel) -> Session:
    return Session(
        id=model.id,
        customer_id=model.customer_id,
        authenticated=model.authenticated,
        created_at=model.created_at,
        expires_at=model.expires_at,
    )


def _to_challenge(model: AuthChallengeModel) -> OTPChallenge:
    return OTPChallenge(
        id=model.id,
        customer_id=model.customer_id,
        session_id=model.session_id,
        otp_hash=model.otp_hash,
        expires_at=model.expires_at,
        attempts=model.attempts,
        max_attempts=model.max_attempts,
        status=ChallengeStatus(model.status),
        created_at=model.created_at,
    )


class SqlAlchemySessionRepository:
    """Implementação do port `SessionRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, session: Session) -> None:
        self._session.add(
            SessionModel(
                id=session.id,
                customer_id=session.customer_id,
                authenticated=session.authenticated,
                created_at=session.created_at,
                expires_at=session.expires_at,
            )
        )
        await self._session.flush()

    async def get(self, session_id: UUID) -> Session | None:
        model = await self._session.get(SessionModel, session_id)
        return _to_session(model) if model is not None else None

    async def get_for_update(self, session_id: UUID) -> Session | None:
        stmt = sa.select(SessionModel).where(SessionModel.id == session_id).with_for_update()
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_session(model) if model is not None else None

    async def update(self, session: Session) -> None:
        await self._session.execute(
            sa.update(SessionModel)
            .where(SessionModel.id == session.id)
            .values(
                customer_id=session.customer_id,
                authenticated=session.authenticated,
                expires_at=session.expires_at,
            )
        )


class SqlAlchemyCustomerRepository:
    """Implementação do port `CustomerRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_cpf_hash(self, cpf_hash: str) -> Customer | None:
        stmt = sa.select(CustomerModel).where(CustomerModel.cpf_hash == cpf_hash)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_customer(model) if model is not None else None

    async def get(self, customer_id: UUID) -> Customer | None:
        model = await self._session.get(CustomerModel, customer_id)
        return _to_customer(model) if model is not None else None


class SqlAlchemyAuthChallengeRepository:
    """Implementação do port `AuthChallengeRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, challenge: OTPChallenge) -> None:
        self._session.add(
            AuthChallengeModel(
                id=challenge.id,
                customer_id=challenge.customer_id,
                session_id=challenge.session_id,
                otp_hash=challenge.otp_hash,
                expires_at=challenge.expires_at,
                attempts=challenge.attempts,
                max_attempts=challenge.max_attempts,
                status=challenge.status.value,
                created_at=challenge.created_at,
            )
        )
        await self._session.flush()

    async def get_pending_for_session_for_update(self, session_id: UUID) -> OTPChallenge | None:
        stmt = (
            sa.select(AuthChallengeModel)
            .where(
                AuthChallengeModel.session_id == session_id,
                AuthChallengeModel.status == ChallengeStatus.PENDING.value,
            )
            .with_for_update()
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_challenge(model) if model is not None else None

    async def expire_pending_for_session(self, session_id: UUID) -> None:
        await self._session.execute(
            sa.update(AuthChallengeModel)
            .where(
                AuthChallengeModel.session_id == session_id,
                AuthChallengeModel.status == ChallengeStatus.PENDING.value,
            )
            .values(status=ChallengeStatus.EXPIRED.value)
        )

    async def update(self, challenge: OTPChallenge) -> None:
        await self._session.execute(
            sa.update(AuthChallengeModel)
            .where(AuthChallengeModel.id == challenge.id)
            .values(attempts=challenge.attempts, status=challenge.status.value)
        )
