---
description: Regras do Sales Agent, LangGraph, tools e providers de LLM (SPEC-004).
paths:
  - "apps/api/src/urbanopay/modules/agent/**"
  - "apps/api/src/urbanopay/providers/llm/**"
  - "tests/**/agent/**"
  - "tests/evals/**"
---

# Regra — Sales Agent Runtime

**Documentos obrigatórios:** `docs/specs/SPEC-004-sales-agent-tools.md`,
ADR-002, ADR-003, ADR-005, ADR-010.

Leia a SPEC-004 antes de qualquer alteração neste módulo.

## Fronteira

O LLM entende, pergunta, recomenda, explica e escolhe qual tool chamar.

O backend valida, calcula, autentica, autoriza e altera estado.

**Nunca mova regra de negócio determinística para prompt.** Prompt é
orientação, nunca segurança.

## Um único agente

Fonte: ADR-003. Existe **um** Sales Agent conversacional em runtime. Não crie
Fare Agent, Card Agent, Payment Agent ou equivalente. Domínios são serviços
determinísticos acessados por tools.

Subagentes do Claude Code usados no desenvolvimento não fazem parte da
arquitetura de runtime.

## LangGraph

Fonte: ADR-002.

- LangGraph orquestra; não implementa regra de negócio.
- O estado do grafo **não** é source of truth de saldo, tarifa, Order ou
  Payment.
- Checkpoints são duráveis, preferencialmente em PostgreSQL.
- Nodes podem ser retomados e reexecutados: **todo side effect é idempotente**.
- Confirmação do passageiro e aprovação humana podem usar `interrupt`/`resume`.
- O webhook financeiro **não passa pelo grafo**.

## Provider de LLM

Fonte: ADR-010.

- Nodes nunca instanciam SDK de provider diretamente. Use a abstração
  `LLMProvider` / Model Router.
- Baseline: Claude Sonnet 5, configurável.
- Contratos internos tipados: `IntentResult`, `TripExtractionResult`,
  `ConfirmationResult`, `ModelResponse`.
- Structured outputs passam por Pydantic **e** por validação de domínio.
  **Schema válido não implica regra válida.**
- `FakeLLMProvider` em testes; nenhuma chamada real de LLM em CI.
- Fallback automático entre providers está fora do MVP.
- Outage do LLM não pode parar webhook, payment ou fulfillment já persistidos.

## Tools permitidas

Catálogo: `search_products`, `get_product`.
Fare: `calculate_trip_fare`, `calculate_usage_cost`.
Identidade: `start_authentication`, `verify_otp`, `get_authentication_status`,
`get_customer_cards`, `get_card_details`, `get_card_balance`.
Order: `create_quote`, `create_order`, `confirm_order`, `get_order`.
Aprovação: `get_approval_status` — somente leitura.
Payment: `create_payment(order_id)`, `get_payment_status(order_id)`.
Pós-venda: `get_fulfillment_status`, `get_ticket`, `get_receipt`.

## Tools proibidas

SQL arbitrário, shell, HTTP arbitrário, acesso a Redis, `set_balance`,
`set_fare`, `set_fare_profile`, `set_order_status`, `set_payment_status`,
`approve_payment`, `mark_payment_as_paid`, `apply_discount`, `override_rule`,
`apply_recharge`, `issue_ticket`.

Nenhuma delas pode ser criada sob nome equivalente ou disfarçada como tool
genérica.

## Mínimo privilégio

Tools recebem resource IDs; dados críticos são derivados server-side.

```text
correto : create_payment(order_id)
errado  : create_payment(amount, customer, discount, ...)
```

## Contexto e PII

- Não reenvie o histórico inteiro indefinidamente. Prefira state estruturado,
  resumo e mensagens recentes.
- Nunca envie ao provider: OTP, CPF completo, número completo de cartão,
  secret ou token.
- Minimize a PII enviada ao provider.

## Limites

Configuráveis por SPEC-004 §14: `max_turns_per_session`,
`max_llm_calls_per_turn`, `max_tool_calls_per_turn`, `max_input_tokens`,
`max_output_tokens`, `max_session_cost`.

Os valores não foram fixados no bootstrap: a SPEC os apresenta como sugestões
iniciais configuráveis. Defina-os junto com a implementação da SPEC-004.

## Autonomia

| Nível | Escopo |
|---|---|
| Alta | entender, perguntar, explicar |
| Média | recomendar, selecionar tool |
| Controlada | criar Quote e Order |
| Restrita | confirmar e criar payment |
| Nenhuma | alterar payment, saldo ou perfil |

## Evals

Dataset de SPEC-004 §16: 50 intents, 50 extrações de trajeto, 30 recomendações,
30 confirmações, 50 adversariais — 210 casos.

Metas: Intent ≥ 95%, Trip Extraction ≥ 98%, Recommendation ≥ 90%, Critical
Hallucination 0%. Confirmação crítica exige falso positivo zero no dataset
crítico.

Regra determinística nunca é validada por eval; use unit test.
