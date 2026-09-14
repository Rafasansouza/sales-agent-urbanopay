"""Base declarativa e convenção de nomes do schema.

Fonte: ADR-012.

Este módulo define a única `DeclarativeBase` da aplicação e a convenção
determinística de nomes para constraints e índices. Sem nomes determinísticos,
o Alembic não consegue alterar nem remover objetos criados anonimamente.

Regras:

- nenhuma tabela é declarada aqui;
- nenhuma regra de domínio pertence a este módulo;
- modelos ORM concretos vivem em `modules/<dominio>/infrastructure/models.py`
  e são agregados por `urbanopay.db.registry` para o Alembic.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Convenção única de produção. Testes que precisem de um MetaData próprio devem
# importar ESTA constante — nunca copiá-la —, para que teste e produção não
# possam divergir.
#
# A chave `ck` usa %(constraint_name)s: toda CheckConstraint deve ser criada
# com `name=` explícito, senão a geração do nome falha — o que é proposital,
# porque constraint anônima é exatamente o que queremos impedir.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarativa única da aplicação.

    Todos os modelos ORM herdam desta classe, o que garante um único
    `MetaData` — requisito do Alembic para autogenerate e `alembic check`.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
