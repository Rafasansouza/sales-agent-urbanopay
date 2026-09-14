"""Persistência dos registros de idempotência (SPEC-003 §11; ADR-009, ADR-012).

Concern transversal, por isso vive em `db/` e não em um módulo de domínio: o
contrato está em `core.idempotency`, e `orders`, `approvals` e `payments`
compartilham esta implementação.

Os registros ficam no **PostgreSQL**, nunca no Redis (ADR-009): Redis não é
autoridade de idempotência financeira, e perder o Redis pode custar
velocidade, nunca histórico.

A unicidade `(operation, key)` é uma constraint de banco, não uma verificação
em memória. É ela que faz a reivindicação ser atômica sob concorrência real.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from urbanopay.core.idempotency import (
    IdempotencyClaim,
    IdempotencyRecord,
    IdempotencyStatus,
)
from urbanopay.db.base import Base

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_CLAIM_ATTEMPTS = 2


class IdempotencyRecordModel(Base):
    """Registro de idempotência de um comando crítico (SPEC-003 §11)."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        # Escopo de unicidade da §11. Base de toda a garantia de não
        # duplicação de efeito financeiro.
        # Sem `name=` explícito: a convenção de `db.base` gera
        # `uq_idempotency_records_operation_key`. Nome literal aqui
        # sobrescreveria a convenção e divergiria da migration.
        sa.UniqueConstraint("operation", "key"),
        sa.CheckConstraint("status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')", name="status_valid"),
        # `COMPLETED` e `FAILED` são desfechos: têm instante de conclusão.
        # `IN_PROGRESS` não tem. Impede registro "concluído" sem quando.
        sa.CheckConstraint(
            "(status = 'IN_PROGRESS' AND completed_at IS NULL)"
            " OR (status <> 'IN_PROGRESS' AND completed_at IS NOT NULL)",
            name="completed_at_matches_status",
        ),
        sa.Index("ix_idempotency_records_status_updated_at", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    operation: Mapped[str] = mapped_column(sa.Text())
    key: Mapped[str] = mapped_column(sa.Text())
    request_fingerprint: Mapped[str] = mapped_column(sa.Text())
    status: Mapped[str] = mapped_column(sa.Text())
    # Sem chave estrangeira: o recurso alvo varia por operação (Order,
    # Payment). Uma FK exigiria uma coluna por tipo, ou uma tabela por
    # operação, sem ganho de integridade real.
    resource_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    response_reference: Mapped[str | None] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True))


def _to_record(model: IdempotencyRecordModel) -> IdempotencyRecord:
    return IdempotencyRecord(
        key=model.key,
        operation=model.operation,
        request_fingerprint=model.request_fingerprint,
        status=IdempotencyStatus(model.status),
        resource_id=model.resource_id,
        response_reference=model.response_reference,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


class SqlAlchemyIdempotencyRepository:
    """Implementação do port `IdempotencyRepository`. Nunca comita."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self, *, operation: str, key: str, fingerprint: str, at: datetime
    ) -> IdempotencyClaim:
        """Reivindica a key com `INSERT ... ON CONFLICT DO NOTHING`.

        Duas tentativas, não por retry cego: se a inserção não aconteceu e a
        leitura seguinte também não encontra o registro, a única explicação é
        que a transação concorrente abortou entre os dois passos — e nesse
        caso a key está livre e deve ser reivindicada. Não há espera ativa
        nem laço indefinido.
        """
        for _ in range(_CLAIM_ATTEMPTS):
            stmt = (
                pg_insert(IdempotencyRecordModel)
                .values(
                    id=uuid.uuid4(),
                    operation=operation,
                    key=key,
                    request_fingerprint=fingerprint,
                    status=IdempotencyStatus.IN_PROGRESS.value,
                    resource_id=None,
                    response_reference=None,
                    created_at=at,
                    updated_at=at,
                    completed_at=None,
                )
                .on_conflict_do_nothing(index_elements=["operation", "key"])
                .returning(IdempotencyRecordModel.id)
            )
            inserted = (await self._session.execute(stmt)).scalar_one_or_none()
            if inserted is not None:
                return IdempotencyClaim(acquired=True, existing=None)

            existing = await self.get(operation=operation, key=key)
            if existing is not None:
                return IdempotencyClaim(acquired=False, existing=existing)

        # Invariante do port: quando não adquirimos, existe registro. Chegar
        # aqui significa inconsistência real, não condição de corrida normal.
        raise RuntimeError("Registro de idempotência não pôde ser reivindicado nem localizado.")

    async def get(self, *, operation: str, key: str) -> IdempotencyRecord | None:
        stmt = sa.select(IdempotencyRecordModel).where(
            IdempotencyRecordModel.operation == operation,
            IdempotencyRecordModel.key == key,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_record(model) if model is not None else None

    async def complete(
        self,
        *,
        operation: str,
        key: str,
        resource_id: uuid.UUID | None,
        response_reference: str | None,
        at: datetime,
    ) -> None:
        """Marca `COMPLETED` — resultado conhecido, qualquer que seja ele."""
        await self._set_outcome(
            operation=operation,
            key=key,
            status=IdempotencyStatus.COMPLETED,
            resource_id=resource_id,
            response_reference=response_reference,
            at=at,
        )

    async def fail(
        self, *, operation: str, key: str, response_reference: str | None, at: datetime
    ) -> None:
        """Marca `FAILED` — falha determinística a reproduzir em replay."""
        await self._set_outcome(
            operation=operation,
            key=key,
            status=IdempotencyStatus.FAILED,
            resource_id=None,
            response_reference=response_reference,
            at=at,
        )

    async def _set_outcome(
        self,
        *,
        operation: str,
        key: str,
        status: IdempotencyStatus,
        resource_id: uuid.UUID | None,
        response_reference: str | None,
        at: datetime,
    ) -> None:
        values: dict[str, object] = {
            "status": status.value,
            "response_reference": response_reference,
            "updated_at": at,
            "completed_at": at,
        }
        if resource_id is not None:
            # Nunca apaga um `resource_id` já registrado: em reconciliação, a
            # conclusão pode chegar sem repetir a referência do recurso.
            values["resource_id"] = resource_id
        stmt = (
            sa.update(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.operation == operation,
                IdempotencyRecordModel.key == key,
            )
            .values(**values)
        )
        await self._session.execute(stmt)
