# Tickets — bilhetes simulados

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-005
**ADRs aplicaveis:** ADR-005
**Estado:** nao implementado

## Responsabilidade

Emissao idempotente de bilhete ficticio com token opaco.

## Entidades previstas

- `Ticket`

## Tools permitidas ao Sales Agent

- `get_ticket`

## Tools proibidas

- `issue_ticket`
- `set_ticket_status`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- O QR e ficticio, contem token opaco e nunca PII.
- qr_token nunca vai para log nem para trace.
- Emissao respeita a quantity do OrderItem e nao duplica.
- Validade do bilhete pendente em PRD §19: nao invente prazo.
- Depende de A-05: sem SPEC de catalogo nao ha produto de bilhete.

## Estrutura esperada quando implementado

```text
tickets/
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
