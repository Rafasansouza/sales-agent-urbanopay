"""Entidade `Approval` (SPEC-003 §7).

Domínio puro e imutável: as decisões são funções que devolvem nova instância.
`approvals` **não importa `orders`** — o efeito da decisão sobre o Order é
aplicado pela camada de aplicação de `orders`, que é quem detém a transação
(`approve_order` é operação do Order, conforme SPEC-003 §11).

Auditoria: toda decisão registra **ator e instante** (§7). O ator é um
identificador opaco de operador — nunca nome, e-mail ou CPF.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from urbanopay.modules.approvals.domain.enums import ApprovalStatus
from urbanopay.modules.approvals.domain.errors import InvalidApprovalStateError

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class Approval:
    """Pedido de aprovação humana de um Order (SPEC-003 §7).

    Criada em `PENDING` no mesmo instante em que o cliente confirma um Order
    com `requires_approval = true` (§8, §14).
    """

    id: UUID
    order_id: UUID
    status: ApprovalStatus
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None

    @property
    def is_pending(self) -> bool:
        return self.status is ApprovalStatus.PENDING

    def _decide(self, status: ApprovalStatus, actor: str, at: datetime) -> Approval:
        if not self.is_pending:
            raise InvalidApprovalStateError
        return replace(self, status=status, decided_at=at, decided_by=actor)

    def approve(self, actor: str, at: datetime) -> Approval:
        """`PENDING → APPROVED` (§7). Terminal não é redecidido."""
        return self._decide(ApprovalStatus.APPROVED, actor, at)

    def reject(self, actor: str, at: datetime) -> Approval:
        """`PENDING → REJECTED` (§7). Terminal não é redecidido."""
        return self._decide(ApprovalStatus.REJECTED, actor, at)
