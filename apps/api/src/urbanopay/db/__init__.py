"""Camada de persistência.

Fonte: ADR-004 (PostgreSQL autoritativo), ADR-012 (**Proposta**).

Estado: vazio por decisão. O ADR-012 — que define driver, camada de acesso a
dados e ferramenta de migrations — está com status `Proposta`.

Enquanto não for aceito:

- nenhuma dependência de banco existe no projeto;
- nenhum modelo, schema ou migration deve ser criado;
- `make migrate` falha deliberadamente.

Ver o README deste diretório e `docs/adr/ADR-012-persistence-orm-migrations.md`.
"""
