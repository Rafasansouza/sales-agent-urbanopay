# Approvals — aprovacao humana

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-003
**ADRs aplicaveis:** ADR-005
**Estado:** nao implementado

## Responsabilidade

Politica de aprovacao operacional. Regra vigente: recarga acima de R$ 200,00 exige aprovacao.

## Entidades previstas

- `Approval`

## Tools permitidas ao Sales Agent

- `get_approval_status (somente leitura)`

## Tools proibidas

- `approve_order pelo agente`
- `qualquer tool que aprove ou rejeite`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- A politica fica encapsulada em ApprovalPolicy, nunca espalhada em if.
- BLOQUEADO por A-07: a interface administrativa de aprovacao nao esta especificada, logo um Order em REQUIRES_APPROVAL nao tem caminho de saida no MVP.
- Ver tambem C-01 sobre a ordem entre confirmacao e aprovacao.

## Estrutura esperada quando implementado

```text
approvals/
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
