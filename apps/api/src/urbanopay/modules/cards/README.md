# Cards — cartoes, perfil oficial e saldo

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-002
**ADRs aplicaveis:** ADR-004, ADR-005
**Estado:** nao implementado

## Responsabilidade

Cartoes de transporte, titularidade, perfil tarifario oficial e saldo. Durante uma transacao, card.fare_profile e a fonte oficial do perfil.

## Entidades previstas

- `Card`

## Tools permitidas ao Sales Agent

- `get_customer_cards`
- `get_card_details`
- `get_card_balance`

## Tools proibidas

- `change_fare_profile`
- `change_balance`
- `set_balance`
- `link_card`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- Titularidade validada server-side: card.customer_id == session.customer_id.
- Cartao de terceiro responde CARD_NOT_ACCESSIBLE sem revelar existencia.
- Numero completo do cartao nunca chega ao agente: masking ****NNNN.
- Saldo em Decimal/NUMERIC, nunca float.

## Estrutura esperada quando implementado

```text
cards/
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
