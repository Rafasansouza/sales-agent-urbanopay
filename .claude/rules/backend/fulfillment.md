---
description: Regras de fulfillment, ledger, tickets, reconciliação e pós-venda (SPEC-005).
paths:
  - "apps/api/src/urbanopay/modules/fulfillment/**"
  - "apps/api/src/urbanopay/modules/tickets/**"
  - "apps/api/src/urbanopay/modules/postsale/**"
  - "tests/**/fulfillment/**"
  - "tests/**/tickets/**"
  - "tests/**/postsale/**"
  - "tests/**/*ledger*"
  - "tests/**/*recharge*"
---

# Regra — Fulfillment & Post-Sale

**Documentos obrigatórios:** `docs/specs/SPEC-005-fulfillment-post-sale.md`,
ADR-005, ADR-007.

Leia a SPEC-005 antes de qualquer alteração nestes módulos.

## Princípio

`PAYMENT APPROVED` e `FULFILLMENT COMPLETED` são eventos **distintos**. Falha
de fulfillment nunca cria nova cobrança automaticamente.

## Invariantes

Fonte: SPEC-005 §19. Nenhuma delas é negociável:

1. nenhum fulfillment sem `Order PAID`;
2. nenhuma recarga sem `Payment APPROVED`;
3. um Order de recarga produz **no máximo um** efeito financeiro;
4. o saldo corresponde ao ledger;
5. ticket nunca excede a quantidade comprada;
6. falha não gera nova cobrança;
7. comprovante de sucesso somente após `COMPLETED`;
8. o LLM nunca altera saldo.

## Atomicidade

A atualização de ledger, saldo e status ocorre na **mesma transação de banco**.

Concorrência usa lock ou controle equivalente. Lock em Redis não substitui
constraint de banco. Dinheiro em `Decimal`/`NUMERIC`.

Todo movimento de saldo gera `CardLedgerEntry`. No MVP o tipo é
`RECHARGE_CREDIT`.

## Idempotência

Chave conceitual: `recharge:{order_id}`.

Reprocessar o mesmo Order retorna o resultado existente e **nunca** duplica
crédito. A emissão de ticket também é idempotente, respeitando a `quantity` do
`OrderItem`.

## Independência do agente

O fulfillment é iniciado pelo backend após o pagamento e continua mesmo se o
usuário fechar o navegador ou se o LLM ficar indisponível. Não acople o
fulfillment ao ciclo de vida da conversa.

## Classificação de falhas

| Classe | Comportamento |
|---|---|
| `RETRYABLE` | retry automático, no máximo 3 tentativas (sugestão inicial da SPEC) |
| `NON_RETRYABLE` | `FAILED`, sem retry |
| `UNKNOWN_OUTCOME` | `RECONCILIATION_REQUIRED`, **nunca** retry cego |

- Falha conhecida antes de qualquer efeito ⇒ `FAILED`.
- Falha na transação local ⇒ rollback.
- Resultado externo desconhecido ⇒ `RECONCILIATION_REQUIRED`.

## Reconciliação

`ReconciliationRecord` com status `PENDING`, `RESOLVED`, `MANUAL_REVIEW`,
`FAILED`.

No MVP local, o job procura `Order PAID` sem estado de fulfillment conhecido e
compara com `RechargeTransaction` e ledger.

Métrica dura: `paid_orders_without_known_fulfillment_state = 0`.

## Ticket

Campos em SPEC-005 §9. Status: `ACTIVE`, `USED`, `EXPIRED`, `CANCELLED`.

O QR é fictício e contém **token opaco**, nunca PII. O `qr_token` não vai para
log nem para trace.

⚠️ A validade exata do QR/bilhete é pendência declarada em PRD §19. Não
invente prazo.

## Comprovante

Gerado somente após `COMPLETED`, com indicação clara de documento simulado e
sem validade fiscal.

## Recuperação após restart

Estados críticos ficam persistidos. Após restart, localize `PAID`,
`FULFILLING` e `RECONCILIATION_REQUIRED`. O job conceitual
`find_stale_fulfillments` recupera operações paradas.

## Tools permitidas ao agente

`get_fulfillment_status`, `get_ticket`, `get_receipt`, `get_card_balance`.

## Tools proibidas

`apply_recharge`, `issue_ticket`, `retry_fulfillment`,
`reconcile_fulfillment`, `set_ticket_status`, `set_balance`.

Não crie nenhuma delas, sob nenhum nome equivalente.

## Observabilidade

Correlacione `conversation_id`, `trace_id` e os IDs de customer, card, order,
payment, fulfillment, recharge, ticket e receipt.

Nunca registre CPF completo, número completo de cartão, OTP ou `qr_token`.
