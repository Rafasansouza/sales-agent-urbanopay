"""Camada de persistência.

Fonte: ADR-004 (PostgreSQL autoritativo), ADR-012 (Aceito).

Foundation **implementada** nesta camada:

- `base.py` — `Base` declarativa e `NAMING_CONVENTION` determinística;
- `engine.py` — fábrica do `AsyncEngine` (psycopg 3, `postgresql+psycopg`);
- `session.py` — `async_sessionmaker` com `expire_on_commit=False`;
- `unit_of_work.py` — implementação SQLAlchemy do port
  `urbanopay.core.persistence.UnitOfWork`;
- `registry.py` — agregação de models para o Alembic;
- `migrations/` — ambiente do Alembic (sem revisions ainda).

O que **não** existe, por decisão: modelos funcionais, repositories e
migrations de negócio — nascem com as SPECs. Nenhum endpoint consome o banco
ainda, então a API não cria engine no startup.

Ver o README deste diretório e `docs/adr/ADR-012-persistence-orm-migrations.md`.
"""
