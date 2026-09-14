"""Domínio de cartões (SPEC-002): titularidade, masking e autoridade de perfil.

Camada pura — sem SQLAlchemy, psycopg, Alembic ou FastAPI. Este módulo não
depende de `identity` nem de `fare`: recebe `customer_id` opaco resolvido a
montante e entrega o perfil oficial como valor; a composição pertence à
orquestração futura (SPEC-004).
"""
