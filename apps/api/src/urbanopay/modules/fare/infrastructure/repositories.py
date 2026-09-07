"""Repositories SQLAlchemy do Fare Engine (ADR-012, SPEC-001 §14).

Implementam os ports de `domain/ports.py` com a API 2.0 (`select` explícito).

Regras:

- devolvem entidades de domínio, nunca modelos ORM;
- nunca executam commit;
- nenhuma regra de classificação ou cálculo;
- nenhuma normalização silenciosa de `line_code`;
- somente falhas claras de conectividade/disponibilidade do banco viram
  `FareServiceUnavailableError`; erros de programação, mapping ou violação
  inesperada propagam intactos para permanecerem visíveis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import exc as sa_exc

from urbanopay.modules.fare.domain.entities import Fare, FareRule
from urbanopay.modules.fare.domain.enums import FareProfile, TransportMode, TripType
from urbanopay.modules.fare.domain.errors import FareServiceUnavailableError
from urbanopay.modules.fare.domain.value_objects import FareLookupKey
from urbanopay.modules.fare.infrastructure.models import FareModel, FareRuleModel

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

# Falhas traduzidas para indisponibilidade do Fare Engine. Restrito por
# decisão: OperationalError e InterfaceError são as classes DBAPI de falha de
# conexão/disponibilidade; TimeoutError é o esgotamento do pool. Programming,
# Data e Integrity errors NUNCA entram aqui — são bugs e devem aparecer.
_UNAVAILABILITY_ERRORS = (
    sa_exc.OperationalError,
    sa_exc.InterfaceError,
    sa_exc.TimeoutError,
)


async def _guarded[T](operation: Awaitable[T]) -> T:
    """Executa a operação traduzindo apenas indisponibilidade de banco."""
    try:
        return await operation
    except _UNAVAILABILITY_ERRORS as exc:
        # `from exc` preserva a causa original para observabilidade.
        raise FareServiceUnavailableError from exc


def _validity_window(
    model: type[FareModel] | type[FareRuleModel], at: datetime
) -> sa.ColumnElement[bool]:
    """Vigência semiaberta: valid_from <= at < valid_until (NULL = aberta)."""
    return sa.and_(
        model.valid_from <= at,
        sa.or_(model.valid_until.is_(None), model.valid_until > at),
    )


def _to_fare(model: FareModel) -> Fare:
    return Fare(
        id=model.id,
        mode=TransportMode(model.mode),
        line_code=model.line_code,
        fare_profile=FareProfile(model.fare_profile),
        amount=model.amount,
        valid_from=model.valid_from,
        valid_until=model.valid_until,
    )


def _to_fare_rule(model: FareRuleModel) -> FareRule:
    return FareRule(
        id=model.id,
        trip_type=TripType(model.trip_type),
        discount_percentage=model.discount_percentage,
        valid_from=model.valid_from,
        valid_until=model.valid_until,
    )


class SqlAlchemyFareRepository:
    """Implementação do port `FareRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_active_fares(
        self,
        profile: FareProfile,
        keys: frozenset[FareLookupKey],
        at: datetime,
    ) -> dict[FareLookupKey, Fare]:
        if not keys:
            return {}

        key_conditions = [
            sa.and_(
                FareModel.mode == key.mode.value,
                FareModel.line_code == key.line_code
                if key.line_code is not None
                else FareModel.line_code.is_(None),
            )
            for key in keys
        ]
        stmt = sa.select(FareModel).where(
            FareModel.fare_profile == profile.value,
            _validity_window(FareModel, at),
            sa.or_(*key_conditions),
        )

        result = await _guarded(self._session.execute(stmt))

        fares: dict[FareLookupKey, Fare] = {}
        for model in result.scalars():
            fare = _to_fare(model)
            # A EXCLUDE constraint garante no máximo uma tarifa vigente por
            # chave; o dict reflete essa unicidade.
            fares[FareLookupKey(fare.mode, fare.line_code)] = fare
        return fares

    async def known_bus_lines(self, line_codes: frozenset[str]) -> frozenset[str]:
        if not line_codes:
            return frozenset()

        stmt = sa.select(sa.distinct(FareModel.line_code)).where(
            FareModel.mode == TransportMode.BUS.value,
            FareModel.line_code.in_(line_codes),
        )
        result = await _guarded(self._session.execute(stmt))
        return frozenset(code for code in result.scalars() if code is not None)


class SqlAlchemyFareRuleRepository:
    """Implementação do port `FareRuleRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_active_rule(self, trip_type: TripType, at: datetime) -> FareRule | None:
        stmt = sa.select(FareRuleModel).where(
            FareRuleModel.trip_type == trip_type.value,
            _validity_window(FareRuleModel, at),
        )
        result = await _guarded(self._session.execute(stmt))
        model = result.scalar_one_or_none()
        return _to_fare_rule(model) if model is not None else None
