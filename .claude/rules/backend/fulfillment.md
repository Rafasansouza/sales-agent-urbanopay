---
paths:
  - apps/api/src/urbanopay/modules/fulfillment/**
  - apps/api/src/urbanopay/modules/tickets/**
  - apps/api/src/urbanopay/modules/postsale/**
---

# Regra — Fulfillment & Post-sale

**Documentos obrigatórios:** `docs/specs/SPEC-005-fulfillment-post-sale.md`, ADR-005, ADR-012.

Leia a SPEC-005 antes de qualquer alteração nestes módulos.

## Princípio

Fulfillment é **consequência** de estado financeiro confirmado.

> Pagamento aprovado autoriza fulfillment; fala do usuário nunca autoriza.

`PAYMENT APPROVED` e `FULFILLMENT COMPLETED` são eventos distintos (§2). Falha
de fulfillment **nunca** cria nova cobrança.

## Escopo do MVP

Somente `fulfillment_type = RECHARGE`. `TICKET_ISSUANCE` está bloqueado por
A-05 e é recusado com `UNSUPPORTED_FULFILLMENT_TYPE` — nunca com comportamento
fictício. Não existe tabela `tickets`, não existe scheduler, não existe outbox,
não existe estorno.

## Autoridade de entrada

O comando é `fulfill_order(order_id)` e **não recebe** `card_id`, `amount`,
`payment_id`, perfil tarifário nem qualquer estado informado pelo usuário.
Tudo é derivado do estado persistido:

- `card_id` ← `order.card_id` (cartão congelado no Order);
- `amount` ← `order.total`, exatamente. A tarifa **não** é recalculada;
- `payment_id` ← `Payment APPROVED` do Order.

Um parâmetro de valor ou de cartão nesta assinatura permitiria à superfície de
chamada escolher quanto se credita e para quem. Há teste de assinatura.

## State machine (SPEC-005 §5.1)

```text
(inexistente) ──> PENDING
PENDING       ──> PROCESSING
PROCESSING   ─┬─> COMPLETED
              ├─> FAILED
              └─> RECONCILIATION_REQUIRED
FAILED                  ──> PROCESSING   (comando EXPLÍCITO)
RECONCILIATION_REQUIRED ──> PROCESSING   (comando EXPLÍCITO)
COMPLETED                                (terminal)
```

Em `RECHARGE`, `PENDING → PROCESSING → COMPLETED` ocorre na **mesma
transação** e não é observável de fora. Isso é deliberado: commit intermediário
criaria janela de estado financeiro parcial. **Não** crie commits só para
tornar estados visíveis.

Reentrada nunca é automática.

## Mapeamento Order × Fulfillment (§5.2)

| Fulfillment | Order |
|---|---|
| `PENDING`, `PROCESSING` | `FULFILLING` |
| `COMPLETED` | `COMPLETED` |
| `FAILED` | `FULFILLMENT_FAILED` |
| `RECONCILIATION_REQUIRED` | `FULFILLMENT_FAILED` |

Fulfillment é a autoridade **detalhada**; o Order mantém o estado
**coarse-grained** da jornada, que termina em `COMPLETED`. Nenhuma transição
nova é introduzida no Order — todos os caminhos já existem em SPEC-003 §14.

## Invariantes financeiras

- nenhum fulfillment sem `Order PAID`;
- nenhuma recarga sem `Payment APPROVED` — verificado, não presumido;
- **um Order de recarga produz no máximo um efeito financeiro**;
- saldo corresponde ao ledger;
- `ledger.amount == order.total`;
- comprovante somente após `COMPLETED`;
- LLM nunca altera saldo.

## Idempotência

Chave **natural**: o Order. **Não** use `idempotency_records` — manter um
segundo mecanismo para o mesmo fato criaria duas verdades a sincronizar (A-15).

Garantia física: índice único parcial de `RECHARGE_CREDIT` por `order_id`.

- replay de Order concluído ⇒ devolve o resultado anterior, sem novo crédito e
  sem novo comprovante;
- efeito divergente para o mesmo Order ⇒ `EFFECT_CONFLICT`, sem efeito.

## Transação e locks

Tudo em **uma** transação: ledger, saldo, fulfillment, Order e comprovante.
Qualquer falha antes do commit desfaz tudo junto — nenhum estado financeiro
parcial sobrevive.

**Ordem global de lock:** `Order → Approval → Payment → Card → Fulfillment`.

No fluxo de recarga: `lock Order` → `lock Card` → `lock Fulfillment`. O
Payment é **leitura**, porque `APPROVED` é terminal e imutável.

⚠️ O `Card` vem **antes** do `Fulfillment` por necessidade técnica.
`fulfillments.card_id` e `card_ledger_entries.card_id` são chaves estrangeiras,
e o PostgreSQL adquire `FOR KEY SHARE` na linha do cartão no `INSERT`. Travar
o cartão **depois** desses inserts deixa duas transações concorrentes sobre o
mesmo cartão com lock compartilhado, ambas tentando elevá-lo a exclusivo —
deadlock. Isso não é teoria: a ordem inversa foi implementada e reprovada por
`tests/integration/fulfillment/test_concurrency.py`, que é o teste de
regressão desse defeito.

Não adquira lock desnecessário.

## Ledger

`CardLedgerEntry` é **imutável**: o repository tem `add`, e não tem `update`
nem `delete`. Invariantes com constraint: `amount > 0`, `currency = 'BRL'`,
`balance_before >= 0`, `balance_after >= 0`,
`balance_after = balance_before + amount`, e um `RECHARGE_CREDIT` por Order.

## Saldo do cartão

A mutação pertence ao módulo **`cards`**, sua casa natural. `fulfillment`
consome o port público de crédito; **nunca** escreve na tabela `cards` pela
própria infraestrutura. `cards` **nunca** importa `fulfillment` — dependência
circular entre módulos é defeito (ADR-001).

## Reconciliação

**Detecção, nunca reparo financeiro automático.** Nenhuma reconciliação cria
crédito porque "parece faltar". Um fulfillment já `COMPLETED` com ledger
ausente é **reportado**, não transicionado: regredir estado terminal
contradiz a máquina de estados aceita.

⚠️ A resolução administrativa de "pago e não entregável" permanece aberta em
**A-18**.

## Privacidade

Persistir apenas IDs opacos, `card_last4`, valores e timestamps. **Nunca** CPF,
OTP, nome desnecessário, número completo de cartão ou payload de provider.

## Tools permitidas ao Sales Agent

`get_fulfillment_status`, `get_ticket`, `get_receipt`, `get_card_balance` —
todas somente leitura.

## Tools proibidas

`apply_recharge`, `issue_ticket`, `retry_fulfillment`, `reconcile_fulfillment`,
`set_ticket_status`, `set_balance`. Não crie nenhuma delas, sob nenhum nome
equivalente.
