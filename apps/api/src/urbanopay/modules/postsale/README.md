# Post-sale — consultas e comprovante

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-005
**ADRs aplicaveis:** ADR-005
**Estado:** sem modulo proprio — por decisao

## Responsabilidade

Consultas autenticadas de pos-venda e geracao de comprovante simulado.

## Entidades previstas

- `Receipt`

## Tools permitidas ao Sales Agent

- `get_receipt`
- `get_fulfillment_status`
- `get_ticket`
- `get_card_balance`

## Tools proibidas

- `qualquer tool que altere estado`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- Comprovante somente apos COMPLETED, com indicacao de documento simulado e sem validade fiscal.
- Toda consulta valida sessao e titularidade.
- Pos-venda usa fontes oficiais, nunca busca vetorial.

## Estrutura esperada quando implementado

```text
postsale/
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

## Por que nao existe modulo proprio

As consultas de pos-venda da SPEC-005 14 ja tem casa:

- saldo -> `cards` (`get_card_balance`, SPEC-002);
- pedido -> `orders`;
- status de pagamento -> `payments`;
- status de fulfillment e comprovante -> `fulfillment`.

Um modulo `postsale` seria fachada sem logica propria. A composicao natural
dessas leituras e a camada de tools da SPEC-004, que ainda nao existe.

Nenhuma tabela e nenhum codigo foram criados aqui, por decisao: modulo sem
responsabilidade propria e acoplamento sem ganho.
