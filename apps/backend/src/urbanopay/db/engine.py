"""Fábrica do engine assíncrono.

Fonte: ADR-012.

Regras:

- driver: psycopg 3, via dialeto `postgresql+psycopg`;
- configuração exclusivamente por `Settings` (variáveis `POSTGRES_*`);
- nenhuma credencial hardcoded;
- nenhum engine criado em import de módulo — sempre por fábrica, com
  injeção explícita (ADR-006);
- `echo` desligado por padrão;
- o chamador é dono do ciclo de vida: `await engine.dispose()` no shutdown.

⚠️ Windows: psycopg async exige um `SelectorEventLoop`. Garanta a política
compatível **antes** de criar o event loop — ver
`urbanopay.core.event_loop.ensure_selector_event_loop_policy`.
"""

from __future__ import annotations

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from urbanopay.core.config import Settings

# Mesmo drivername para engine síncrono (Alembic) e assíncrono (aplicação):
# o dialeto psycopg resolve o modo pelo tipo de engine criado.
DRIVER_NAME = "postgresql+psycopg"


class DatabaseConfigurationError(RuntimeError):
    """Configuração de banco ausente ou inválida.

    Nunca inclui o valor de credencial na mensagem.
    """


def build_database_url(settings: Settings) -> URL:
    """Deriva a URL SQLAlchemy da fonte canônica `POSTGRES_*`.

    `URL.create` escapa usuário e senha com segurança; nunca monte a URL por
    interpolação de string.
    """
    password = settings.postgres_password.get_secret_value()
    if not password:
        raise DatabaseConfigurationError(
            "POSTGRES_PASSWORD não configurado. Defina a variável de ambiente "
            "ou o .env local (ver .env.example)."
        )

    return URL.create(
        drivername=DRIVER_NAME,
        username=settings.postgres_user,
        password=password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )


def create_engine_from_settings(settings: Settings, *, echo: bool = False) -> AsyncEngine:
    """Cria o engine assíncrono da aplicação.

    O pooling é o do próprio SQLAlchemy (ADR-012 — sem `psycopg_pool`).
    `pool_pre_ping` descarta conexões mortas do pool antes do uso, o que evita
    erro espúrio após restart do PostgreSQL local.
    """
    return create_async_engine(
        build_database_url(settings),
        echo=echo,
        pool_pre_ping=True,
    )
