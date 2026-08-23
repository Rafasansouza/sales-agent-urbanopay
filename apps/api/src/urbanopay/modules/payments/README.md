# Payments — pagamento Pix e webhook

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-003
**ADRs aplicaveis:** ADR-005, ADR-007
**Estado:** nao implementado

## Responsabilidade

Criacao de pagamento Pix em sandbox, idempotencia e processamento de webhook. Somente o provider ou o backend estabelece APPROVED.

## Entidades previstas

- `Payment`
- `PaymentEvent`

## Tools permitidas ao Sales Agent

- `create_payment(order_id)`
- `get_payment_status(order_id)`

## Tools proibidas

- `set_payment_status`
- `approve_payment`
- `mark_payment_as_paid`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- payment.amount vem de order.total, sempre derivado server-side.
- Um Order pode ter 1..N Payments, no maximo um APPROVED. Proteger tambem com constraint de banco.
- Webhook duplicado nunca produz efeito duplicado.
- Timeout de criacao e estado desconhecido, nao falha definitiva.
- O webhook entra direto no PaymentService, nunca no LLM.

## Estrutura esperada quando implementado

```text
payments/
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
