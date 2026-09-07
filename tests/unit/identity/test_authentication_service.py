"""Fluxo de autenticação simulada (SPEC-002 §3, §4) com fakes em memória."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from tests.unit.identity.fakes import (
    FIXED_NOW,
    FIXED_OTP,
    MARIANA_CPF,
    FakeIdentityUnitOfWork,
    FakeOtpGenerator,
    make_customer,
    test_hasher,
)
from urbanopay.modules.identity.application.services import (
    AuthenticationService,
    SessionService,
)
from urbanopay.modules.identity.domain.entities import Customer, Session
from urbanopay.modules.identity.domain.enums import ChallengeStatus, CustomerStatus
from urbanopay.modules.identity.domain.errors import (
    AuthenticationChallengeNotFoundError,
    SessionExpiredError,
    SessionNotFoundError,
)
from urbanopay.modules.identity.domain.results import (
    IdentificationStatus,
    VerificationStatus,
)

SESSION_TTL = timedelta(minutes=30)
OTP_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5


def build(
    customers: list[Customer],
    *,
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[FakeIdentityUnitOfWork, SessionService, AuthenticationService]:
    uow = FakeIdentityUnitOfWork(customers)
    sessions = SessionService(uow, session_ttl=SESSION_TTL)
    auth = AuthenticationService(
        uow,
        test_hasher(),
        FakeOtpGenerator(),
        otp_ttl=OTP_TTL,
        otp_max_attempts=max_attempts,
        session_ttl=SESSION_TTL,
    )
    return uow, sessions, auth


async def anonymous(sessions: SessionService) -> Session:
    return await sessions.create_anonymous_session(at=FIXED_NOW)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fluxo_completo_de_autenticacao() -> None:
    customer = make_customer()
    uow, sessions, auth = build([customer])
    session = await anonymous(sessions)

    started = await auth.start_authentication(session.id, "111.222.333-44", at=FIXED_NOW)
    assert started.status is IdentificationStatus.CUSTOMER_FOUND
    assert started.challenge_id is not None
    assert started.challenge_expires_at == FIXED_NOW + OTP_TTL

    verified = await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)
    assert verified.status is VerificationStatus.AUTHENTICATED
    assert verified.customer_id == customer.id

    stored_session = uow.session_store[session.id]
    assert stored_session.authenticated is True
    assert stored_session.customer_id == customer.id

    stored_challenge = uow.challenge_store[started.challenge_id]
    assert stored_challenge.status is ChallengeStatus.VERIFIED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resultado_nao_carrega_otp() -> None:
    """O valor do OTP nunca aparece no resultado (exposição é H-12/SPEC-004)."""
    _uow, sessions, auth = build([make_customer()])
    session = await anonymous(sessions)

    started = await auth.start_authentication(session.id, MARIANA_CPF, at=FIXED_NOW)

    assert not hasattr(started, "otp")
    assert FIXED_OTP not in repr(started)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param("12345", IdentificationStatus.INVALID_DOCUMENT, id="formato-invalido"),
        pytest.param("99988877766", IdentificationStatus.CUSTOMER_NOT_FOUND, id="nao-encontrado"),
    ],
)
async def test_identificacao_sem_challenge(document: str, expected: IdentificationStatus) -> None:
    uow, sessions, auth = build([make_customer()])
    session = await anonymous(sessions)

    result = await auth.start_authentication(session.id, document, at=FIXED_NOW)

    assert result.status is expected
    assert result.challenge_id is None
    assert uow.challenge_store == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_customer_bloqueado() -> None:
    blocked = make_customer(cpf="22233344455", status=CustomerStatus.BLOCKED)
    _, sessions, auth = build([blocked])
    session = await anonymous(sessions)

    result = await auth.start_authentication(session.id, "22233344455", at=FIXED_NOW)
    assert result.status is IdentificationStatus.CUSTOMER_BLOCKED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_customer_inactive_responde_como_inexistente() -> None:
    """Decisão registrada: §3 não define resultado para INACTIVE; tratá-lo como
    ausente evita revelar o estado da conta."""
    inactive = make_customer(cpf="33344455566", status=CustomerStatus.INACTIVE)
    _, sessions, auth = build([inactive])
    session = await anonymous(sessions)

    result = await auth.start_authentication(session.id, "33344455566", at=FIXED_NOW)
    assert result.status is IdentificationStatus.CUSTOMER_NOT_FOUND


@pytest.mark.unit
@pytest.mark.asyncio
async def test_otp_incorreto_conta_tentativa() -> None:
    uow, sessions, auth = build([make_customer()])
    session = await anonymous(sessions)
    started = await auth.start_authentication(session.id, MARIANA_CPF, at=FIXED_NOW)
    assert started.challenge_id is not None

    result = await auth.verify_otp(session.id, "000000", at=FIXED_NOW)

    assert result.status is VerificationStatus.OTP_INVALID
    assert result.attempts_remaining == MAX_ATTEMPTS - 1
    assert uow.challenge_store[started.challenge_id].status is ChallengeStatus.PENDING


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maximo_de_tentativas_bloqueia_o_challenge() -> None:
    uow, sessions, auth = build([make_customer()], max_attempts=2)
    session = await anonymous(sessions)
    started = await auth.start_authentication(session.id, MARIANA_CPF, at=FIXED_NOW)
    assert started.challenge_id is not None

    first = await auth.verify_otp(session.id, "000000", at=FIXED_NOW)
    assert first.status is VerificationStatus.OTP_INVALID
    assert first.attempts_remaining == 1

    second = await auth.verify_otp(session.id, "000000", at=FIXED_NOW)
    assert second.status is VerificationStatus.CHALLENGE_BLOCKED
    assert uow.challenge_store[started.challenge_id].status is ChallengeStatus.BLOCKED

    # Bloqueado não é mais PENDING: nem o OTP correto autentica.
    with pytest.raises(AuthenticationChallengeNotFoundError):
        await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_otp_expirado() -> None:
    uow, sessions, auth = build([make_customer()])
    session = await anonymous(sessions)
    started = await auth.start_authentication(session.id, MARIANA_CPF, at=FIXED_NOW)
    assert started.challenge_id is not None

    result = await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW + OTP_TTL)

    assert result.status is VerificationStatus.OTP_EXPIRED
    assert uow.challenge_store[started.challenge_id].status is ChallengeStatus.EXPIRED
    assert uow.session_store[session.id].authenticated is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_otp_e_uso_unico() -> None:
    """SPEC-002 §4: uso único — o challenge consumido não autentica de novo."""
    _, sessions, auth = build([make_customer()])
    session = await anonymous(sessions)
    await auth.start_authentication(session.id, MARIANA_CPF, at=FIXED_NOW)
    await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)

    with pytest.raises(AuthenticationChallengeNotFoundError) as excinfo:
        await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)
    assert excinfo.value.code == "AUTHENTICATION_CHALLENGE_NOT_FOUND"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_sem_start() -> None:
    _, sessions, auth = build([make_customer()])
    session = await anonymous(sessions)

    with pytest.raises(AuthenticationChallengeNotFoundError):
        await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_novo_start_substitui_challenge_anterior() -> None:
    uow, sessions, auth = build([make_customer()])
    session = await anonymous(sessions)

    first = await auth.start_authentication(session.id, MARIANA_CPF, at=FIXED_NOW)
    second = await auth.start_authentication(
        session.id, MARIANA_CPF, at=FIXED_NOW + timedelta(minutes=1)
    )
    assert first.challenge_id is not None
    assert second.challenge_id is not None

    assert uow.challenge_store[first.challenge_id].status is ChallengeStatus.EXPIRED
    assert uow.challenge_store[second.challenge_id].status is ChallengeStatus.PENDING

    pending = [
        challenge
        for challenge in uow.challenge_store.values()
        if challenge.status is ChallengeStatus.PENDING
    ]
    assert len(pending) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sessao_invalida_no_fluxo() -> None:
    _, sessions, auth = build([make_customer()])
    session = await anonymous(sessions)

    with pytest.raises(SessionNotFoundError):
        await auth.start_authentication(uuid.uuid4(), MARIANA_CPF, at=FIXED_NOW)

    with pytest.raises(SessionExpiredError):
        await auth.start_authentication(session.id, MARIANA_CPF, at=FIXED_NOW + SESSION_TTL)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reautenticacao_por_fluxo_completo_revincula() -> None:
    """Re-autenticação via OTP completo é o mesmo caminho de confiança da
    primeira; atalhos (`authenticate_as`) é que são proibidos (§11)."""
    first = make_customer(cpf="11122233344")
    second = make_customer(name="Lucas Teste", cpf="55566677788")
    uow, sessions, auth = build([first, second])
    session = await anonymous(sessions)

    await auth.start_authentication(session.id, "11122233344", at=FIXED_NOW)
    await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)
    assert uow.session_store[session.id].customer_id == first.id

    await auth.start_authentication(session.id, "55566677788", at=FIXED_NOW)
    await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)
    assert uow.session_store[session.id].customer_id == second.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_determinismo() -> None:
    customer = make_customer()
    _, sessions_a, auth_a = build([customer])
    _, sessions_b, auth_b = build([customer])

    session_a = await anonymous(sessions_a)
    session_b = await anonymous(sessions_b)

    result_a = await auth_a.start_authentication(session_a.id, MARIANA_CPF, at=FIXED_NOW)
    result_b = await auth_b.start_authentication(session_b.id, MARIANA_CPF, at=FIXED_NOW)

    assert result_a.status is result_b.status is IdentificationStatus.CUSTOMER_FOUND
