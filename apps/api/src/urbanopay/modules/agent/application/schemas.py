"""Contratos de entrada das tools (SPEC-004 §5, §9, §9.1).

Pydantic é a **primeira** barreira, nunca a única: schema válido não implica
regra válida (ADR-005, ADR-010). O que passa daqui ainda enfrenta autorização,
titularidade, state machine e constraints de banco.

Duas decisões governam todos os modelos:

- **`extra="forbid"`.** Argumento não declarado é recusado, não ignorado.
  Silenciar um campo extra transformaria uma tentativa de injeção em sucesso
  parcial;
- **valor monetário entra como `str`.** `Decimal` só nasce da conversão
  explícita no handler. Aceitar `float` no schema colocaria ponto flutuante no
  caminho do dinheiro, o que é proibido em qualquer ponto (ADR-012).

O que **nunca** aparece como campo, em nenhum modelo (§9.1): `status`,
`amount` de pagamento, `balance`, `fare_profile` oficial, `payment_id`,
`customer_id`, `requires_approval` e `idempotency_key`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ToolInput(BaseModel):
    """Base de todo contrato de entrada."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NoInput(ToolInput):
    """Tool sem argumentos.

    Continua sendo um modelo para que `extra="forbid"` valha: uma chamada que
    inventa argumentos é recusada mesmo onde nenhum é esperado.
    """


class SegmentInputSchema(ToolInput):
    """Segmento bruto de trajeto (SPEC-001 §9).

    `mode` e `line_code` chegam como texto e são validados pelo domínio —
    `INVALID_TRANSPORT_MODE`, `INVALID_SEGMENT_STRUCTURE`,
    `BUS_LINE_REQUIRED`. Repetir aqui as regras de composição duplicaria
    regra de negócio fora do domínio.
    """

    mode: str
    line_code: str | None = None


class CalculateTripFareInput(ToolInput):
    """Simulação tarifária.

    O campo se chama `declared_fare_profile`, e não `fare_profile`, porque o
    nome é o contrato: o que entra aqui é **declaração do usuário**, e ela só
    prevalece em sessão anônima. Havendo cartão selecionado numa sessão
    autenticada, o perfil oficial do cartão substitui a declaração
    (SPEC-002 §8, §15). Nenhuma tool aceita o perfil **oficial** como entrada.
    """

    segments: list[SegmentInputSchema]
    declared_fare_profile: str


class StartAuthenticationInput(ToolInput):
    """Identificação por documento.

    ⚠️ `document` é PII. A tool é `SENSITIVE_INPUT`: a entrada é interceptada
    por handler determinístico antes de qualquer chamada ao provider de LLM, e
    o valor nunca é ecoado, registrado ou persistido no estado (§13.1).
    """

    document: str


class VerifyOtpInput(ToolInput):
    """Verificação do desafio pendente da sessão.

    ⚠️ `otp` é segredo de uso único. Nunca é registrado, nunca é devolvido e
    nunca entra no estado ou no histórico enviado ao modelo (SPEC-002 §4).
    """

    otp: str


class CardInput(ToolInput):
    """Operação escopada em um cartão do próprio cliente."""

    card_id: UUID


class CreateRechargeQuoteInput(ToolInput):
    """Orçamento de recarga.

    `amount` é a única grandeza monetária que entra pela conversa, porque em
    `RECHARGE` o valor é escolha do cliente (SPEC-003 §1.1). Enquanto A-06
    estiver aberta, o agente **não** sugere esse valor.

    `declared_fare_profile` existe apenas para que a divergência com o perfil
    oficial possa ser **sinalizada** (`FARE_PROFILE_CHANGED`, A-11). Ele nunca
    substitui o perfil do cartão: a autoridade é `CardService`.
    """

    card_id: UUID
    amount: str
    declared_fare_profile: str | None = None


class CreateOrderInput(ToolInput):
    """Criação do Order a partir de uma Quote.

    `quote_id` é opcional porque a orquestração já sabe qual Quote está em
    curso; informá-lo serve para detectar divergência, não para escolher
    (§9.1).
    """

    quote_id: UUID | None = None


class ConfirmOrderInput(ToolInput):
    """Confirmação explícita do cliente (SPEC-003 §8).

    `order_id` é opcional **de propósito**: a Order confirmada é sempre a que
    o contexto guarda em `pending_confirmation`. O campo existe apenas para
    que uma tentativa de vincular outra Order seja detectada e recusada com
    `CONFIRMATION_CONTEXT_MISMATCH` — nunca para o modelo escolher.
    """

    order_id: UUID | None = None


class CreatePaymentInput(ToolInput):
    """Criação da cobrança Pix (SPEC-003 §9, §10).

    Recebe, no máximo, um `order_id` de conferência. Valor, moeda, cartão e
    idempotency key são **derivados server-side**: é isso que impede que a
    superfície de chamada — inclusive um modelo manipulado — influencie quanto
    se cobra.
    """

    order_id: UUID | None = None


class OrderInput(ToolInput):
    """Consulta escopada em um Order do próprio cliente.

    Aqui o `order_id` é livre de propósito: o cliente pode perguntar sobre um
    pedido anterior. A proteção é a titularidade verificada no backend, em
    consulta única.
    """

    order_id: UUID
