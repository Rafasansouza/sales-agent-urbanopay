# Observability — correlacao de dominio

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** transversal
**ADRs aplicaveis:** ADR-008
**Estado:** nao implementado

## Responsabilidade

Fronteira declarada em ADR-001. A instrumentacao transversal (logging JSON e bootstrap de telemetria) vive em urbanopay.core; este modulo reserva o espaco para helpers de correlacao especificos de dominio, como enriquecimento de span com IDs de Order e Payment.

## Entidades previstas

_Nenhuma._

## Tools permitidas ao Sales Agent

_Nenhuma._

## Tools proibidas

- `nenhuma tool e exposta ao agente por este modulo`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- Traces nunca sao fonte de verdade financeira.
- OTP, CPF completo, cartao completo e qr_token nunca sao registrados.
- Se a sanitizacao falhar, preferir nao exportar.
- Outage de observabilidade nao derruba o fluxo de negocio.

## Estrutura esperada quando implementado

```text
observability/
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
