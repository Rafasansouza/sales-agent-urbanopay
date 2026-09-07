"""Ports do domínio de Orders (ADR-012).

Contratos comuns:

- implementações devolvem entidades de domínio, nunca modelos ORM;
- implementações **nunca** executam commit — a fronteira transacional é do
  Unit of Work, controlado pela aplicação;
- nenhuma exceção de repository carrega PII ou valor monetário;
- **ordem global de lock, única em toda a base:
  `Order → Approval → Payment → Card → Fulfillment`** (ADR-012). Toda
  transação que toque mais de um desses agregados adquire os locks nessa
  ordem, para evitar deadlock. Deste módulo participam os três primeiros
  elos; `Card` e `Fulfillment` entram com a SPEC-005.

Sobre acesso por titularidade: as consultas do cliente recebem `customer_id` e
`order_id`/`quote_id` **na mesma query**, jamais em duas etapas. Buscar
primeiro e comparar depois vaza a existência do recurso pelo tempo de resposta
e pelo caminho de erro — o mesmo raciocínio do `get_owned` da SPEC-002.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from urbanopay.core.persistence import UnitOfWork

if TYPE_CHECKING:
    from uuid import UUID

    from urbanopay.core.idempotency import IdempotencyRepository
    from urbanopay.modules.approvals.domain.ports import ApprovalRepository
    from urbanopay.modules.orders.domain.entities import Order, Quote


class QuoteRepository(Protocol):
    """Persistência de Quotes e dos seus itens congelados."""

    async def add(self, quote: Quote) -> None: ...

    async def get_owned(self, *, customer_id: UUID, quote_id: UUID) -> Quote | None:
        """Quote do cliente, ou `None` se inexistente **ou** de outro cliente.

        Uma única query com os dois filtros: o chamador não consegue
        distinguir os dois casos, e traduz `None` para
        `QUOTE_NOT_ACCESSIBLE`.
        """
        ...


class OrderRepository(Protocol):
    """Persistência de Orders e dos seus itens congelados."""

    async def add(self, order: Order) -> None: ...

    async def get(self, order_id: UUID) -> Order | None:
        """Consulta sem filtro de titularidade.

        Uso restrito a atores que não são o cliente — a superfície
        administrativa de aprovação (A-07) e os aplicadores de estado de
        pagamento, que operam a partir do `Payment`. Fluxo de cliente usa
        `get_owned`.
        """
        ...

    async def get_owned(self, *, customer_id: UUID, order_id: UUID) -> Order | None:
        """Order do cliente, ou `None` se inexistente **ou** de outro cliente."""
        ...

    async def get_for_update(self, order_id: UUID) -> Order | None:
        """Carrega o Order com lock de linha (`SELECT ... FOR UPDATE`).

        Primeiro elo da ordem global de lock. Qualquer transação que também
        vá travar `Approval` ou `Payment` adquire este lock antes.
        """
        ...

    async def get_owned_for_update(self, *, customer_id: UUID, order_id: UUID) -> Order | None:
        """Combina titularidade e lock de linha em uma única query."""
        ...

    async def update(self, order: Order) -> None:
        """Persiste a nova versão do Order.

        Os itens são congelados na criação (§5) e nunca são atualizados aqui.
        """
        ...

    async def has_quote_been_consumed(self, quote_id: UUID) -> bool:
        """Indica se já existe Order referenciando esta Quote (§4).

        O consumo da Quote é o fato relacional de existir tal Order — não há
        coluna de status a consultar.
        """
        ...


@runtime_checkable
class OrdersUnitOfWork(UnitOfWork, Protocol):
    """Fronteira transacional do módulo, com seus repositories.

    Inclui `idempotency` porque `create_order` e `confirm_order` são operações
    locais: reivindicar a key, aplicar o efeito e marcar `COMPLETED` acontecem
    na **mesma** transação (SPEC-003 §11.2). Sem o registro na mesma unidade
    de trabalho, existiria `IN_PROGRESS` órfão.

    Inclui `approvals` porque a confirmação de um Order que exige aprovação
    **cria a `Approval` em `PENDING` na mesma transação** (§7, §8): duas
    transações separadas admitiriam um Order em `REQUIRES_APPROVAL` sem
    aprovação correspondente. O tipo é o port público de `approvals`; a
    dependência é unidirecional — `approvals` nunca importa `orders`.
    """

    quotes: QuoteRepository
    orders: OrderRepository
    approvals: ApprovalRepository
    idempotency: IdempotencyRepository
