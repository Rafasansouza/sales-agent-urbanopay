"""Fakes em memória do módulo identity.

Implementam os ports de `identity/domain/ports.py`, incluindo o
`IdentityUnitOfWork` — a aplicação é testada sem banco e sem `AsyncSession`.
Todos os dados são fictícios.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from urbanopay.modules.identity.domain.entities import Customer, OTPChallenge, Session
from urbanopay.modules.identity.domain.enums import ChallengeStatus, CustomerStatus
from urbanopay.modules.identity.domain.ports import (
    AuthChallengeRepository,
    CustomerRepository,
    SessionRepository,
)
from urbanopay.modules.identity.domain.value_objects import IdentityHasher

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)

# Segredo e credenciais 100% fictícios, exclusivos da suíte de testes.
TEST_SECRET = "test-identity-secret-fictional"  # noqa: S105 - fictício de teste
FIXED_OTP = "123456"
MARIANA_CPF = "11122233344"


def build_hasher() -> IdentityHasher:
    """Hasher com o segredo fictício da suíte.

    O nome **não** começa com `test_`: é helper, não teste. Com o prefixo, o
    pytest o coletava como caso de teste sem marcador — desselecionado em todo
    alvo e distorcendo a contagem da suíte.
    """
    return IdentityHasher(TEST_SECRET)


def make_customer(
    *,
    name: str = "Mariana Teste",
    cpf: str = MARIANA_CPF,
    status: CustomerStatus = CustomerStatus.ACTIVE,
    customer_id: uuid.UUID | None = None,
) -> Customer:
    return Customer(
        id=customer_id if customer_id is not None else uuid.uuid4(),
        name=name,
        cpf_hash=build_hasher().hash_cpf(cpf),
        status=status,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


class FakeOtpGenerator:
    """Gerador determinístico para testes reproduzíveis (sem backdoor runtime)."""

    def __init__(self, otp: str = FIXED_OTP) -> None:
        self._otp = otp

    def generate(self) -> str:
        return self._otp


class InMemorySessionRepository:
    def __init__(self, store: dict[uuid.UUID, Session]) -> None:
        self._store = store

    async def add(self, session: Session) -> None:
        self._store[session.id] = session

    async def get(self, session_id: uuid.UUID) -> Session | None:
        return self._store.get(session_id)

    async def get_for_update(self, session_id: uuid.UUID) -> Session | None:
        return self._store.get(session_id)

    async def update(self, session: Session) -> None:
        self._store[session.id] = session


class InMemoryCustomerRepository:
    def __init__(self, customers: list[Customer]) -> None:
        self._customers = list(customers)

    async def find_by_cpf_hash(self, cpf_hash: str) -> Customer | None:
        for customer in self._customers:
            if customer.cpf_hash == cpf_hash:
                return customer
        return None

    async def get(self, customer_id: uuid.UUID) -> Customer | None:
        for customer in self._customers:
            if customer.id == customer_id:
                return customer
        return None


class InMemoryAuthChallengeRepository:
    def __init__(self, store: dict[uuid.UUID, OTPChallenge]) -> None:
        self._store = store

    async def add(self, challenge: OTPChallenge) -> None:
        self._store[challenge.id] = challenge

    async def get_pending_for_session_for_update(
        self, session_id: uuid.UUID
    ) -> OTPChallenge | None:
        for challenge in self._store.values():
            if challenge.session_id == session_id and challenge.status is ChallengeStatus.PENDING:
                return challenge
        return None

    async def expire_pending_for_session(self, session_id: uuid.UUID) -> None:
        for challenge_id, challenge in self._store.items():
            if challenge.session_id == session_id and challenge.status is ChallengeStatus.PENDING:
                self._store[challenge_id] = replace(challenge, status=ChallengeStatus.EXPIRED)

    async def update(self, challenge: OTPChallenge) -> None:
        self._store[challenge.id] = challenge


class FakeIdentityUnitOfWork:
    """Fake do port `IdentityUnitOfWork` com commit rastreável."""

    # Anotações com os tipos dos PORTS: exigido pela tipagem estrutural do
    # Protocol (atributos mutáveis são invariantes).
    sessions: SessionRepository
    customers: CustomerRepository
    challenges: AuthChallengeRepository

    def __init__(self, customers: list[Customer] | None = None) -> None:
        self.session_store: dict[uuid.UUID, Session] = {}
        self.challenge_store: dict[uuid.UUID, OTPChallenge] = {}
        self.sessions = InMemorySessionRepository(self.session_store)
        self.customers = InMemoryCustomerRepository(customers or [])
        self.challenges = InMemoryAuthChallengeRepository(self.challenge_store)
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None
