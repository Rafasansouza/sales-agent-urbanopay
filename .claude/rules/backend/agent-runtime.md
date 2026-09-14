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
ADR-002, ADR-003, ADR-005, ADR-010, ADR-014, ADR-015.

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

Fonte: ADR-002, com ADR-014 tendo precedência no tema **persistência /
checkpoint durável do estado conversacional**.

- LangGraph orquestra; não implementa regra de negócio.
- O estado do grafo **não** é source of truth de saldo, tarifa, Order ou
  Payment.
- Nodes podem ser retomados e reexecutados: **todo side effect é idempotente**.
- O webhook financeiro **não passa pelo grafo**.

### Persistência: application-owned (ADR-014)

- O grafo é compilado **sem checkpointer**.
- O estado conversacional durável **pertence à aplicação**: tabela
  `agent_conversations`, versionada exclusivamente por Alembic.
- **Nenhum schema é criado por runtime ou por framework** — nem `setup()`, nem
  `create_all`, sob nome algum. Regra permanente.
- **Não** usar: tabelas nativas de checkpoint, `MemorySaver` em produção,
  Redis como source of truth, JSONB genérico de graph state.
- **`interrupt`/`resume` não são usados no MVP.** A confirmação do passageiro é
  fronteira de turno, registrada em `pending_confirmation`; a aprovação humana
  é assíncrona e ocorre fora do grafo (A-07).
- Tipos do LangGraph **não vazam** para `domain`, para contratos de
  `application` nem para o modelo de persistência: o grafo se adapta ao
  `ConversationState`, não o contrário.
- `langgraph-checkpoint-postgres` **não** é dependência do projeto.

### Onde cada peça vive

```text
application/conversation_service.py   ciclo de vida do turno
application/sensitive_input.py        intercepta CPF/OTP antes do modelo
application/reconciliation.py         backend vence o estado conversacional
application/turn.py                   port TurnRunner (sem tipo de framework)
infrastructure/graph/                 ÚNICO lugar que importa langgraph
infrastructure/models.py              agent_conversations, agent_turn_requests
infrastructure/repositories.py        CAS por version
```

`understand` e `respond` são os **únicos** nodes que falam com o modelo. `act`
é determinístico: os playbooks decidem quais tools rodam e em que ordem.

## Provider de LLM

Fonte: ADR-010, ADR-015.

```text
                 ┌─ FakeLLMProvider     ← testes, CI e demo sem credencial
LLMProvider Port ┤
                 └─ OpenAILLMProvider   ← runtime com modelo real
```

- Nodes nunca instanciam SDK de provider diretamente. Use a abstração
  `LLMProvider`.
- Baseline do MVP: **OpenAI**, modelo vindo de `OPENAI_MODEL` — nunca
  hardcoded (ADR-015 alterou a escolha de provider de ADR-010).
- A SDK fica **inteiramente** encapsulada no adaptador: nenhum tipo dela
  alcança `domain`, `application`, contrato de tool ou `ConversationState`.
- `OPENAI_API_KEY` vive só no backend. Nunca em HTML, JS, browser, resposta,
  log, estado do grafo, banco ou telemetria.
- `LLM_PROVIDER=openai` sem chave **falha explicitamente**. Nunca fallback
  silencioso para o Fake.
- **Não existe caminho de negócio especial para o Fake**: os dois implementam
  o mesmo port e devolvem os mesmos contratos.
- Contratos internos tipados: `IntentResult`, `TripExtractionResult`,
  `ConfirmationResult`, `ModelResponse`.
- Structured outputs passam por Pydantic **e** por validação de domínio.
  **Schema válido não implica regra válida.**
- `FakeLLMProvider` em testes; nenhuma chamada real de LLM em CI.
- Fallback automático entre providers está fora do MVP.
- Outage do LLM não pode parar webhook, payment ou fulfillment já persistidos.

## Tool registrada ≠ tool visível ao modelo

