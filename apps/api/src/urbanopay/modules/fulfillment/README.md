# Fulfillment — recarga, ledger e reconciliacao

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-005
**ADRs aplicaveis:** ADR-005, ADR-007
**Estado:** nao implementado

## Responsabilidade

Executa a entrega apos pagamento aprovado: recarga, ledger, idempotencia, retry classificado e reconciliacao.

## Entidades previstas

- `Fulfillment`
- `RechargeTransaction`
- `CardLedgerEntry`
- `FulfillmentAttempt`
- `ReconciliationRecord`

## Tools permitidas ao Sales Agent

- `get_fulfillment_status`

## Tools proibidas

- `apply_recharge`
- `retry_fulfillment`
- `reconcile_fulfillment`
- `set_balance`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- Nenhum fulfillment sem Order PAID e Payment APPROVED.
- Ledger, saldo e status na mesma transacao de banco.
- Idempotencia por recharge:{order_id}: nunca duplica credito.
- Falha apos pagamento nunca gera nova cobranca.
- UNKNOWN_OUTCOME vira RECONCILIATION_REQUIRED, nunca retry cego.
- Iniciado pelo backend: continua se o usuario fechar o navegador.

## Estrutura esperada quando implementado

```text
fulfillment/
├── domain/          entidades, value objects, erros tipados, regras puras
├── application/     use cases e servicos
└── infrastructure/  repositorios e adaptadores
```

Direcao de dependencia: `domain` nao importa `application` nem
`infrastructure`. Ver `.claude/rules/architecture.md`.

## Antes de implementar

1. Leia a SPEC correspondente por inteiro, nao de memoria.
2. Leia `docs/OPEN-QUESTIONS.md` e confirme que nenhuma pendencia bloqueia a
   tarefa.
3. Confirme que os ADRs necessarios estao com status Aceito.
4. Use a skill `prepare-task` antes de escrever codigo.
