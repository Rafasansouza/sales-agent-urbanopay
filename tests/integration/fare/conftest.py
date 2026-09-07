"""Fixtures dos testes de integração do Fare Engine.

Dados sintéticos usam linhas de teste inexistentes no seed oficial (8xx/9xx) e
são removidos por ID no teardown — a linha `999` fica reservada como
inexistente, conforme SPEC-001 §12. A linha oficial nunca é alterada.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from urbanopay.modules.fare.infrastructure.models import FareModel, FareRuleModel


class FareTestData:
    """Insere dados de teste rastreando IDs para limpeza determinística."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.fare_ids: list[uuid.UUID] = []
        self.rule_ids: list[uuid.UUID] = []

    async def add_fare(
        self,
        *,
        mode: str,
        line_code: str | None,
        fare_profile: str,
        amount: str,
        valid_from: datetime,
        valid_until: datetime | None = None,
    ) -> uuid.UUID:
        fare_id = uuid.uuid4()
        async with self._session_factory() as session:
            session.add(
                FareModel(
                    id=fare_id,
                    mode=mode,
                    line_code=line_code,
                    fare_profile=fare_profile,
                    amount=Decimal(amount),
                    valid_from=valid_from,
                    valid_until=valid_until,
                )
            )
            await session.commit()
        self.fare_ids.append(fare_id)
        return fare_id

    async def add_rule(
        self,
        *,
        trip_type: str,
        discount_percentage: str,
        valid_from: datetime,
        valid_until: datetime | None = None,
    ) -> uuid.UUID:
        rule_id = uuid.uuid4()
        async with self._session_factory() as session:
            session.add(
                FareRuleModel(
                    id=rule_id,
                    trip_type=trip_type,
                    discount_percentage=Decimal(discount_percentage),
                    valid_from=valid_from,
                    valid_until=valid_until,
                )
            )
            await session.commit()
        self.rule_ids.append(rule_id)
        return rule_id


@pytest_asyncio.fixture
async def fare_data(
    migrated: None,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[FareTestData]:
    data = FareTestData(session_factory)
    try:
        yield data
    finally:
        async with engine.begin() as conn:
            if data.fare_ids:
                await conn.execute(sa.delete(FareModel).where(FareModel.id.in_(data.fare_ids)))
            if data.rule_ids:
                await conn.execute(
                    sa.delete(FareRuleModel).where(FareRuleModel.id.in_(data.rule_ids))
                )
