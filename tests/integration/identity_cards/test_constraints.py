"""Constraints físicas da SPEC-002, violadas de propósito."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.identity_cards.conftest import FIXED_NOW, IdentityCardsTestData
from urbanopay.modules.cards.infrastructure.models import CardModel
from urbanopay.modules.identity.infrastructure.models import (
    AuthChallengeModel,
    CustomerModel,
    SessionModel,
)

LATER = FIXED_NOW + timedelta(minutes=30)


async def _expect_violation(
    session_factory: async_sessionmaker[AsyncSession],
    instance: object,
    constraint: str,
) -> None:
    async with session_factory() as session:
        session.add(instance)
        with pytest.raises(IntegrityError) as excinfo:
            await session.commit()
        await session.rollback()
    assert constraint in str(excinfo.value)


def _customer(**overrides: object) -> CustomerModel:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Teste Constraint",
        "cpf_hash": f"hash-{uuid.uuid4()}",
        "status": "ACTIVE",
        "created_at": FIXED_NOW,
        "updated_at": FIXED_NOW,
    }
    values.update(overrides)
    return CustomerModel(**values)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cpf_hash_e_unico(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await data.add_customer(name="Original", cpf="90190190190")
    duplicated = _customer(
        cpf_hash=(await _existing_cpf_hash(session_factory, "Original")),
    )
    await _expect_violation(session_factory, duplicated, "uq_customers_cpf_hash")


async def _existing_cpf_hash(session_factory: async_sessionmaker[AsyncSession], name: str) -> str:
    import sqlalchemy as sa

    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(CustomerModel.cpf_hash).where(CustomerModel.name == name)
            )
        ).scalar_one()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"status": "DELETED"}, "ck_customers_status_valid", id="status-invalido"),
        pytest.param({"name": "   "}, "ck_customers_name_not_blank", id="nome-em-branco"),
    ],
)
async def test_constraints_de_customers(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
    overrides: dict[str, object],
    constraint: str,
) -> None:
    await _expect_violation(session_factory, _customer(**overrides), constraint)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sessao_autenticada_exige_customer(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Invariante física: authenticated=true sem customer é impossível."""
    orphan = SessionModel(
        id=uuid.uuid4(),
        customer_id=None,
        authenticated=True,
        created_at=FIXED_NOW,
        expires_at=LATER,
    )
    await _expect_violation(session_factory, orphan, "ck_sessions_authenticated_has_customer")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expiracao_da_sessao_apos_criacao(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    invalid = SessionModel(
        id=uuid.uuid4(),
        customer_id=None,
        authenticated=False,
        created_at=LATER,
        expires_at=FIXED_NOW,
    )
    await _expect_violation(session_factory, invalid, "ck_sessions_expiry_after_creation")


def _challenge(
    customer_id: uuid.UUID, session_id: uuid.UUID, **overrides: object
) -> AuthChallengeModel:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "customer_id": customer_id,
        "session_id": session_id,
        "otp_hash": "hash-ficticio",
        "expires_at": LATER,
        "attempts": 0,
        "max_attempts": 5,
        "status": "PENDING",
        "created_at": FIXED_NOW,
    }
    values.update(overrides)
    return AuthChallengeModel(**values)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_constraints_de_challenges_e_unico_pending(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    customer_id = await data.add_customer(name="Dono do Challenge", cpf="90290290290")
    session_id = uuid.uuid4()
    async with session_factory() as db:
        db.add(
            SessionModel(
                id=session_id,
                customer_id=None,
                authenticated=False,
                created_at=FIXED_NOW,
                expires_at=LATER,
            )
        )
        await db.commit()
    data.track_session(session_id)

    # attempts > max_attempts
    await _expect_violation(
        session_factory,
        _challenge(customer_id, session_id, attempts=6, status="BLOCKED"),
        "ck_auth_challenges_attempts_within_max",
    )
    # max_attempts = 0
    await _expect_violation(
        session_factory,
        _challenge(customer_id, session_id, max_attempts=0),
        "ck_auth_challenges_max_attempts_positive",
    )
    # status inválido
    await _expect_violation(
        session_factory,
        _challenge(customer_id, session_id, status="USED"),
        "ck_auth_challenges_status_valid",
    )

    # Último recurso de integridade: dois PENDING na mesma sessão por escrita
    # direta (contornando o lock da aplicação) → índice único parcial.
    async with session_factory() as db:
        db.add(_challenge(customer_id, session_id))
        await db.commit()
    await _expect_violation(
        session_factory,
        _challenge(customer_id, session_id),
        "uq_auth_challenges_pending_session",
    )


def _card(customer_id: uuid.UUID, **overrides: object) -> CardModel:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "customer_id": customer_id,
        "card_last4": "9999",
        "fare_profile": "INTEGRAL",
        "balance": Decimal("1.00"),
        "status": "ACTIVE",
        "expires_at": None,
        "created_at": FIXED_NOW,
        "updated_at": FIXED_NOW,
    }
    values.update(overrides)
    return CardModel(**values)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"card_last4": "12a4"}, "ck_cards_last4_format", id="last4-com-letra"),
        pytest.param({"card_last4": "123"}, "ck_cards_last4_format", id="last4-curto"),
        pytest.param({"fare_profile": "GRATUITO"}, "ck_cards_profile_valid", id="perfil-invalido"),
        pytest.param({"status": "LOST"}, "ck_cards_status_valid", id="status-invalido"),
        pytest.param(
            {"balance": Decimal("-0.01")}, "ck_cards_balance_non_negative", id="saldo-negativo"
        ),
    ],
)
async def test_constraints_de_cards(
    data: IdentityCardsTestData,
    session_factory: async_sessionmaker[AsyncSession],
    overrides: dict[str, object],
    constraint: str,
) -> None:
    customer_id = await data.add_customer(name="Dono do Cartao", cpf="90390390390")
    await _expect_violation(session_factory, _card(customer_id, **overrides), constraint)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_card_exige_customer_valido(
    migrated: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FK física: cartão sem customer existente é impossível."""
    await _expect_violation(session_factory, _card(uuid.uuid4()), "fk_cards_customer_id_customers")
