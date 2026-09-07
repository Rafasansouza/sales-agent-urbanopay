"""Ports do domínio de aprovação (ADR-012).

`ApprovalRepository` é a **interface pública** do módulo: é assim que `orders`
cria e decide aprovações dentro da sua própria transação, sem tocar tabela
alheia e sem que `approvals` precise conhecer `orders`.

Ordem global de lock, única em toda a base:
`Order → Approval → Payment → Card → Fulfillment` (ADR-012).
`get_for_order_for_update` é sempre chamado **depois** do lock do Order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from urbanopay.modules.approvals.domain.entities import Approval


class ApprovalRepository(Protocol):
    """Persistência de aprovações. Nunca executa commit."""

    async def add(self, approval: Approval) -> None: ...

    async def get_for_order(self, order_id: UUID) -> Approval | None: ...

    async def get_for_order_for_update(self, order_id: UUID) -> Approval | None:
        """Aprovação do Order com lock de linha (`SELECT ... FOR UPDATE`).

        Segundo elo da ordem global de lock: exige que o Order já esteja
        travado pela mesma transação.
        """
        ...

    async def update(self, approval: Approval) -> None: ...
