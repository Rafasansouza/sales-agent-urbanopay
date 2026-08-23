# Agent — Sales Agent conversacional

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-004
**ADRs aplicaveis:** ADR-002, ADR-003, ADR-005, ADR-010
**Estado:** nao implementado

## Responsabilidade

Agente conversacional unico que compreende linguagem natural, preserva contexto, coleta dados faltantes, chama tools estreitas, recomenda e conduz a jornada. Nao possui autoridade financeira.

## Entidades previstas

- `ConversationState`

## Tools permitidas ao Sales Agent

- `as tools listadas em SPEC-004 §7, todas estreitas e tipadas`

## Tools proibidas

- `SQL arbitrario`
- `shell`
- `HTTP arbitrario`
- `acesso a Redis`
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
generica.

## Invariantes e bloqueios

- Nenhum agente adicional de runtime pode ser criado (ADR-003).
- O webhook financeiro nunca passa pelo grafo (ADR-002).
- Os limites de SPEC-004 §14 ainda nao foram fixados.

## Estrutura esperada quando implementado

```text
agent/
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
