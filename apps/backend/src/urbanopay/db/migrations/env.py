"""Ambiente do Alembic.

Fonte: ADR-012.

- O metadata alvo vem de `urbanopay.db.registry`, que agrega os models de
  todos os módulos de domínio (hoje: nenhum).
- A URL vem das mesmas `Settings` do runtime (variáveis `POSTGRES_*`) — uma
  única fonte de configuração, sem credencial em arquivo.
- O engine é **síncrono**, conforme o ADR permite para o Alembic; o mesmo
  drivername `postgresql+psycopg` atende os dois modos.
- `include_schemas=False`: o Alembic compara apenas o schema default. Isso
  também isola os schemas descartáveis criados por testes de integração.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from urbanopay.core.config import Settings
from urbanopay.db.engine import build_database_url
from urbanopay.db.registry import target_metadata

metadata = target_metadata()


def _database_url() -> str:
    """URL derivada da fonte canônica POSTGRES_*.

    `render_as_string(hide_password=False)` é necessário porque o Alembic
    recebe a URL como string; ela nunca é logada por este módulo.
    """
    settings = Settings()
    return build_database_url(settings).render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    """Modo offline: gera SQL sem conectar (`alembic upgrade --sql`).

    Permite revisão humana do SQL exato antes de aplicar (ADR-012).
    """
    context.configure(
        url=_database_url(),
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo online: aplica migrations conectado ao banco."""
    engine = create_engine(_database_url())

    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=metadata,
                compare_type=True,
                compare_server_default=True,
                include_schemas=False,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
