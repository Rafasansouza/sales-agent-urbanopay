"""Ciclo de vida da sessão anônima e autenticada (SPEC-002 §2, §9)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.unit.identity.fakes import FIXED_NOW, FakeIdentityUnitOfWork, make_customer
from urbanopay.modules.identity.application.services import SessionService
from urbanopay.modules.identity.domain.errors import (
    NotAuthenticatedError,
    SessionExpiredError,
    SessionNotFoundError,
)
from urbanopay.modules.identity.domain.services import authenticate_session

TTL = timedelta(minutes=30)


def make_service(uow: FakeIdentityUnitOfWork) -> SessionService:
    return SessionService(uow, session_ttl=TTL)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sessao_anonima_nasce_sem_customer() -> None:
    uow = FakeIdentityUnitOfWork()
    session = await make_service(uow).create_anonymous_session(at=FIXED_NOW)

    assert session.authenticated is False
    assert session.customer_id is None
    assert session.expires_at == FIXED_NOW + TTL
    assert uow.session_store[session.id] == session
    assert uow.commits == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_status_de_sessao_anonima() -> None:
    uow = FakeIdentityUnitOfWork()
    service = make_service(uow)
    session = await service.create_anonymous_session(at=FIXED_NOW)

    status = await service.get_authentication_status(session.id, at=FIXED_NOW)
    assert status.authenticated is False
    assert status.customer_id is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sessao_inexistente() -> None:
    import uuid

    uow = FakeIdentityUnitOfWork()
    with pytest.raises(SessionNotFoundError) as excinfo:
        await make_service(uow).get_authentication_status(uuid.uuid4(), at=FIXED_NOW)
    assert excinfo.value.code == "SESSION_NOT_FOUND"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sessao_expirada() -> None:
    uow = FakeIdentityUnitOfWork()
    service = make_service(uow)
    session = await service.create_anonymous_session(at=FIXED_NOW)

    with pytest.raises(SessionExpiredError) as excinfo:
        await service.get_authentication_status(session.id, at=FIXED_NOW + TTL)
    assert excinfo.value.code == "SESSION_EXPIRED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_operacao_protegida_exige_autenticacao() -> None:
    """Matriz de §9: sessão anônima não passa pelo portão determinístico."""
    uow = FakeIdentityUnitOfWork()
    service = make_service(uow)
    session = await service.create_anonymous_session(at=FIXED_NOW)

    with pytest.raises(NotAuthenticatedError) as excinfo:
        await service.require_authenticated(session.id, at=FIXED_NOW)
    assert excinfo.value.code == "NOT_AUTHENTICATED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_authenticated_resolve_customer_e_desliza_janela() -> None:
    uow = FakeIdentityUnitOfWork()
    service = make_service(uow)
    session = await service.create_anonymous_session(at=FIXED_NOW)

    customer = make_customer()
    uow.session_store[session.id] = authenticate_session(session, customer.id, FIXED_NOW, TTL)

    later = FIXED_NOW + timedelta(minutes=20)
    resolved = await service.require_authenticated(session.id, at=later)

    assert resolved.customer_id == customer.id
    assert resolved.session_id == session.id
    # Janela deslizante: a atividade renovou a expiração (§2: inatividade).
    assert uow.session_store[session.id].expires_at == later + TTL


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_authenticated_nao_renova_sessao_expirada() -> None:
    """Sessão expirada falha ANTES de qualquer renovação: o `expires_at`
    permanece intacto — expiração nunca é desfeita por tentativa de uso."""
    uow = FakeIdentityUnitOfWork()
    service = make_service(uow)
    session = await service.create_anonymous_session(at=FIXED_NOW)

    customer = make_customer()
    uow.session_store[session.id] = authenticate_session(session, customer.id, FIXED_NOW, TTL)
    original_expiry = uow.session_store[session.id].expires_at

    with pytest.raises(SessionExpiredError):
        await service.require_authenticated(session.id, at=original_expiry)

    assert uow.session_store[session.id].expires_at == original_expiry


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mesmo_session_id_apos_autenticacao() -> None:
    """Decisão aprovada: o ID da sessão não muda ao autenticar (MVP).

    O risco de session fixation está registrado como evolução futura.
    """
    uow = FakeIdentityUnitOfWork()
    service = make_service(uow)
    session = await service.create_anonymous_session(at=FIXED_NOW)

    customer = make_customer()
    authenticated = authenticate_session(session, customer.id, FIXED_NOW, TTL)

    assert authenticated.id == session.id
    assert authenticated.authenticated is True
    assert authenticated.customer_id == customer.id
