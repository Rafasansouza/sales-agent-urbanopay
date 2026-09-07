# Persistência

**Documentos:** ADR-004 (Aceito), ADR-012 (Aceito)
**Estado:** foundation implementada — modelos funcionais ainda não existem

## O que existe nesta camada

| Arquivo | Papel |
|---|---|
| `base.py` | `Base` declarativa única e `NAMING_CONVENTION` determinística |
| `engine.py` | `build_database_url` (a partir de `POSTGRES_*`) e fábrica do `AsyncEngine` |
| `session.py` | `create_session_factory` — `async_sessionmaker` com `expire_on_commit=False` |
| `unit_of_work.py` | `SqlAlchemyUnitOfWork`, implementação do port `core.persistence.UnitOfWork` |
| `registry.py` | Agregação dos models para o Alembic (hoje: nenhum model) |
| `migrations/` | Ambiente do Alembic — `env.py`, template e `versions/` (vazio) |

Stack validada empiricamente em Python 3.13: SQLAlchemy 2.0.x (asyncio),
psycopg 3.3.x, Alembic 1.19.x, greenlet 3.5.x.

## Como usar

```python
from urbanopay.core.config import get_settings
from urbanopay.db.engine import create_engine_from_settings
from urbanopay.db.session import create_session_factory
from urbanopay.db.unit_of_work import SqlAlchemyUnitOfWork

engine = create_engine_from_settings(get_settings())
session_factory = create_session_factory(engine)

uow = SqlAlchemyUnitOfWork(session_factory)
async with uow:
    ...  # repositories futuros participam via uow
    await uow.commit()  # sempre explícito; sair sem commit = rollback

await engine.dispose()  # shutdown explícito
```

A camada de aplicação depende do port `urbanopay.core.persistence.UnitOfWork`,
nunca desta implementação diretamente.

## Regras em vigor (ADR-012)

- Modelos ORM vivem **apenas** em `modules/<dominio>/infrastructure/models.py`,
  herdam de `Base` e são registrados em `registry.py`. Nunca atravessam a
  fronteira do repositório.
- Entidades de domínio são puras — verificado por teste de arquitetura
  (`tests/unit/test_architecture_boundaries.py`).
- Repositories nunca executam commit; a fronteira transacional é da aplicação,
  via Unit of Work.
- Dinheiro: `Numeric(12, 2, asdecimal=True)` ↔ `Decimal`. A persistência não
  arredonda; `ROUND_HALF_UP` pertence ao domínio.
- Toda constraint tem nome determinístico. `CheckConstraint` exige `name=`
  explícito — a convenção falha de propósito sem ele.
- Nenhuma tabela é criada fora do Alembic.

## Migrations

```powershell
.\scripts\dev.ps1 migrate                       # upgrade head
.\scripts\dev.ps1 migration "descricao"         # gera CANDIDATA (autogenerate)
.\scripts\dev.ps1 downgrade                     # reverte uma
.\scripts\dev.ps1 migration-check               # alembic check
```

Regra permanente: `autogenerate → candidata → revisão humana obrigatória`.
Índices parciais, `CHECK`s e invariantes específicas do PostgreSQL exigem
revisão explícita. Migration destrutiva exige revisão humana sinalizada no PR.

`versions/` está vazio por decisão: nenhuma revision artificial. A primeira
migration real nasce com a primeira SPEC implementada.

## Windows

psycopg async não funciona sobre o `ProactorEventLoop` padrão do Windows. O
único ponto do projeto que trata isso é `urbanopay/core/event_loop.py`; os
testes async recebem um `SelectorEventLoop` pelo hook
`pytest_asyncio_loop_factories` em `tests/conftest.py` (registrado apenas em
Windows). Solução específica do Python 3.13 — rever antes de migrar para 3.14+.

## O que ainda não existe, por decisão

- Modelos funcionais, repositories e migrations de negócio — nascem com as
  SPECs.
- A dependência FastAPI "uma sessão por request" — entra com o primeiro
  endpoint que consumir o banco. A API **não** cria engine no startup.
- Checkpointer do LangGraph — fora do escopo do ADR-012; exige ADR próprio
  antes da SPEC-004 (H-11). Nenhum `setup()` de schema do LangGraph.
- `pgvector` (pacote Python) — adiado até existir consumidor real.
