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
from pydantic_settings import SettingsConfigDict

from urbanopay_database.config import DatabaseSettings


class AppEnv(StrEnum):
    """Ambiente de execução."""

    LOCAL = "local"
    TEST = "test"
    CI = "ci"


class LLMProviderName(StrEnum):
    """Providers de LLM previstos em ADR-010 e ADR-015.

    `FAKE` é o padrão para que o ambiente suba sem credencial alguma — é o que
    permite `docker compose up` funcionar num clone recém-feito.
    """

    FAKE = "fake"
    OPENAI = "openai"


class PaymentProviderName(StrEnum):
    """Providers de pagamento previstos em ADR-007.

    `FAKE` é o padrão; `MERCADOPAGO` opera exclusivamente em ambiente de teste.
    """

    FAKE = "fake"
    MERCADOPAGO = "mercadopago"


class Settings(DatabaseSettings):
    """Configuração da aplicação.

    **Herda** `DatabaseSettings` (ADR-017): os campos `POSTGRES_*` têm uma
    definição só, no pacote mais baixo, e o backend acrescenta o que é dele —
    aplicação, identidade, pedidos, agente, LLM, pagamento e telemetria.
    """

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

    # PostgreSQL vem de `DatabaseSettings` (ADR-017): definido uma única vez,
    # no pacote mais baixo.

    # --- Identity & Cards (SPEC-002) ---
    # Segredo do HMAC usado para derivar identificadores de lookup (CPF) e
    # proteger hashes de OTP. Sem default utilizável; valor vem do ambiente ou
    # do `.env` local — em CI/local, somente valores fictícios.
    #
    # ⚠️ Rotação futura deste segredo exige estratégia de migração dos
    # identificadores derivados (todos os cpf_hash mudam) — decisão documental
    # antes de rotacionar.
    identity_hash_secret: SecretStr = SecretStr("")

    # TTLs e limites com os defaults sugeridos pela SPEC-002 §2, configuráveis.
    session_ttl_minutes: int = 30
    otp_ttl_minutes: int = 5
    otp_max_attempts: int = 5

    # --- Orders & Payments (SPEC-003) ---
    # TTLs com os defaults que a SPEC-003 §4 e §5.1 fixam, configuráveis.
    # Não há TTL após a confirmação do cliente, por decisão documentada: os
    # valores estão congelados, `REQUIRES_APPROVAL` pode aguardar decisão
    # humana e `CONFIRMED` pode aguardar a criação do Payment.
    quote_ttl_minutes: int = 10
    order_draft_ttl_minutes: int = 10

    # --- Agente conversacional (SPEC-004, ADR-014) ---
    # TTL da conversa, deslizante e avaliado na leitura. Nenhum documento de
    # produto fixa este número: é parâmetro de retenção, não regra de negócio.
    # 24h cobre o cliente que paga o Pix e volta depois, sem reter contexto
    # indefinidamente (ADR-014, D-3).
    conversation_ttl_minutes: int = 1440
    # Tetos de SPEC-004 §14 que possuem consumidor nesta etapa.
    max_tool_calls_per_turn: int = 5
    max_llm_calls_per_turn: int = 4

    # --- LLM (ADR-010, ADR-015) ---
    # O acesso em runtime sempre passa por uma abstração de provider. Nenhum
    # node instancia SDK diretamente.
    llm_provider: LLMProviderName = LLMProviderName.FAKE
    # ⚠️ Credencial: vive exclusivamente no backend. `SecretStr` impede que ela
    # apareça em repr, log ou trace. Nunca é enviada a HTML, JavaScript,
    # browser, resposta HTTP, estado do grafo, ConversationState, PostgreSQL,
    # telemetria ou ToolResult (ADR-015).
    openai_api_key: SecretStr = SecretStr("")
    # O modelo nunca é hardcoded no código (ADR-015).
    openai_model: str = "gpt-5.6-luna"

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

    def require_llm_credentials(self) -> None:
        """Valida a credencial do provider selecionado (ADR-015).

        Falha **explícita** e sem fallback silencioso para o Fake: um fallback
        faria uma demonstração parecer real enquanto responde por regra fixa, e
        tornaria indistinguível "configurei errado" de "está funcionando".

        A mensagem nunca imprime parte alguma da chave.
        """
        if self.llm_provider is not LLMProviderName.OPENAI:
            return
        if not self.openai_api_key.get_secret_value().strip():
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devolve a configuração da aplicação, resolvida uma única vez.

    Usada como dependência do FastAPI para manter a injeção explícita.
    """
    return Settings()
