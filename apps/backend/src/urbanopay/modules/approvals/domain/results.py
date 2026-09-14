"""Resultados de leitura do domínio de aprovação (SPEC-003 §7).

`ApprovalDecision` é a **projeção de consulta** da aprovação de um Order: o que
o cliente — e, por consequência, o Sales Agent — pode saber sobre a decisão
humana.

Deliberadamente **não** carrega `decided_by`. O ator é identificador opaco de
operador, existe para trilha de auditoria (§7) e não tem função na conversa:
expô-lo ampliaria a superfície de dado interno sem nenhum ganho para o cliente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from urbanopay.modules.approvals.domain.enums import ApprovalStatus

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """Estado da aprovação humana de um Order.

    `status is None` significa que **nenhuma `Approval` foi criada** — o caso
    normal de um Order que não exige aprovação, e também o de um Order que
    ainda não foi confirmado pelo cliente. Os dois se distinguem por
    `requires_approval`, congelado na criação do Order (§5).
    """

    order_id: UUID
    requires_approval: bool
    status: ApprovalStatus | None
    requested_at: datetime | None
    decided_at: datetime | None

    @property
    def is_pending(self) -> bool:
        """Existe decisão humana pendente bloqueando a jornada financeira."""
        return self.status is ApprovalStatus.PENDING
