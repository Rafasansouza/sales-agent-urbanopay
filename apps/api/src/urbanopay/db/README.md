# Persistência

**Documentos:** ADR-004 (Aceito), ADR-012 (Aceito)
**Estado:** arquitetura decidida — implementação futura

## Decisão vigente

O ADR-012 foi **aceito** e define:

- **SQLAlchemy 2.x**, com ORM declarativo tipado como modelo de persistência e
  queries explícitas na API 2.0 (`select`, `insert`, `update`);
- **psycopg 3** como driver;
- **runtime assíncrono**: `AsyncSession`, `async_sessionmaker`,
  `expire_on_commit=False`;
- **Repository Pattern** com ports (`Protocol`) no domínio;
- **Unit of Work** explícito e fino como port da camada de aplicação;
- **Alembic** para migrations — nenhuma tabela é criada fora dele;
- `READ COMMITTED`, `SELECT ... FOR UPDATE`, constraints e índices únicos como
  mecanismos principais de concorrência;
- um único schema lógico no MVP.

## Por que este diretório ainda está sem código

A decisão arquitetural existe; a **implementação ainda não**. Ela nasce em
tarefa posterior, junto com a primeira SPEC que precisar de persistência, e
seguirá a estrutura documentada no ADR-012 (`base.py`, `engine.py`,
`session.py`, `unit_of_work.py`, `registry.py`, `migrations/`).

Consequências atuais:

- Nenhuma dependência de banco no `pyproject.toml` — SQLAlchemy, psycopg 3 e
  Alembic serão adicionados na tarefa de implementação.
- Nenhum modelo, schema ou migration.
- `make migrate` / `.\scripts\dev.ps1 migrate` falham com mensagem explicativa,
  porque o Alembic não está instalado.
- O job `test-integration` da CI sobe PostgreSQL e Redis, mas não coleta testes.
- `GET /api/v1/health` não verifica banco nem Redis.

## Regras que valem para a implementação

Fonte: ADR-012, ADR-004, CLAUDE.md, SPEC-001 §7, SPEC-005 §7. Detalhes em
`.claude/rules/database.md`.

- Modelos ORM vivem **apenas** em `modules/<dominio>/infrastructure/` e nunca
  atravessam a fronteira do repositório.
- Entidades de domínio são puras: `domain/` não importa SQLAlchemy.
- Repositories nunca executam commit; a camada de aplicação controla a
  fronteira transacional via `UnitOfWork`.
- Dinheiro em `NUMERIC(12, 2)` ↔ `Decimal`, sem float em nenhum ponto e sem
  arredondamento na persistência.
- Constraints de banco para invariantes críticas, entre elas:
  - no máximo um `Payment APPROVED` por `Order` (índice único parcial);
  - um efeito financeiro por Order de recarga (`UNIQUE (order_id)`);
  - unicidade de CPF normalizado e de chave de idempotência.
- Ledger, saldo e status atualizados na mesma transação, com
  `SELECT ... FOR UPDATE`.
- Migration destrutiva exige revisão humana explícita; `alembic check` na CI.
- Em Windows, psycopg async exige política de event loop compatível
  (`SelectorEventLoop` ou equivalente) — critério de teste da implementação.
- Seeds exclusivamente fictícios.

## Fora do escopo do ADR-012

As tabelas internas do LangGraph (checkpointer de ADR-002) exigem **ADR
próprio** antes da SPEC-004 — ver H-11 em `docs/OPEN-QUESTIONS.md`. Até lá,
nenhum `setup()` automático de schema do LangGraph pode ser introduzido.
