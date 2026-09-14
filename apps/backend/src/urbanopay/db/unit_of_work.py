"""Implementação SQLAlchemy do Unit of Work.

Fonte: ADR-012.

Implementa o port `urbanopay.core.persistence.UnitOfWork`. A camada de
aplicação depende do port; somente a composição da aplicação conhece esta
classe.

Semântica:

- `commit` é sempre explícito;
- a saída do contexto executa `rollback` incondicional — o que já foi
  confirmado por `commit` permanece; qualquer trabalho pendente é desfeito.
  Isso cobre também o caso de trabalho iniciado **depois** do último commit;
- exceção dentro do contexto desfaz o trabalho pendente;
- a sessão é sempre fechada e devolvida ao pool na saída;
- repositories nunca executam commit: eles receberão a sessão desta classe
  quando existirem, e apenas participam da transação.

Nesta fase não existem repositories funcionais, portanto esta classe não
compõe nenhum. Quando o primeiro módulo de domínio ganhar persistência, um
Unit of Work daquele domínio estenderá esta implementação instanciando seus
repositories sobre `self._session`.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlAlchemyUnitOfWork:
    """Unit of Work sobre uma `AsyncSession`.

    Uma instância atende a uma unidade de trabalho por vez e nunca deve ser
    compartilhada entre tasks concorrentes — a mesma regra da sessão que ela
    encapsula.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        """Sessão ativa da unidade de trabalho.

        Uso restrito à infraestrutura: é por aqui que os futuros repositories
        participarão da transação. Nunca exponha a sessão a routers,
        `application` ou `domain`.
        """
        if self._session is None:
            raise RuntimeError(
                "Unit of Work fora de contexto: use 'async with' antes de acessar a sessão."
            )
        return self._session

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Unit of Work já está em uso: instâncias não são reentrantes.")
        self._session = self._session_factory()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self._session
        if session is None:  # pragma: no cover - defensivo
            return
        try:
            # Rollback incondicional: é no-op quando não há transação pendente
            # (por exemplo, logo após um commit), e desfaz qualquer trabalho
            # não confirmado — inclusive em caso de exceção.
            await session.rollback()
        finally:
            self._session = None
            await session.close()

    async def commit(self) -> None:
        """Confirma o trabalho pendente. Somente a camada de aplicação chama."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Desfaz o trabalho pendente sem encerrar a unidade de trabalho."""
        await self.session.rollback()
