# Agent — Sales Agent conversacional

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-004
**ADRs aplicaveis:** ADR-002, ADR-003, ADR-005, ADR-010
**Estado:** Etapa 1 implementada (SPEC-004 §22)

## Responsabilidade

Agente conversacional unico que compreende linguagem natural, preserva contexto,
coleta dados faltantes, chama tools estreitas, recomenda e conduz a jornada. Nao
possui autoridade financeira.

## O que existe hoje (Etapa 1)

A **camada deterministica** entre o modelo e os servicos de dominio:

```text
agent/
├── domain/
│   ├── catalog.py           nomes, visibilidade, indisponiveis, denylist
│   ├── conversation.py      ConversationState, fases, pending_confirmation
│   ├── results.py           ToolResult, ResultType, NextAction, GuardCode
│   ├── errors.py            erros de guarda da orquestracao
│   └── idempotency_keys.py  IdempotencyKeyPolicy (pura)
├── application/
│   ├── schemas.py           contratos de entrada (Pydantic)
│   ├── presenters.py        entidade -> dados sanitizados
│   ├── error_mapping.py     excecao de dominio -> codigo + next_action
│   ├── telemetry.py         log estruturado sanitizado
│   ├── registry.py          catalogo fechado + schema entregue ao LLM
│   ├── executor.py          pipeline de execucao
│   └── tools/               uma funcao por tool
└── infrastructure/
    └── composition.py       montagem explicita dos servicos (ADR-006)
```

Direcao de dependencia: `domain` nao importa `application` nem
`infrastructure`. O modulo **nao** importa SQLAlchemy, models ORM ou
`AsyncSession`, e nenhum modulo de negocio importa `agent`. Ambas as regras sao
verificadas por `tests/unit/test_architecture_boundaries.py`.

## O que NAO existe, por decisao

- **LangGraph, provider de LLM, prompt, evals e limites de token/custo** —
  Etapa 2, bloqueada por **ADR-014** (ver H-11 em `docs/OPEN-QUESTIONS.md`).
- **Persistencia conversacional** — nenhuma tabela, nenhuma migration. O
  `ConversationState` e efemero e explicitamente nao autoritativo.
- **Transporte HTTP, webhook e coordenador pos-pagamento** — Etapa 3
  (SPEC-005 §10.1 / A-19).

## Catalogo

**16 contratos registrados** (SPEC-004 §7.2): 9 `LLM_VISIBLE`, 5 `GRAPH_ONLY`,
2 `SENSITIVE_INPUT`. O schema entregue ao modelo contem **apenas**
`LLM_VISIBLE`.

**4 declaradas e indisponiveis** (§7.3), resolvendo para `TOOL_UNAVAILABLE`:
`search_products`, `get_product`, `get_ticket` (A-05) e `calculate_usage_cost`
(A-06).

**31 nomes na denylist** `BACKEND_ONLY`, provados irresolviveis por teste.

## Tools proibidas

- `SQL arbitrario`
- `shell`
- `HTTP arbitrario`
- `acesso a Redis`
- `get_otp`
- `set_balance`
- `set_fare`
- `set_fare_profile`
- `set_order_status`
- `set_payment_status`
- `approve_payment`
- `mark_payment_as_paid`
- `apply_discount`
- `override_rule`
- `apply_recharge`
- `issue_ticket`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica. Nao existe fallback dinamico nem resolucao por reflexao a partir de
nome vindo do modelo.

## Invariantes e bloqueios

- Nenhum agente adicional de runtime pode ser criado (ADR-003).
- O webhook financeiro nunca passa pelo grafo (ADR-002).
- `fulfill_order`, `approve_order`, `reject_order`, `reconcile_payment` e
  `process_payment_webhook` sao `BACKEND_ONLY`.
- Identificador de operacao critica e derivado do contexto, nunca escolhido
  pelo modelo (SPEC-004 §9.1).
- A idempotency key nunca vem do modelo.
- CPF e OTP nunca entram no estado, no log ou no envelope.

## Antes de implementar

1. Leia a SPEC correspondente por inteiro, nao de memoria.
2. Leia `docs/OPEN-QUESTIONS.md` e confirme que nenhuma pendencia bloqueia a
   tarefa. Abertas e relevantes: A-05, A-06, A-07, A-18, A-21, H-11, H-12.
3. Confirme que os ADRs necessarios estao com status Aceito.
4. Use a skill `prepare-task` antes de escrever codigo.
