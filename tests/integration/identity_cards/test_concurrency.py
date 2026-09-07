"""Concorrência real contra PostgreSQL: consumo atômico de OTP e supersede.

Cada tarefa concorrente usa engine e conexões próprios — os `SELECT ... FOR
UPDATE` do PostgreSQL serializam de verdade (foundation, estratégia de commits
reais).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.identity_cards.conftest import (
    FIXED_NOW,
    FIXED_OTP,
    IdentityCardsTestData,
    build_services,
)
from urbanopay.core.config import Settings
from urbanopay.db.engine import create_engine_from_settings
from urbanopay.db.session import create_session_factory
from urbanopay.modules.identity.application.services import AuthenticationService
from urbanopay.modules.identity.domain.errors import AuthenticationChallengeNotFoundError
from urbanopay.modules.identity.domain.results import VerificationResult, VerificationStatus
from urbanopay.modules.identity.domain.value_objects import IdentityHasher
from urbanopay.modules.identity.infrastructure.models import AuthChallengeModel, SessionModel


@pytest_asyncio.fixture
async def concurrent_auth_services(
    settings: Settings,
    hasher: IdentityHasher,
) -> AsyncIterator[tuple[AuthenticationService, AuthenticationService]]:
    """Dois serviços com engines independentes = duas conexões reais."""
    engine_a = create_engine_from_settings(settings)
    engine_b = create_engine_from_settings(settings)
    try:
        _, auth_a = build_services(create_session_factory(engine_a), hasher)
        _, auth_b = build_services(create_session_factory(engine_b), hasher)
        yield auth_a, auth_b
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verificacoes_simultaneas_consomem_o_challenge_uma_unica_vez(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
    concurrent_auth_services: tuple[AuthenticationService, AuthenticationService],
) -> None:
    """Duas `verify_otp` simultâneas com o OTP correto: exatamente UMA autentica.

    O lock Session→Challenge serializa; a segunda transação encontra o
    challenge já VERIFIED (não-PENDING) e falha com CHALLENGE_NOT_FOUND.
    """
    await data.add_customer(name="Concorrencia OTP", cpf="80180180180")
    sessions, auth = build_services(session_factory, hasher)
    session = await sessions.create_anonymous_session(at=FIXED_NOW)
    data.track_session(session.id)
    await auth.start_authentication(session.id, "80180180180", at=FIXED_NOW)

    auth_a, auth_b = concurrent_auth_services

    async def attempt(service: AuthenticationService) -> VerificationResult | str:
        try:
            return await service.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)
        except AuthenticationChallengeNotFoundError:
            return "CHALLENGE_NOT_FOUND"

    outcomes = await asyncio.gather(attempt(auth_a), attempt(auth_b))

    authenticated = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, VerificationResult)
        and outcome.status is VerificationStatus.AUTHENTICATED
    ]
    rejected = [outcome for outcome in outcomes if outcome == "CHALLENGE_NOT_FOUND"]

    assert len(authenticated) == 1, f"exatamente uma deve autenticar: {outcomes}"
    assert len(rejected) == 1

    # Estado final no banco: um único challenge, VERIFIED, e sessão autenticada.
    async with session_factory() as db:
        challenge_statuses = (
            (
                await db.execute(
                    sa.select(AuthChallengeModel.status).where(
                        AuthChallengeModel.session_id == session.id
                    )
                )
            )
            .scalars()
            .all()
        )
        stored_session = (
            await db.execute(sa.select(SessionModel).where(SessionModel.id == session.id))
        ).scalar_one()

    assert challenge_statuses == ["VERIFIED"]
    assert stored_session.authenticated is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_starts_simultaneos_terminam_com_um_unico_pending(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
    concurrent_auth_services: tuple[AuthenticationService, AuthenticationService],
) -> None:
    """Dois `start_authentication` simultâneos: o lock da sessão serializa —
    ambos concluem sem IntegrityError e o estado final tem no máximo um
    challenge PENDING (o índice único parcial fica como última defesa, não
    como mecanismo normal)."""
    await data.add_customer(name="Concorrencia Start", cpf="80280280280")
    sessions, _ = build_services(session_factory, hasher)
    session = await sessions.create_anonymous_session(at=FIXED_NOW)
    data.track_session(session.id)

    auth_a, auth_b = concurrent_auth_services

    results = await asyncio.gather(
        auth_a.start_authentication(session.id, "80280280280", at=FIXED_NOW),
        auth_b.start_authentication(session.id, "80280280280", at=FIXED_NOW),
    )
    assert all(result.challenge_id is not None for result in results)

    async with session_factory() as db:
        statuses = (
            (
                await db.execute(
                    sa.select(AuthChallengeModel.status).where(
                        AuthChallengeModel.session_id == session.id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert statuses.count("PENDING") == 1
    assert statuses.count("EXPIRED") == 1
    assert len(statuses) == 2
