"""Fluxo de autenticação completo contra PostgreSQL real (SPEC-002 §3, §4, §14)."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.identity_cards.conftest import (
    FIXED_NOW,
    FIXED_OTP,
    IdentityCardsTestData,
    build_services,
)
from urbanopay.modules.identity.domain.errors import (
    AuthenticationChallengeNotFoundError,
    SessionExpiredError,
)
from urbanopay.modules.identity.domain.results import (
    IdentificationStatus,
    VerificationStatus,
)
from urbanopay.modules.identity.domain.value_objects import IdentityHasher
from urbanopay.modules.identity.infrastructure.models import AuthChallengeModel, SessionModel


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fluxo_completo_persistido(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
) -> None:
    """Anônima → identificação → OTP → autenticada, com estado real no banco."""
    customer_id = await data.add_customer(name="Mariana Fluxo", cpf="70170170170")
    sessions, auth = build_services(session_factory, hasher)

    session = await sessions.create_anonymous_session(at=FIXED_NOW)
    data.track_session(session.id)

    status = await sessions.get_authentication_status(session.id, at=FIXED_NOW)
    assert status.authenticated is False

    started = await auth.start_authentication(session.id, "701.701.701-70", at=FIXED_NOW)
    assert started.status is IdentificationStatus.CUSTOMER_FOUND

    verified = await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)
    assert verified.status is VerificationStatus.AUTHENTICATED
    assert verified.customer_id == customer_id

    # Estado persistido de verdade: sessão autenticada e challenge consumido.
    async with session_factory() as db:
        stored_session = (
            await db.execute(sa.select(SessionModel).where(SessionModel.id == session.id))
        ).scalar_one()
        stored_challenge = (
            await db.execute(
                sa.select(AuthChallengeModel).where(AuthChallengeModel.session_id == session.id)
            )
        ).scalar_one()

    assert stored_session.authenticated is True
    assert stored_session.customer_id == customer_id
    assert stored_challenge.status == "VERIFIED"

    resolved = await sessions.require_authenticated(session.id, at=FIXED_NOW)
    assert resolved.customer_id == customer_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_otp_errado_persiste_tentativas_e_bloqueia(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
) -> None:
    await data.add_customer(name="Bloqueio Teste", cpf="70270270270")
    sessions, auth = build_services(session_factory, hasher, otp_max_attempts=2)

    session = await sessions.create_anonymous_session(at=FIXED_NOW)
    data.track_session(session.id)
    await auth.start_authentication(session.id, "70270270270", at=FIXED_NOW)

    first = await auth.verify_otp(session.id, "000000", at=FIXED_NOW)
    assert first.status is VerificationStatus.OTP_INVALID
    assert first.attempts_remaining == 1

    second = await auth.verify_otp(session.id, "000000", at=FIXED_NOW)
    assert second.status is VerificationStatus.CHALLENGE_BLOCKED

    async with session_factory() as db:
        stored = (
            await db.execute(
                sa.select(AuthChallengeModel).where(AuthChallengeModel.session_id == session.id)
            )
        ).scalar_one()
    assert stored.status == "BLOCKED"
    assert stored.attempts == 2

    with pytest.raises(AuthenticationChallengeNotFoundError):
        await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_otp_expirado_contra_o_banco(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
) -> None:
    await data.add_customer(name="Expiracao Teste", cpf="70370370370")
    sessions, auth = build_services(session_factory, hasher)

    session = await sessions.create_anonymous_session(at=FIXED_NOW)
    data.track_session(session.id)
    await auth.start_authentication(session.id, "70370370370", at=FIXED_NOW)

    result = await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW + timedelta(minutes=5))
    assert result.status is VerificationStatus.OTP_EXPIRED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_supersede_persiste_um_unico_pending(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
) -> None:
    await data.add_customer(name="Supersede Teste", cpf="70470470470")
    sessions, auth = build_services(session_factory, hasher)

    session = await sessions.create_anonymous_session(at=FIXED_NOW)
    data.track_session(session.id)
    await auth.start_authentication(session.id, "70470470470", at=FIXED_NOW)
    await auth.start_authentication(session.id, "70470470470", at=FIXED_NOW + timedelta(minutes=1))

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
    assert sorted(statuses) == ["EXPIRED", "PENDING"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sessao_expirada_e_janela_deslizante(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
) -> None:
    await data.add_customer(name="Sessao Teste", cpf="70570570570")
    sessions, auth = build_services(session_factory, hasher)

    session = await sessions.create_anonymous_session(at=FIXED_NOW)
    data.track_session(session.id)

    # Atividade aos 20 min desliza a janela: aos 45 min a sessão segue viva...
    await auth.start_authentication(session.id, "70570570570", at=FIXED_NOW + timedelta(minutes=20))
    status = await sessions.get_authentication_status(
        session.id, at=FIXED_NOW + timedelta(minutes=45)
    )
    assert status.expires_at == FIXED_NOW + timedelta(minutes=50)

    # ...e expira depois da janela renovada.
    with pytest.raises(SessionExpiredError):
        await sessions.get_authentication_status(session.id, at=FIXED_NOW + timedelta(minutes=50))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_require_authenticated_renova_e_nao_renova_expirada(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
) -> None:
    """`require_authenticated` desliza a janela persistida (now + ttl) e uma
    sessão já expirada falha SEM renovação — contrato de §2 (inatividade)."""
    await data.add_customer(name="Renovacao Teste", cpf="70770770770")
    sessions, auth = build_services(session_factory, hasher)

    session = await sessions.create_anonymous_session(at=FIXED_NOW)
    data.track_session(session.id)
    await auth.start_authentication(session.id, "70770770770", at=FIXED_NOW)
    await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)

    # Renovação persistida: atividade aos 25 min ⇒ expires_at = 25 + 30 = 55.
    later = FIXED_NOW + timedelta(minutes=25)
    await sessions.require_authenticated(session.id, at=later)
    async with session_factory() as db:
        stored = (
            await db.execute(sa.select(SessionModel).where(SessionModel.id == session.id))
        ).scalar_one()
    assert stored.expires_at == later + timedelta(minutes=30)

    # Expirada não renova: falha e o expires_at persistido permanece intacto.
    expired_at = stored.expires_at
    with pytest.raises(SessionExpiredError):
        await sessions.require_authenticated(session.id, at=expired_at)
    async with session_factory() as db:
        untouched = (
            await db.execute(sa.select(SessionModel).where(SessionModel.id == session.id))
        ).scalar_one()
    assert untouched.expires_at == expired_at


@pytest.mark.integration
@pytest.mark.asyncio
async def test_challenge_nao_atravessa_sessoes(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: IdentityHasher,
) -> None:
    """Uso cruzado impedido: o challenge pertence à sessão que o iniciou."""
    await data.add_customer(name="Cruzado Teste", cpf="70670670670")
    sessions, auth = build_services(session_factory, hasher)

    session_a = await sessions.create_anonymous_session(at=FIXED_NOW)
    session_b = await sessions.create_anonymous_session(at=FIXED_NOW)
    data.track_session(session_a.id)
    data.track_session(session_b.id)

    await auth.start_authentication(session_a.id, "70670670670", at=FIXED_NOW)

    with pytest.raises(AuthenticationChallengeNotFoundError):
        await auth.verify_otp(session_b.id, FIXED_OTP, at=FIXED_NOW)
