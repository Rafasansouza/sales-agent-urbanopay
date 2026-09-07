"""Prova de que dados sensíveis não vazam por repr, erros ou logs (SPEC-002 §12)."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from tests.unit.identity.fakes import (
    FIXED_NOW,
    FIXED_OTP,
    MARIANA_CPF,
    TEST_SECRET,
    FakeIdentityUnitOfWork,
    FakeOtpGenerator,
    make_customer,
    test_hasher,
)
from urbanopay.modules.identity.application.services import (
    AuthenticationService,
    SessionService,
)
from urbanopay.modules.identity.domain.entities import OTPChallenge
from urbanopay.modules.identity.domain.enums import ChallengeStatus
from urbanopay.modules.identity.domain.errors import (
    AuthenticationChallengeNotFoundError,
    NotAuthenticatedError,
    SessionExpiredError,
    SessionNotFoundError,
)

SENSITIVE_VALUES = (MARIANA_CPF, FIXED_OTP, TEST_SECRET)


@pytest.mark.unit
def test_repr_de_customer_nao_expoe_cpf_hash() -> None:
    customer = make_customer()
    rendered = repr(customer)
    assert customer.cpf_hash not in rendered
    assert MARIANA_CPF not in rendered


@pytest.mark.unit
def test_repr_de_challenge_nao_expoe_otp_hash() -> None:
    import uuid

    hasher = test_hasher()
    challenge_id = uuid.uuid4()
    challenge = OTPChallenge(
        id=challenge_id,
        customer_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        otp_hash=hasher.hash_otp(challenge_id, FIXED_OTP),
        expires_at=FIXED_NOW,
        attempts=0,
        max_attempts=5,
        status=ChallengeStatus.PENDING,
        created_at=FIXED_NOW,
    )
    rendered = repr(challenge)
    assert challenge.otp_hash not in rendered
    assert FIXED_OTP not in rendered


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        SessionNotFoundError(),
        SessionExpiredError(),
        NotAuthenticatedError(),
        AuthenticationChallengeNotFoundError(),
    ],
    ids=lambda error: type(error).__name__,
)
def test_mensagens_de_erro_sem_pii(error: Exception) -> None:
    message = str(error)
    for sensitive in SENSITIVE_VALUES:
        assert sensitive not in message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fluxo_completo_nao_loga_segredos(caplog: pytest.LogCaptureFixture) -> None:
    """Executa o fluxo inteiro com captura de log em DEBUG: OTP, CPF, hash e
    segredo não podem aparecer em nenhum registro (SPEC-002 §4, §12)."""
    customer = make_customer()
    uow = FakeIdentityUnitOfWork([customer])
    sessions = SessionService(uow, session_ttl=timedelta(minutes=30))
    auth = AuthenticationService(
        uow,
        test_hasher(),
        FakeOtpGenerator(),
        otp_ttl=timedelta(minutes=5),
        otp_max_attempts=5,
        session_ttl=timedelta(minutes=30),
    )

    with caplog.at_level(logging.DEBUG):
        session = await sessions.create_anonymous_session(at=FIXED_NOW)
        started = await auth.start_authentication(session.id, MARIANA_CPF, at=FIXED_NOW)
        await auth.verify_otp(session.id, "000000", at=FIXED_NOW)
        await auth.verify_otp(session.id, FIXED_OTP, at=FIXED_NOW)

    assert started.challenge_id is not None
    stored_hash = uow.challenge_store[started.challenge_id].otp_hash
    for sensitive in (*SENSITIVE_VALUES, stored_hash, customer.cpf_hash):
        assert sensitive not in caplog.text