Fonte: SPEC-004 §7.1. **O schema entregue ao LLM contém exclusivamente
`LLM_VISIBLE`.** Estar no catálogo autoriza a operação; a visibilidade define
quem pode invocá-la.

**16 contratos registrados.**

| Nível | Qtd. | Tools |
|---|--:|---|
| `LLM_VISIBLE` | 9 | `calculate_trip_fare`, `get_customer_cards`, `get_card_details`, `get_card_balance`, `get_order`, `get_approval_status`, `get_payment_status`, `get_fulfillment_status`, `get_receipt` |
| `GRAPH_ONLY` | 5 | `get_authentication_status`, `create_recharge_quote`, `create_order`, `confirm_order`, `create_payment` |
| `SENSITIVE_INPUT` | 2 | `start_authentication`, `verify_otp` |
| `BACKEND_ONLY` | — | **não registradas**; nome resolve para `TOOL_NOT_AUTHORIZED` |

`create_quote` de SPEC-004 §7 materializa-se como **`create_recharge_quote`**:
`RECHARGE` é o único `operation_type` do MVP.

## Tools declaradas e indisponíveis

Fonte: SPEC-004 §7.3. Resolvem para `TOOL_UNAVAILABLE` nomeando o bloqueio.
**Nunca** substituídas por comportamento fictício.

`search_products` (A-05), `get_product` (A-05), `get_ticket` (A-05),
`calculate_usage_cost` (A-06).

Enquanto A-06 estiver aberta, **o agente não recomenda valor de recarga**: o
cliente informa o valor.

## Tools proibidas

SQL arbitrário, shell, HTTP arbitrário, acesso a Redis, `get_otp`,
`set_balance`, `set_fare`, `set_fare_profile`, `set_order_status`,
`set_payment_status`, `approve_payment`, `mark_payment_as_paid`,
`mark_order_as_paid`, `apply_discount`, `override_rule`, `apply_recharge`,
`issue_ticket`, `retry_fulfillment`, `reconcile_fulfillment`,
`set_ticket_status`, `authenticate_as`, `change_customer`,
`change_fare_profile`, `change_balance`, `link_card`.

`BACKEND_ONLY` — existem no backend e **jamais** são alcançáveis pelo agente:
`approve_order`, `reject_order`, `expire_draft`, `process_payment_webhook`,
`reconcile_payment`, `fulfill_order`, comandos de recuperação/consistência.

Nenhuma delas pode ser criada sob nome equivalente ou disfarçada como tool
genérica. Não existe fallback dinâmico nem resolução por reflexão a partir de
nome vindo do modelo.

## Mínimo privilégio

Tools recebem resource IDs; dados críticos são derivados server-side.

```text
correto : create_payment(order_id)
errado  : create_payment(amount, customer, discount, ...)
```

E, para operação crítica, **nem o resource ID é escolhido pelo modelo**
(SPEC-004 §9.1):

| Operação | Identificador derivado de | Ausência de contexto |
|---|---|---|
| `confirm_order` | `pending_confirmation.order_id` | `NO_PENDING_CONFIRMATION` |
| `create_payment` | `current_order_id` do contexto confirmado | `NO_PENDING_CONFIRMATION` |

Vínculo divergente ⇒ `CONFIRMATION_CONTEXT_MISMATCH`, sem chamar serviço.

Nunca são argumento de tool: `status`, `amount` de pagamento, `balance`,
`fare_profile` oficial, `payment_id`, `customer_id`, `requires_approval` e
**idempotency key**.

## Idempotência: o modelo nunca escolhe a key

Fonte: SPEC-004 §9.1, SPEC-003 §11, §13.

```text
create_order    : create_order:{quote_id}
confirm_order   : confirm_order:{order_id}
create_payment  : create_payment:{order_id}:initial
                  create_payment:{order_id}:after:{last_terminal_payment_id}
```

