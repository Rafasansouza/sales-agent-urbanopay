"""Configuração de banco (ADR-012, ADR-017).

Somente `POSTGRES_*`. Esta é a **única** definição desses campos no projeto: a
`Settings` da aplicação herda desta classe, de modo que não existem duas
verdades sobre como o banco é endereçado.

Vive aqui, e não em `apps/backend`, porque `urbanopay-database` é a camada mais
baixa — e o engine e o Alembic precisam da URL sem conhecer a configuração de
LLM, de pagamento ou do agente.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Fonte canônica de endereçamento do PostgreSQL.

    A URL do SQLAlchemy é **derivada** destes campos por `build_database_url`;
    não existe uma segunda fonte de verdade em forma de `DATABASE_URL`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "urbanopay"
    postgres_user: str = "urbanopay"
    # `SecretStr`: nunca aparece em repr, log ou trace. Sem default utilizável —
    # o valor vem do ambiente ou do `.env` local.
    postgres_password: SecretStr = SecretStr("")
