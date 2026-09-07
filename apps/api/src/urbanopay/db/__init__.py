"""Camada de persistência.

Fonte: ADR-004 (PostgreSQL autoritativo), ADR-012 (Aceito).

Arquitetura decidida: SQLAlchemy 2.x com ORM declarativo tipado, psycopg 3,
runtime assíncrono (`AsyncSession`), Repository Pattern, Unit of Work e Alembic
para migrations.

Estado: **decidido, ainda não implementado**. A implementação nasce em tarefa
posterior, junto com a primeira SPEC que precisar dela.

Enquanto isso:

- as dependências previstas (SQLAlchemy, psycopg 3, Alembic) não foram
  instaladas;
- nenhum modelo, schema ou migration existe;
- `make migrate` falha deliberadamente, porque não há Alembic instalado.

Ver o README deste diretório e `docs/adr/ADR-012-persistence-orm-migrations.md`.
"""
