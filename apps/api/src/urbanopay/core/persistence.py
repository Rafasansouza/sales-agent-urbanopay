"""Port da fronteira transacional.

Fonte: ADR-012.

Este módulo define o contrato de Unit of Work que a camada de aplicação usa
para controlar a fronteira transacional. Ele pertence a `core` porque é
transversal aos módulos de domínio.

Restrição estrutural: **este módulo nunca importa SQLAlchemy**, psycopg ou
qualquer detalhe de infraestrutura. A implementação concreta vive em
`urbanopay.db.unit_of_work`, e a separação é verificada por teste de
arquitetura.

A `Session` do SQLAlchemy já é, por si, um Unit of Work. Esta abstração não
existe para suprir uma ausência da biblioteca; ela existe para:

1. impedir que `AsyncSession` vaze para `application` e `domain`;
2. coordenar vários repositories na mesma transação;
3. tornar commit e rollback explícitos no ponto da decisão de negócio;
4. permitir testes da camada de aplicação com implementações falsas.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self, runtime_checkable


@runtime_checkable
class UnitOfWork(Protocol):
    """Contrato mínimo da fronteira transacional.

    Semântica exigida de toda implementação:

    - `commit` é sempre **explícito**: nenhuma saída de contexto confirma
      trabalho pendente;
    - sair do contexto sem `commit` desfaz o trabalho pendente (rollback);
    - sair do contexto por exceção desfaz o trabalho pendente;
    - os recursos da unidade de trabalho são sempre liberados na saída;
    - uma instância atende a **uma** unidade de trabalho por vez e nunca é
      compartilhada entre tasks concorrentes.

    Este port não expõe repositories: eles ainda não existem. Quando o
    primeiro módulo de domínio ganhar persistência, seu Unit of Work
    específico estenderá este contrato com os repositories daquele domínio,
    definidos por `Protocol` em `modules/<dominio>/domain/ports.py`.
    """

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None:
        """Confirma o trabalho pendente. Somente a aplicação decide chamar."""
        ...

    async def rollback(self) -> None:
        """Desfaz o trabalho pendente."""
        ...
