"""Resultados de saída da aplicação de fulfillment (SPEC-005 §6, §12.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from urbanopay.modules.fulfillment.domain.entities import (
        CardLedgerEntry,
        Fulfillment,
        Receipt,
    )


@dataclass(frozen=True, slots=True)
class FulfillmentResult:
    """Desfecho de `fulfill_order`.

    `replayed=True` significa que o efeito já existia e **nada** novo foi
    aplicado: nenhum crédito, nenhum comprovante. O resultado devolvido é o
    persistido anteriormente. A distinção fica explícita para quem chama, em
    vez de silenciosa.
    """

    fulfillment: Fulfillment
    ledger_entry: CardLedgerEntry
    receipt: Receipt
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    """Achados de consistência (SPEC-005 §12.1).

    **Detecção, nunca reparo.** Nenhum campo aqui autoriza crédito: são listas
    de `order_id` para análise. Um relatório vazio é a expectativa em operação
    normal, e as métricas da §18 (`duplicate_fulfillment_effects = 0`,
    `paid_orders_without_known_fulfillment_state = 0`) se leem daqui.
    """

    eligible_orders: list[UUID] = field(default_factory=list)
    completed_without_ledger: list[UUID] = field(default_factory=list)
    ledger_without_completed: list[UUID] = field(default_factory=list)

    @property
    def has_grave_inconsistency(self) -> bool:
        """Fulfillment `COMPLETED` sem ledger é o achado que não pode existir."""
        return bool(self.completed_without_ledger)

    @property
    def is_clean(self) -> bool:
        return not (
            self.eligible_orders or self.completed_without_ledger or self.ledger_without_completed
        )
