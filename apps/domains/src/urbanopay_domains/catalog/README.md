# Catalog — produtos tarifarios

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** nenhuma SPEC existe
**ADRs aplicaveis:** ADR-004
**Estado:** nao implementado

## Responsabilidade

Catalogo de produtos vendaveis. O PRD §6.4 lista Bilhete Unitario QR, Passe Diario, Pacote 10 Viagens e Recarga Livre.

## Entidades previstas

- `Product`

## Tools permitidas ao Sales Agent

- `search_products`
- `get_product`

## Tools proibidas

- `qualquer tool que altere preco ou elegibilidade`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- BLOQUEADO: nao existe SPEC de catalogo. Ver A-05 em docs/OPEN-QUESTIONS.md.
- PRD §19 mantem pendentes as regras de Passe Diario, de Pacote 10 Viagens e a validade do QR/bilhete.
- Consequencia: a jornada TICKET_PURCHASE nao e implementavel sem inventar regra de negocio.

## Estrutura esperada quando implementado

```text
catalog/
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
