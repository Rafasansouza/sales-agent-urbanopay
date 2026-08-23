# Regra — Banco de Dados

Fonte: ADR-004, ADR-009, ADR-012 (Proposta), SPEC-001 §7, SPEC-005 §7.

## Autoridade

PostgreSQL é a fonte autoritativa de `Customer`, `Card`, saldo, `Fare`,
`FareRule`, `Product`, `Quote`, `Order`, `Approval`, `Payment`, `Fulfillment`,
ledger, `Ticket` e auditoria.

- Se existe chave, estado, preço, validade, relacionamento ou regra objetiva,
  use consulta relacional.
- pgvector serve **apenas** para recuperação semântica de FAQ, descrições e
  conteúdo textual.
- Busca vetorial nunca é autoritativa para preço, saldo ou status de pagamento.
  Ela indica o que parece relevante; o dado atual é revalidado no serviço
  oficial.
- Redis nunca é autoridade de saldo, Order, Payment, Fulfillment, ledger ou
  idempotência financeira. Registros de idempotência financeira ficam no
  PostgreSQL.
- Perda total do Redis pode custar velocidade, nunca histórico.

## Dinheiro

- Python: `Decimal`. **Nunca** `float`, em nenhum ponto do caminho.
- PostgreSQL: `NUMERIC`/`DECIMAL`.
- Duas casas decimais, arredondamento `ROUND_HALF_UP`.
- Contrato JSON transporta valor como string decimal.

## Migrations

- Toda mudança de schema exige migration versionada.
- Migration destrutiva exige revisão humana explícita. Nunca execute sem ela.
- Migration é revisável e reversível.
- Use constraints de banco para invariantes críticas sempre que praticável:
  unicidade, `CHECK`, índice único parcial, chave estrangeira.

Exemplos de invariante que merece constraint, não apenas código:

- no máximo um `Payment APPROVED` por `Order`;
- unicidade de CPF normalizado;
- unicidade da chave de idempotência;
- saldo não negativo, quando a regra assim determinar.

## Transação e concorrência

Fonte: SPEC-005 §7.

- Atualização de ledger, saldo e status ocorre na **mesma transação**.
- Concorrência em saldo usa lock ou controle equivalente.
- Lock em Redis não substitui constraint de banco.

## Vigência

Fonte: SPEC-001 §8.

Tarifa e regra tarifária possuem `valid_from` e `valid_until`. Alteração futura
**encerra a vigência anterior**; nunca sobrescreve histórico.

## Seeds

Somente dados fictícios. Nenhum dado pessoal real, em nenhum ambiente.

## Estado atual do repositório

ADR-012 está com status **Proposta**. Enquanto não for aceito:

- não adicione dependência de banco ao backend;
- não crie modelo, schema ou migration;
- `apps/api/src/urbanopay/db/` contém apenas documentação.
