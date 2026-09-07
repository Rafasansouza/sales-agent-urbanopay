"""Ports do domínio de identidade (ADR-012).

Contratos comuns:

- implementações devolvem entidades de domínio, nunca modelos ORM;
- implementações nunca executam commit — a fronteira transacional é do
  `IdentityUnitOfWork`, controlado pela aplicação;
- nenhuma exceção de repository carrega PII;
- ordem de lock global: `sessions` ANTES de `auth_challenges` (ADR-012 —
  ordem consistente para evitar deadlock).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from urbanopay.core.persistence import UnitOfWork

if TYPE_CHECKING:
    from uuid import UUID

    from urbanopay.modules.identity.domain.entities import Customer, OTPChallenge, Session


class SessionRepository(Protocol):
    """Persistência de sessões conversacionais."""

    async def add(self, session: Session) -> None: ...

    async def get(self, session_id: UUID) -> Session | None: ...

    async def get_for_update(self, session_id: UUID) -> Session | None:
        """Carrega a sessão com lock de linha (`SELECT ... FOR UPDATE`)."""
        ...

    async def update(self, session: Session) -> None: ...


class CustomerRepository(Protocol):
    """Consulta de clientes. Nenhuma operação de escrita nesta SPEC."""

    async def find_by_cpf_hash(self, cpf_hash: str) -> Customer | None: ...

    async def get(self, customer_id: UUID) -> Customer | None: ...


class AuthChallengeRepository(Protocol):
    """Persistência dos desafios de OTP."""

    async def add(self, challenge: OTPChallenge) -> None: ...

    async def get_pending_for_session_for_update(self, session_id: UUID) -> OTPChallenge | None:
        """Desafio PENDING da sessão, com lock de linha.

        Existe no máximo um (índice único parcial); o lock garante o consumo
        atômico do OTP.
        """
        ...

    async def expire_pending_for_session(self, session_id: UUID) -> None:
        """Marca como EXPIRED o desafio PENDING da sessão, se existir.

        Usado pelo supersede: um novo `start_authentication` substitui o
        desafio anterior, sob o lock da sessão.
        """
        ...

    async def update(self, challenge: OTPChallenge) -> None: ...


class OtpGenerator(Protocol):
    """Geração do código OTP simulado.

    O runtime usa geração criptograficamente aleatória (`secrets`); testes
    injetam um gerador determinístico. Não existe OTP fixo por configuração —
    isso criaria um caminho permanente de autenticação conhecido (decisão
    aprovada). A exposição do código na jornada demonstrativa é decisão
    pendente da SPEC-004 (H-12 em docs/OPEN-QUESTIONS.md).
    """

    def generate(self) -> str: ...


@runtime_checkable
class IdentityUnitOfWork(UnitOfWork, Protocol):
    """Fronteira transacional do módulo, com seus repositories.

    Estende o port transversal `core.persistence.UnitOfWork`; a aplicação
    nunca toca `AsyncSession`.
    """

    sessions: SessionRepository
    customers: CustomerRepository
    challenges: AuthChallengeRepository
