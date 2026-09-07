---
description: Regras de Quote, Order, aprovação e Payment (SPEC-003). Idempotência financeira.
paths:
  - "apps/api/src/urbanopay/modules/orders/**"
  - "apps/api/src/urbanopay/modules/payments/**"
  - "apps/api/src/urbanopay/modules/approvals/**"
  - "apps/api/src/urbanopay/providers/payments/**"
  - "apps/api/src/urbanopay/core/idempotency.py"
  - "apps/api/src/urbanopay/db/idempotency.py"
  - "tests/**/orders/**"
  - "tests/**/payments/**"
  - "tests/**/approvals/**"
  - "tests/**/*payment*"
  - "tests/**/*order*"
---

# Regra — Orders, Approvals & Payments

**Documentos obrigatórios:** `docs/specs/SPEC-003-orders-payments.md`, ADR-005, ADR-007.

Leia a SPEC-003 antes de qualquer alteração nestes módulos.

## Princípio

A conversa representa **intenção**; o backend representa **estado**. Dizer
"paguei" nunca altera status financeiro — não é evento de domínio.

## State machine oficial do Order (SPEC-003 §14)

A confirmação explícita do cliente **precede** a aprovação humana.
`CONFIRMED` é o **único** estado pagável e significa: todas as confirmações
necessárias foram satisfeitas.

```text
DRAFT ─┬─> CANCELLED                (cancelamento pelo cliente — só em DRAFT)
       ├─> EXPIRED                  (TTL de DRAFT: default 10 min)
       ├─> CONFIRMED                (confirma; requires_approval = false)
       └─> REQUIRES_APPROVAL        (confirma; requires_approval = true)
              ├─> CANCELLED         (Approval REJECTED)
              └─> CONFIRMED         (Approval APPROVED)

CONFIRMED         ──> PAYMENT_PENDING          (create_payment)
PAYMENT_PENDING ─┬──> PAID                     (Payment APPROVED)
                 └──> CONFIRMED                (Payment terminal não aprovado)
PAID              ──> FULFILLING               (SPEC-005)
FULFILLING       ─┬──> COMPLETED               (Fulfillment COMPLETED)
                  └──> FULFILLMENT_FAILED      (FAILED ou RECONCILIATION_REQUIRED)
FULFILLMENT_FAILED──> FULFILLING               (reentrada por comando EXPLÍCITO)
```

**Não existe `Order.APPROVED`** e **não existe `Order.FAILED`** — ambos foram
removidos do enum por não possuírem caminho de entrada. A aprovação é
`Approval.status = APPROVED`; o pagamento aprovado é
`Payment.status = APPROVED`.

Estados do Order: `DRAFT`, `REQUIRES_APPROVAL`, `CONFIRMED`,
`PAYMENT_PENDING`, `PAID`, `FULFILLING`, `COMPLETED`, `FULFILLMENT_FAILED`,
`CANCELLED`, `EXPIRED`. Transição inválida ⇒ `INVALID_ORDER_STATE_TRANSITION`.

Cancelamento pelo cliente: **somente em `DRAFT`**. `REQUIRES_APPROVAL →
CANCELLED` ocorre apenas por rejeição de aprovação, com motivo registrado como
tal — nunca apresentado como pedido do cliente. `PAID` é terminal; reembolso
está fora do escopo.

## Escopo do MVP

Somente `operation_type = RECHARGE`. `TICKET_PURCHASE` está bloqueado por A-05
(catálogo sem SPEC) — não implemente comportamento fictício para produtos sem
especificação.

Para RECHARGE: valor escolhido pelo cliente, `subtotal == total`,
`discount_amount == 0`, `currency = BRL`. O Fare Engine **não** calcula o valor
da recarga; `fare_profile` é snapshot de auditoria.

## Invariantes financeiras

- Somente o provider ou o backend estabelece `PaymentStatus.APPROVED`.
- Somente `PaymentStatus.APPROVED` permite `Order PAID`.
- Um Order pode ter `1..N` Payments, **no máximo um `APPROVED`** e **no máximo
  uma tentativa ativa** (`CREATED`/`PENDING`). Ambos protegidos por índice
  único parcial, além da verificação em código.
- `payment.amount == order.total`, derivado server-side. Não é expressável como
  `CHECK` entre tabelas: garanta no serviço de aplicação **e** em teste.
