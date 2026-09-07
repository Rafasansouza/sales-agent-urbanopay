"""Registro dos modelos ORM para o Alembic.

Fonte: ADR-012.

Este módulo é o **único** ponto do projeto que conhece todos os módulos de
domínio, e existe exclusivamente porque o Alembic precisa de um `MetaData`
com todas as tabelas para autogenerate e `alembic check`.

Como funciona: importar um módulo de models registra suas tabelas em
`Base.metadata` como efeito colateral da declaração das classes. O `env.py`
do Alembic importa **este** módulo e, através dele, enxerga o schema completo.

Estado atual: **nenhum modelo funcional existe** — as SPECs ainda não foram
implementadas. O metadata permanece válido vazio, e é assim por decisão:
nenhuma tabela placeholder, nenhum import fictício.

Quando o primeiro módulo de domínio ganhar persistência, adicione aqui o
import dos seus models, no padrão:

    from urbanopay.modules.<dominio>.infrastructure import models as _<dominio>  # noqa: F401

Este módulo não é ponto de acoplamento entre domínios: nenhum código de
aplicação ou de domínio deve importá-lo. Consumidores legítimos são o `env.py`
do Alembic e os testes de migration.
"""

from __future__ import annotations

from sqlalchemy import MetaData

from urbanopay.db.base import Base

# Imports de models entram aqui, um por módulo de domínio, quando existirem.
# (nenhum ainda)


def target_metadata() -> MetaData:
    """Devolve o metadata completo da aplicação para o Alembic."""
    return Base.metadata
