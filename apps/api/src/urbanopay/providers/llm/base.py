"""Port e contratos do provider de LLM (ADR-010, ADR-015).

Um único port, duas implementações — `FakeLLMProvider` para testes e CI,
`OpenAILLMProvider` para runtime. `domain`, grafo e tools **não sabem** qual
está ativa, e **não existe caminho de negócio especial para o Fake**.

O que o modelo produz aqui é sempre **interpretação**, nunca autoridade. Um
`TurnUnderstanding` diz o que o cliente parece querer; quem decide se aquilo
existe, é válido e pode ser executado é o backend (ADR-005). Schema válido não
implica regra válida: a validação de domínio acontece depois do Pydantic.

Nada nestes contratos carrega CPF, OTP, hash, segredo, saldo, `fare_profile`
oficial, status de agregado ou valor monetário autoritativo.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Sequence


class AgentIntent(StrEnum):
    """Os dez intents do PRD §9 e da SPEC-004 §4.

    Nenhum intent novo é inventado aqui. Mensagem que não se encaixa vira
    `GENERAL_TRANSPORT_HELP`, que é exatamente o caso de uso dele.
    """

    DISCOVER_PRODUCT = "DISCOVER_PRODUCT"
    CALCULATE_TRIP_COST = "CALCULATE_TRIP_COST"
    CALCULATE_RECHARGE_NEED = "CALCULATE_RECHARGE_NEED"
    RECHARGE_CARD = "RECHARGE_CARD"
    BUY_TICKET = "BUY_TICKET"
    CHECK_BALANCE = "CHECK_BALANCE"
    CHECK_ORDER = "CHECK_ORDER"
    CHECK_PAYMENT = "CHECK_PAYMENT"
    CHECK_TICKET = "CHECK_TICKET"
    GENERAL_TRANSPORT_HELP = "GENERAL_TRANSPORT_HELP"


class ConfirmationDecision(StrEnum):
    """Leitura de uma resposta a pedido de confirmação (SPEC-004 §11).

    ⚠️ `CONFIRMED` **não confirma nada sozinho**. Ele só produz efeito se
    existir `pending_confirmation` no estado, e o Order confirmado é sempre o
    do contexto — nunca um escolhido pelo modelo (§9.1). Mensagem ambígua
    jamais dispara pagamento.
    """

    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"


class TripSegmentDraft(BaseModel):
    """Segmento extraído da fala do cliente, ainda não validado.

    "Draft" é literal: o Fare Engine é quem valida modo, linha e composição, e
    quem recusa com erro tipado. Nada aqui é preço.
    """

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(description="BUS ou METRO")
    line_code: str | None = Field(
        default=None, description="Codigo da linha de onibus; METRO nao possui linha"
    )


class TurnUnderstanding(BaseModel):
    """Interpretação estruturada de uma mensagem (SPEC-004 §5).

    Deliberadamente **sem** `card_id`, `order_id`, `quote_id`, `payment_id`,
    `amount` de pagamento, `balance`, `fare_profile` oficial, `customer_id`,
    `requires_approval` ou idempotency key: identificadores de operação crítica
    são derivados do contexto seguro, não propostos pelo modelo (§9.1).

    `recharge_amount` é a única grandeza monetária que entra pela conversa —
    por ser escolha do cliente (SPEC-003 §1.1) — e passa por schema **e** por
    validação de domínio antes de virar Quote.
    """

    model_config = ConfigDict(extra="forbid")

    intent: AgentIntent = AgentIntent.GENERAL_TRANSPORT_HELP
    segments: list[TripSegmentDraft] = Field(default_factory=list)
    declared_fare_profile: str | None = Field(
        default=None, description="INTEGRAL ou MEIA, quando o cliente declarar"
    )
    recharge_amount: str | None = Field(
        default=None, description="Valor da recarga como string decimal, ex '100.00'"
    )
    card_hint: str | None = Field(
        default=None, description="Ultimos digitos do cartao citado pelo cliente, ex '4821'"
    )
    confirmation: ConfirmationDecision | None = Field(
        default=None, description="Preenchido apenas quando a mensagem responde a uma confirmacao"
    )
    wants_authentication: bool = Field(
        default=False, description="O cliente sinalizou querer se identificar"
    )


class ModelResponse(BaseModel):
    """Resposta conversacional composta pelo modelo (ADR-010)."""

    model_config = ConfigDict(extra="forbid")

    message: str


class TurnFact(BaseModel):
    """Fato estruturado entregue ao modelo para ele transformar em linguagem.

    Espelha o envelope de tool de SPEC-004 §21: o modelo recebe **fatos**, e a
    prosa é trabalho dele. O envelope não carrega texto pronto, porque prosa no
    resultado devolveria a ambiguidade que ele existe para eliminar.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str
    ok: bool
    code: str
    result_type: str
    data: dict[str, object] = Field(default_factory=dict)


class TurnContext(BaseModel):
    """O que o modelo sabe sobre a conversa, e nada além disso.

    Note o que **não** está aqui: CPF, OTP, nome, e-mail, telefone, número de
    cartão, saldo, `fare_profile` oficial, status de Order, Payment ou
    Fulfillment, e identificadores internos. Status e valores chegam ao modelo
    apenas como **fatos de tool já sanitizados** (`TurnFact`), nunca como
    contexto que ele possa tomar por memória confiável.
    """

    model_config = ConfigDict(extra="forbid")

    phase: str
    authenticated: bool = False
    has_selected_card: bool = False
    has_pending_confirmation: bool = False
    awaiting_confirmation_total: str | None = None


class LLMProvider(Protocol):
    """Fronteira com o modelo de linguagem.

    Implementações encapsulam **inteiramente** a SDK do provider: nenhum tipo,
    objeto ou exceção do fornecedor atravessa esta fronteira (ADR-015). O
    adaptador traduz falha de provider para exceção própria.
    """

    @property
    def name(self) -> str: ...

    async def understand(self, *, message: str, context: TurnContext) -> TurnUnderstanding:
        """Classifica a mensagem e extrai o que ela carrega de estruturado."""
        ...

    async def compose_reply(
        self, *, message: str, context: TurnContext, facts: Sequence[TurnFact]
    ) -> ModelResponse:
        """Transforma fatos estruturados em uma resposta em português."""
        ...


class LLMProviderError(Exception):
    """Falha ao falar com o provider.

    Erro de provider **nunca** vira sucesso conversacional e nunca para
    webhook, payment ou fulfillment já persistidos (ADR-010).
    """
