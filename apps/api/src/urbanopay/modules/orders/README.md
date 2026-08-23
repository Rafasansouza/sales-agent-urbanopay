# Orders — Quote e Order

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-003
**ADRs aplicaveis:** ADR-005, ADR-007
**Estado:** nao implementado

## Responsabilidade

Transforma intencao validada em operacao transacional controlada. Quote e snapshot; Order congela produto, tarifa, perfil, desconto e total.

## Entidades previstas

- `Quote`
- `Order`
- `OrderItem`
- `IdempotencyRecord`

## Tools permitidas ao Sales Agent

- `create_quote`
- `create_order`
- `confirm_order`
- `get_order`

## Tools proibidas

- `set_order_status`
- `mark_order_as_paid`
- `apply_discount`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- BLOQUEADO por C-01: PRD §8 e SPEC-003 §14 discordam sobre a ordem entre confirmacao do passageiro e aprovacao humana.
- BLOQUEADO por C-02: nao existe transicao definida para segunda tentativa de pagamento apos rejeicao.
- Estados FAILED, CANCELLED e EXPIRED tem transicoes incompletas: A-03.
- TTL de Order indefinido: A-10.

## Estrutura esperada quando implementado

```text
orders/
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
