"""Repository SQLAlchemy do módulo approvals (ADR-012, SPEC-003 §7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from urbanopay.modules.approvals.domain.entities import Approval
from urbanopay.modules.approvals.domain.enums import ApprovalStatus
from urbanopay.modules.approvals.infrastructure.models import ApprovalModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def _to_approval(model: ApprovalModel) -> Approval:
    return Approval(
        id=model.id,
        order_id=model.order_id,
        status=ApprovalStatus(model.status),
        requested_at=model.requested_at,
        decided_at=model.decided_at,
        decided_by=model.decided_by,
    )


class SqlAlchemyApprovalRepository:
    """Implementação do port `ApprovalRepository`. Nunca comita."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, approval: Approval) -> None:
        self._session.add(
            ApprovalModel(
                id=approval.id,
                order_id=approval.order_id,
                status=approval.status.value,
                requested_at=approval.requested_at,
                decided_at=approval.decided_at,
                decided_by=approval.decided_by,
            )
        )
        await self._session.flush()

    async def get_for_order(self, order_id: UUID) -> Approval | None:
        stmt = sa.select(ApprovalModel).where(ApprovalModel.order_id == order_id)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_approval(model) if model is not None else None

    async def get_for_order_for_update(self, order_id: UUID) -> Approval | None:
        # Segundo elo da ordem global de lock: o Order já está travado por
        # quem chamou.
        stmt = sa.select(ApprovalModel).where(ApprovalModel.order_id == order_id).with_for_update()
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_approval(model) if model is not None else None

    async def update(self, approval: Approval) -> None:
        stmt = (
            sa.update(ApprovalModel)
            .where(ApprovalModel.id == approval.id)
            .values(
                status=approval.status.value,
                decided_at=approval.decided_at,
                decided_by=approval.decided_by,
            )
        )
        await self._session.execute(stmt)
