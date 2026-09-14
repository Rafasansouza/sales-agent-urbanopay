# Fulfillment — recarga, ledger e reconciliação

**Fronteira de domínio:** ADR-001
**Documentos obrigatórios:** SPEC-005
**ADRs aplicáveis:** ADR-005, ADR-007, ADR-012
**Estado:** implementado (SPEC-005, escopo `RECHARGE`)

## Responsabilidade

Aplica o efeito comercial depois que o pagamento foi confirmado, de forma
determinística, atômica e auditável. É o fim da cadeia:

```text
Payment APPROVED → Order PAID → fulfill_order → crédito + ledger + comprovante
```

Fulfillment é **consequência** de estado financeiro confirmado. Pagamento
aprovado autoriza; fala do usuário nunca autoriza.

## Entidades

- `Fulfillment` — autoridade detalhada do processo
- `CardLedgerEntry` — prova física de crédito único; no recorte `RECHARGE` é
  também a materialização da `RechargeTransaction` conceitual (A-16)
- `Receipt` — comprovante simulado, não fiscal
- `CreditApplication` — value object do cálculo de crédito

**Não materializadas** nesta versão: `RechargeTransaction` (fundida no
ledger), `FulfillmentAttempt`, `ReconciliationRecord` e `Ticket` — ver A-16 e
SPEC-005 §4.1.

## Autoridade de entrada

`fulfill_order(order_id)` e nada mais. `card_id`, `amount` e `payment_id` são
derivados do estado persistido — há teste de assinatura provando que nenhum
deles é parâmetro.

## Estados

`PENDING → PROCESSING → COMPLETED | FAILED | RECONCILIATION_REQUIRED`, com
reentrada explícita a partir dos dois últimos. Em `RECHARGE` a sequência até
`COMPLETED` ocorre na mesma transação e não é observável de fora — commit
intermediário criaria janela de estado financeiro parcial.

## Invariantes

- nenhum fulfillment sem `Order PAID`;
- nenhuma recarga sem `Payment APPROVED` — verificado, não presumido;
- **um Order de recarga produz no máximo um efeito financeiro**
  (`uq_card_ledger_entries_recharge_per_order`);
- `ledger.amount == order.total`, sem recálculo de tarifa;
- comprovante somente após `COMPLETED`;
- ledger imutável;
- LLM nunca altera saldo.

## Ordem de lock

`Order → Card → Fulfillment`. O `Card` vem antes do `Fulfillment` por
necessidade técnica — chave estrangeira para `cards` faz o PostgreSQL travar a
linha em `FOR KEY SHARE` no `INSERT`, e elevar esse lock a exclusivo em duas
transações concorrentes é deadlock. Há teste de regressão.

## Estrutura

```text
fulfillment/
├── domain/          entidades, enums, erros, state machine, ports
├── application/     FulfillmentService, FulfillmentRecoveryService
└── infrastructure/  models ORM, repositories, Units of Work
```

`fulfillment` depende dos ports públicos de `orders`, `cards` e `payments`;
nenhum deles importa `fulfillment` (ADR-001).

## Pendências

⚠️ **A-18** — a resolução administrativa de "pago e não entregável" não
existe. O comportamento determinístico está implementado (zero efeito, estado
`RECONCILIATION_REQUIRED`), mas o desfecho para o cliente depende de decisão
de produto.

Não existe scheduler: há o comando e as consultas de recuperação, para uso
futuro da camada de composição.
