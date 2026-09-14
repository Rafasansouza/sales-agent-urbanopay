"""Unit of Work do módulo identity, sobre a foundation (ADR-012).

Materializa o padrão previsto: o port `IdentityUnitOfWork` estende o port
transversal com os repositories do módulo, e esta implementação os monta
sobre a sessão interna da foundation — a aplicação nunca vê `AsyncSession`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from urbanopay.db.unit_of_work import SqlAlchemyUnitOfWork
from urbanopay.modules.identity.infrastructure.repositories import (
    SqlAlchemyAuthChallengeRepository,
    SqlAlchemyCustomerRepository,
    SqlAlchemySessionRepository,
)

if TYPE_CHECKING:
    from urbanopay.modules.identity.domain.ports import (
        AuthChallengeRepository,
        CustomerRepository,
        SessionRepository,
    )


class SqlAlchemyIdentityUnitOfWork(SqlAlchemyUnitOfWork):
    """UoW do identity: repositories disponíveis dentro do contexto.

    Semântica herdada da foundation: commit explícito; saída sem commit ou por
    exceção desfaz o trabalho pendente; sessão sempre liberada.
    """

    sessions: SessionRepository
    customers: CustomerRepository
    challenges: AuthChallengeRepository

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.sessions = SqlAlchemySessionRepository(self.session)
        self.customers = SqlAlchemyCustomerRepository(self.session)
        self.challenges = SqlAlchemyAuthChallengeRepository(self.session)
        return self