A identidade da tentativa de pagamento vem de **evidência persistida**, nunca
de contador em memória e nunca do modelo. Tentativa ativa `CREATED` ⇒
`PAYMENT_STATUS_UNKNOWN` e a jornada para; tentativa ativa `PENDING` ⇒ devolve
a existente. Nova tentativa comercial só nasce depois de um Payment terminal
não aprovado persistido.

## Códigos de guarda

Fonte: SPEC-004 §20. São de **orquestração**, não de domínio, e nenhum cria
estado financeiro: `TOOL_NOT_AUTHORIZED`, `TOOL_UNAVAILABLE`,
`TOOL_LIMIT_EXCEEDED`, `NO_PENDING_CONFIRMATION`,
`CONFIRMATION_CONTEXT_MISMATCH`, `INTERNAL_ERROR`.

Exceção desconhecida ⇒ `ok=false`, `INTERNAL_ERROR`, `next_action=STOP`, log
sanitizado. **Nunca** vira sucesso, nunca expõe stack trace.

## Faseamento

Fonte: SPEC-004 §22.

- **Etapa 1 (implementada):** tools, visibilidade, autorização, envelopes,
  presenters, guardas, idempotência, composition root, testes.
- **Etapa 2 (implementada):** LangGraph sem checkpointer, `LLMProvider` com
  Fake e OpenAI, prompt, limite de tool calls por turno, evals, persistência
  conversacional.
- **Etapa 3 (implementada):** `POST /api/v1/agent/messages`, webhook de
  pagamento, coordenador pós-pagamento (A-19), E2E da jornada do PRD §18,
  canal de OTP de demonstração (H-12) e página de chat dev-only.

## Contexto e PII

- Não reenvie o histórico inteiro indefinidamente. Prefira state estruturado,
  resumo e mensagens recentes.
- Nunca envie ao provider: OTP, CPF completo, número completo de cartão,
  secret ou token.
- Minimize a PII enviada ao provider.

**Entrada sensível é interceptada antes do modelo** (SPEC-004 §13.1). Nas fases
`AWAITING_DOCUMENT` e `AWAITING_OTP`, a mensagem passa por handler
determinístico → tool `SENSITIVE_INPUT` → serviço de identity, e só então, se
necessário, pelo LLM. No histórico e no estado destinados ao modelo o valor
vira `[DOCUMENT_REDACTED]` / `[OTP_REDACTED]`.

CPF, OTP e hashes **nunca** entram no `ConversationState`. `get_otp` é proibida
sob qualquer nome; H-12 (canal de OTP para demo humana) permanece aberta.

## Estado é cache, nunca autoridade

Fonte: SPEC-004 §3.1. O estado guarda **referências de orquestração**:
`conversation_id`, `session_id`, `phase`, `selected_card_id`,
`current_quote_id`, `current_order_id`, `current_payment_id`,
`pending_confirmation`.

Nunca são autoridade no state — releia do PostgreSQL antes de operação crítica:
`Card.status`, saldo, `fare_profile`, `Order.status`, `Order.total`,
`requires_approval`, `Payment.status`, `Approval.status`,
`Fulfillment.status`. `authenticated` e `customer_id` também não: derivam da
sessão a cada operação protegida.

Valor de display que fique no state é marcado como **não autoritativo** e
jamais participa de decisão. Ele é **valor de turno**: ADR-014 decidiu que
`display_total` **não é persistido** — na retomada, o total é recomposto
relendo o Order.

`ConversationPhase` **não é apenas UX** (ADR-014): `AWAITING_DOCUMENT` e
`AWAITING_OTP` são o que informa ao transporte que a próxima mensagem precisa
do handler determinístico de §13.1 **antes** do provider. Por isso a fase
precisa continuar conhecida depois de um restart — é controle de PII.

O estado conversacional **nunca compartilha transação** com Order, Approval,
Payment, Fulfillment ou saldo de Card. Se o commit de negócio der certo e a
escrita conversacional falhar, **não existe compensação financeira**: o turno
seguinte relê o backend e continua de forma idempotente.

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
