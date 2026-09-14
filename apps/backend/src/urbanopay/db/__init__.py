"""Camada de persistência.

Fonte: ADR-004 (PostgreSQL autoritativo), ADR-012 (Aceito).

Foundation **implementada** nesta camada:

- `base.py` — `Base` declarativa e `NAMING_CONVENTION` determinística;
- `engine.py` — fábrica do `AsyncEngine` (psycopg 3, `postgresql+psycopg`);
- `session.py` — `async_sessionmaker` com `expire_on_commit=False`;
- `unit_of_work.py` — implementação SQLAlchemy do port
  `urbanopay.core.persistence.UnitOfWork`;
- `registry.py` — agregação de models para o Alembic (registrados: fare);
- `migrations/` — ambiente do Alembic com as revisions do Fare Engine
  (`fare0001` schema, `fare0002` dados de referência).

A persistência dos demais módulos nasce com as respectivas SPECs. Nenhum
endpoint consome o banco ainda, então a API não cria engine no startup.

Ver o README deste diretório e `docs/adr/ADR-012-persistence-orm-migrations.md`.
"""
