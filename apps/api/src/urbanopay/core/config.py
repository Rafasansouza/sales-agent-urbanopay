"""Configuração da aplicação a partir de variáveis de ambiente.

Fonte: ADR-006 (injeção de dependência explícita), ADR-007, ADR-008, ADR-010.

Regras desta camada:

- nenhum valor de credencial aparece em log, em resposta HTTP ou em telemetria;
- nenhum valor de regra de negócio é definido aqui — limites de agente e TTLs de
  domínio pertencem às SPECs correspondentes e permanecem ausentes enquanto não
  houver decisão documentada (ver docs/OPEN-QUESTIONS.md);
- valores padrão são seguros: providers falsos e telemetria desligada.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    """Ambiente de execução."""

    LOCAL = "local"
    TEST = "test"
    CI = "ci"


class LLMProviderName(StrEnum):
    """Providers de LLM previstos em ADR-010.

    `FAKE` é o padrão para que o ambiente suba sem credencial alguma.
    """

    FAKE = "fake"
    ANTHROPIC = "anthropic"


class PaymentProviderName(StrEnum):
    """Providers de pagamento previstos em ADR-007.

    `FAKE` é o padrão; `MERCADOPAGO` opera exclusivamente em ambiente de teste.
    """

    FAKE = "fake"
    MERCADOPAGO = "mercadopago"


class Settings(BaseSettings):
    """Configuração carregada de variáveis de ambiente e de `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Aplicação ---
    app_env: AppEnv = AppEnv.LOCAL
    app_name: str = "urbanopay-api"
    log_level: str = "INFO"

    # --- PostgreSQL (ADR-004, ADR-012) ---
    # Fonte canônica de configuração do banco. A URL do SQLAlchemy é derivada
    # destes campos por `urbanopay.db.engine.build_database_url`; não existe
    # uma segunda fonte de verdade em forma de DATABASE_URL.
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "urbanopay"
    postgres_user: str = "urbanopay"
    # SecretStr: nunca aparece em repr, log ou trace. Sem default utilizável —
    # o valor vem do ambiente ou do `.env` local.
    postgres_password: SecretStr = SecretStr("")

    # --- LLM (ADR-010) ---
    # O acesso em runtime sempre passa por uma abstração de provider. Nenhum
    # node instancia SDK diretamente.
    llm_provider: LLMProviderName = LLMProviderName.FAKE
    llm_model: str = "claude-sonnet-5"

    # --- Pagamentos (ADR-007) ---
    # Somente ambiente de teste é suportado no MVP.
    payment_provider: PaymentProviderName = PaymentProviderName.FAKE

    # --- Observabilidade (ADR-008) ---
    # Desligada por padrão: outage de observabilidade nunca derruba o fluxo de
    # negócio, e a instrumentação chega junto com as SPECs.
    otel_enabled: bool = False
    otel_service_name: str = "urbanopay-api"
    langfuse_enabled: bool = Field(default=False)

    @property
    def is_local(self) -> bool:
        return self.app_env is AppEnv.LOCAL


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devolve a configuração da aplicação, resolvida uma única vez.

    Usada como dependência do FastAPI para manter a injeção explícita.
    """
    return Settings()
