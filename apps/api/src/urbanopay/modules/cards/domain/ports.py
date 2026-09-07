"""Ports do domínio de cartões (ADR-012, SPEC-002 §5).

Contratos comuns: entidades de domínio na saída, nunca ORM; sem commit;
nenhuma PII em exceção. Módulo somente leitura nesta SPEC — sem UoW próprio.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from urbanopay.modules.cards.domain.entities import Card


class CardRepository(Protocol):
    """Consulta de cartões, sempre escopada pelo cliente autenticado."""

    async def list_for_customer(self, customer_id: UUID) -> list[Card]: ...

    async def get_owned(self, customer_id: UUID, card_id: UUID) -> Card | None:
        """Cartão do cliente, em UMA única query com os dois filtros.

        `None` cobre indistintamente "não existe" e "pertence a outro
        cliente" — a aplicação traduz para `CARD_NOT_ACCESSIBLE` sem qualquer
        consulta prévia por `card_id` isolado (anti-enumeração, §5).
        """
        ...