- `Order PAID ⇔ existe Payment APPROVED`: mesma observação — aplicação + teste.
- Após confirmação, os valores do Order são **imutáveis**.
- Falha de fulfillment após pagamento **nunca** gera nova cobrança.

## Payment: estados e retentativa

Sete estados, apenas (SPEC-003 §9): `CREATED`, `PENDING`, `APPROVED`,
`REJECTED`, `CANCELLED`, `EXPIRED`, `FAILED`. **Não crie `UNKNOWN`.**

- `CREATED` = tentativa local existe, estado externo ainda não confirmado.
- `PENDING` = provider confirmou a cobrança.
- Terminais **não regridem**.

**Retry técnico** (timeout/inconclusivo): mesmo `payment_id`, mesma key,
nenhum Payment novo, **lookup antes de qualquer novo POST**. Nunca retry cego.

**Nova tentativa comercial** (terminal não aprovado): Order volta a
`CONFIRMED`; então novo `payment_id` e nova key.

**Estado externo desconhecido:** `Payment CREATED` + `Order PAYMENT_PENDING` +
`Idempotency IN_PROGRESS`, retornando `PAYMENT_STATUS_UNKNOWN`. Nenhuma nova
tentativa comercial até reconciliar.

## Idempotência

Obrigatória em `create_order`, `confirm_order`, `approve_order`,
`create_payment` e `process_payment_webhook`. Escopo `(operation, key)`;
payload divergente ⇒ `IDEMPOTENCY_CONFLICT`. Registros vivem no PostgreSQL,
nunca no Redis (ADR-009).

- **Operações locais:** uma única transação — claim, efeito e `COMPLETED`
  comitam juntos. Não existe `IN_PROGRESS` órfão.
- **`create_payment`:** duas fases. Nenhuma transação de banco permanece
  aberta durante a chamada ao provider.
- **`COMPLETED`** = operação executada e resultado conhecido, **inclusive**
  quando o Payment terminou não aprovado. `FAILED` é falha determinística da
  própria operação. `Payment.REJECTED` ≠ `Idempotency.FAILED`.
- **Nunca** apropriação de key por tempo. `stale_after` só aciona consulta ao
  provider: o tempo autoriza reconciliação, nunca cobrança.

## Aprovação humana

`RECHARGE` com `order.total > R$ 200,00` (estritamente maior; 200,00 exatos
**não** exigem aprovação). A política fica encapsulada em `ApprovalPolicy` —
nunca espalhada em `if`, nunca com o valor literal fora dela.

`Approval.status`: `PENDING → APPROVED | REJECTED`. Terminais não voltam a
`PENDING`. Sem TTL e sem estado `CANCELLED` no MVP. Toda decisão registra ator
e instante.

O Sales Agent consulta o status; **nunca** aprova nem rejeita.

⚠️ A superfície administrativa de decisão permanece aberta (A-07).

## Webhook e PaymentEvent

A entidade se chama **`PaymentEvent`**, como nomeiam a SPEC-003 §3 e §11.2 —
não `ProviderEvent`.

`UNIQUE (provider, provider_event_id)` + `ON CONFLICT DO NOTHING`: webhook
duplicado ⇒ efeito único. Webhook e polling convergem no **mesmo** aplicador de
estado, ambos sob lock do Payment, com regras monotônicas. Evento fora de ordem
nunca faz estado terminal regredir; em caso de dúvida, **consulte o provider**.

Persista apenas payload minimizado/redigido. **Nunca** token, secret,
credencial ou PII desnecessária.

O webhook entra direto no `PaymentService` — nunca no grafo do agente, nunca no
LLM.

## Concorrência

**Ordem global de lock, única em toda a base:
`Order → Approval → Payment → Card → Fulfillment`** (ADR-012). Toda transação
que toque mais de um desses agregados respeita essa ordem. Destes módulos
participam os três primeiros elos; `Card` e `Fulfillment` entram com a
SPEC-005 (ver `.claude/rules/backend/fulfillment.md`).

Isolamento `READ COMMITTED` (ADR-012) — não altere.

## Tools proibidas

`set_order_status`, `set_payment_status`, `mark_order_as_paid`,
`apply_discount`, `approve_payment`, `mark_payment_as_paid`. Não crie nenhuma
delas, sob nenhum nome equivalente.
