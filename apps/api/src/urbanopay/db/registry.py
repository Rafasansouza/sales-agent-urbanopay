"""Registro dos modelos ORM para o Alembic.

Fonte: ADR-012.

Este módulo é o **único** ponto do projeto que conhece todos os módulos de
domínio, e existe exclusivamente porque o Alembic precisa de um `MetaData`
com todas as tabelas para autogenerate e `alembic check`.

Como funciona: importar um módulo de models registra suas tabelas em
`Base.metadata` como efeito colateral da declaração das classes. O `env.py`
do Alembic importa **este** módulo e, através dele, enxerga o schema completo.

Estado atual: SPEC-001 (`fare`), SPEC-002 (`identity`, `cards`), SPEC-003
(`orders`, `approvals`, `payments`, além da tabela transversal de
idempotência) e SPEC-005 (`fulfillment`) possuem modelos registrados. Nenhuma tabela placeholder e
nenhum import fictício: um módulo só aparece aqui quando tem persistência
real.

Ao dar persistência a um novo módulo de domínio, adicione aqui o import dos
seus models, no padrão:

    from urbanopay.modules.<dominio>.infrastructure import models as _<dominio>  # noqa: F401

Este módulo não é ponto de acoplamento entre domínios: nenhum código de
aplicação ou de domínio deve importá-lo. Consumidores legítimos são o `env.py`
do Alembic e os testes de migration.
"""

from __future__ import annotations

from sqlalchemy import MetaData

# Importar um módulo de models registra suas tabelas em `Base.metadata` como
# efeito colateral da declaração das classes — é para isso que estes imports
# existem, e é por isso que carregam `noqa: F401`.
#
# `db.idempotency` é a tabela transversal da SPEC-003 §11: não pertence a
# nenhum módulo de domínio, por isso vem de `db` e não de `modules`.
from urbanopay.db import idempotency as _idempotency_models  # noqa: F401
from urbanopay.db.base import Base
from urbanopay.modules.approvals.infrastructure import models as _approvals_models  # noqa: F401
from urbanopay.modules.cards.infrastructure import models as _cards_models  # noqa: F401
from urbanopay.modules.fare.infrastructure import models as _fare_models  # noqa: F401
from urbanopay.modules.fulfillment.infrastructure import models as _fulfillment_models  # noqa: F401
from urbanopay.modules.identity.infrastructure import models as _identity_models  # noqa: F401
from urbanopay.modules.orders.infrastructure import models as _orders_models  # noqa: F401
from urbanopay.modules.payments.infrastructure import models as _payments_models  # noqa: F401


def target_metadata() -> MetaData:
    """Devolve o metadata completo da aplicação para o Alembic."""
    return Base.metadata
