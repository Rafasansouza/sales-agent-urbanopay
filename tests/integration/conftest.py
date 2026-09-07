"""Fixtures da camada de integração — persistence foundation.

Requisitos de ambiente: PostgreSQL 17 no ar (`make up` / `.\\scripts\\dev.ps1 up`)
e variáveis `POSTGRES_*` definidas (ambiente ou `.env` local; na CI, o job as
fornece com credenciais fictícias).

Isolamento em relação ao Alembic: a tabela de sondagem vive em um **schema
descartável** (`it_foundation`) e em um `MetaData` **próprio dos testes** —
nunca em `Base.metadata`. Como o `env.py` compara apenas o schema default
(`include_schemas=False`), o `alembic check` não enxerga nada daqui, e nenhuma
tabela de teste pode vazar para migration.

A tabela `foundation_probe` não representa entidade de domínio: é uma sonda
genérica para validar driver, sessão, transação e naming convention.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import CheckConstraint, MetaData, Numeric, String, UniqueConstraint, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from urbanopay.core.config import Settings

# A convenção é IMPORTADA da produção — nunca copiada — para que teste e
# produção não possam divergir (ADR-012).
from urbanopay.db.base import NAMING_CONVENTION
from urbanopay.db.engine import create_engine_from_settings
from urbanopay.db.session import create_session_factory
from urbanopay.db.unit_of_work import SqlAlchemyUnitOfWork

PROBE_SCHEMA = "it_foundation"


class ProbeBase(DeclarativeBase):
    """Base exclusiva dos testes: metadata separado de `Base.metadata`."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION, schema=PROBE_SCHEMA)


class FoundationProbe(ProbeBase):
    """Sonda genérica de infraestrutura — não é entidade de domínio."""

    __tablename__ = "foundation_probe"
    __table_args__ = (
        UniqueConstraint("note"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2, asdecimal=True), index=True)
    note: Mapped[str | None] = mapped_column(String(50))


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Configuração vinda do ambiente. Nenhum default de senha utilizável."""
    return Settings()


@pytest_asyncio.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Engine assíncrono por teste, com dispose explícito."""
    eng = create_engine_from_settings(settings)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def uow(session_factory: async_sessionmaker[AsyncSession]) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory)


@pytest_asyncio.fixture
async def probe_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    """Cria o schema descartável com a sonda e o remove por completo no fim."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS it_foundation"))
        await conn.run_sync(ProbeBase.metadata.create_all)
    try:
        yield
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS it_foundation CASCADE"))
