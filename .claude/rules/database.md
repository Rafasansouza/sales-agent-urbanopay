# Regra — Banco de Dados

Fonte: ADR-004, ADR-009, ADR-012, SPEC-001 §7, SPEC-005 §7.

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

## Camada de persistência

Fonte: ADR-012 (Aceito).

- SQLAlchemy 2.x, com ORM declarativo tipado como modelo de persistência.
- Queries explícitas com a API 2.0: `select`, `insert`, `update`. Nunca o estilo
  legado `session.query()`.
- Modelos ORM vivem **apenas** em `modules/<dominio>/infrastructure/` e **nunca**
  atravessam a fronteira do repositório.
- Entidades de domínio são puras: `domain/` não importa SQLAlchemy.
- Nenhuma regra de negócio em modelo ORM. Nenhum arredondamento monetário na
  persistência — `Numeric(12, 2, asdecimal=True)` apenas armazena.
- Driver: psycopg 3. Runtime assíncrono, com `AsyncSession` e
  `async_sessionmaker`, `expire_on_commit=False`.
- Alembic para migrations. Nenhuma tabela é criada fora do Alembic.
- Um único schema lógico no MVP.

### Sessão e transação

- **Repositories nunca executam commit nem rollback.**
- **A camada de aplicação controla a fronteira transacional**, através do
  `UnitOfWork`.
- Uma sessão por unidade de trabalho.
- Uma `AsyncSession` **nunca** é compartilhada entre tasks concorrentes.
- Isolamento `READ COMMITTED`. A correção vem de constraints e de locks
  explícitos, não do nível de isolamento.
- Ordem de lock consistente em toda a base, para evitar deadlock.

### Retries

- `23505` (violação de unicidade) **não é erro técnico**: significa que outro
  processo já realizou a operação. Traduza para resultado de domínio. Nunca
  retry cego.
- `40P01` (deadlock) admite retry limitado, mas a causa raiz é ordem de lock
  inconsistente.
- Falha de conexão em escrita é **estado desconhecido**: vai para reconciliação,
  nunca retry cego.

## Estado atual do repositório

ADR-012 foi **aceito**, mas a persistência **ainda não foi implementada**. A
implementação nasce em tarefa posterior, junto com a primeira SPEC que precisar
dela.

Enquanto isso:

- `apps/api/src/urbanopay/db/` contém apenas documentação;
- as dependências previstas (SQLAlchemy, psycopg 3, Alembic, pytest-asyncio)
  ainda não foram instaladas;
- `pgvector` permanece adiado até existir consumidor real.

ADR-012 governa **apenas as tabelas da aplicação e do domínio UrbanoPay**. A
persistência das tabelas internas do LangGraph exige ADR próprio antes da
SPEC-004 — ver H-11 em `docs/OPEN-QUESTIONS.md`. Até lá, nenhum `setup()`
automático de schema do LangGraph pode ser introduzido.
