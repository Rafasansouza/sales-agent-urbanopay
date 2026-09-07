"""Fakes em memória dos ports do Fare Engine e dataset oficial de teste.

Os fakes implementam os `Protocol` de `domain/ports.py`, incluindo a semântica
de vigência semiaberta `[valid_from, valid_until)`. O dataset oficial é
DERIVADO da tabela aceita de SPEC-001 §2 — a mesma fonte da migration de seed,
duplicada de propósito: os testes validam a implementação contra a SPEC, não
contra ela mesma.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from urbanopay.modules.fare.domain.entities import Fare, FareRule
from urbanopay.modules.fare.domain.enums import FareProfile, TransportMode, TripType
from urbanopay.modules.fare.domain.errors import FareServiceUnavailableError
from urbanopay.modules.fare.domain.value_objects import FareLookupKey

# Instante de referência fixo dos testes: dentro da vigência oficial fictícia
# (2026-01-01Z, decisão aprovada do MVP) e determinístico.
FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
OFFICIAL_VALID_FROM = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

# Tabela aceita de SPEC-001 §2: linha -> (INTEGRAL, MEIA).
OFFICIAL_BUS_FARES: dict[str, tuple[str, str]] = {
    "101": ("6.00", "3.00"),
    "202": ("7.00", "3.50"),
    "303": ("8.00", "4.00"),
    "404": ("9.00", "4.50"),
    "505": ("10.00", "5.00"),
}
OFFICIAL_METRO_FARES: tuple[str, str] = ("10.00", "5.00")

OFFICIAL_INTEGRATION_DISCOUNT = "15.00"


def make_fare(
    mode: TransportMode,
    line_code: str | None,
    profile: FareProfile,
    amount: str,
    *,
    valid_from: datetime = OFFICIAL_VALID_FROM,
    valid_until: datetime | None = None,
    fare_id: uuid.UUID | None = None,
) -> Fare:
    return Fare(
        id=fare_id if fare_id is not None else uuid.uuid4(),
        mode=mode,
        line_code=line_code,
        fare_profile=profile,
        amount=Decimal(amount),
        valid_from=valid_from,
        valid_until=valid_until,
    )


def make_rule(
    percentage: str = OFFICIAL_INTEGRATION_DISCOUNT,
    *,
    valid_from: datetime = OFFICIAL_VALID_FROM,
    valid_until: datetime | None = None,
    rule_id: uuid.UUID | None = None,
) -> FareRule:
    return FareRule(
        id=rule_id if rule_id is not None else uuid.uuid4(),
        trip_type=TripType.INTEGRATION,
        discount_percentage=Decimal(percentage),
        valid_from=valid_from,
        valid_until=valid_until,
    )


def official_fares() -> list[Fare]:
    """As 12 tarifas oficiais derivadas de SPEC-001 §2."""
    fares: list[Fare] = []
    for line_code, (integral, meia) in OFFICIAL_BUS_FARES.items():
        fares.append(make_fare(TransportMode.BUS, line_code, FareProfile.INTEGRAL, integral))
        fares.append(make_fare(TransportMode.BUS, line_code, FareProfile.MEIA, meia))
    fares.append(
        make_fare(TransportMode.METRO, None, FareProfile.INTEGRAL, OFFICIAL_METRO_FARES[0])
    )
    fares.append(make_fare(TransportMode.METRO, None, FareProfile.MEIA, OFFICIAL_METRO_FARES[1]))
    return fares


def _is_active(valid_from: datetime, valid_until: datetime | None, at: datetime) -> bool:
    """Vigência semiaberta `[valid_from, valid_until)`; NULL = aberta."""
    return valid_from <= at and (valid_until is None or valid_until > at)


class InMemoryFareRepository:
    """Fake do port `FareRepository` respeitando perfil, chaves e vigência."""

    def __init__(self, fares: list[Fare]) -> None:
        self._fares = list(fares)

    async def find_active_fares(
        self,
        profile: FareProfile,
        keys: frozenset[FareLookupKey],
        at: datetime,
    ) -> dict[FareLookupKey, Fare]:
        result: dict[FareLookupKey, Fare] = {}
        for fare in self._fares:
            key = FareLookupKey(fare.mode, fare.line_code)
            if (
                fare.fare_profile is profile
                and key in keys
                and _is_active(fare.valid_from, fare.valid_until, at)
            ):
                result[key] = fare
        return result

    async def known_bus_lines(self, line_codes: frozenset[str]) -> frozenset[str]:
        return frozenset(
            fare.line_code
            for fare in self._fares
            if fare.mode is TransportMode.BUS
            and fare.line_code is not None
            and fare.line_code in line_codes
        )


class InMemoryFareRuleRepository:
    """Fake do port `FareRuleRepository`."""

    def __init__(self, rules: list[FareRule]) -> None:
        self._rules = list(rules)

    async def find_active_rule(self, trip_type: TripType, at: datetime) -> FareRule | None:
        for rule in self._rules:
            if rule.trip_type is trip_type and _is_active(rule.valid_from, rule.valid_until, at):
                return rule
        return None


class UnavailableFareRepository:
    """Fake que simula indisponibilidade de infraestrutura."""

    async def find_active_fares(
        self,
        profile: FareProfile,
        keys: frozenset[FareLookupKey],
        at: datetime,
    ) -> dict[FareLookupKey, Fare]:
        raise FareServiceUnavailableError

    async def known_bus_lines(self, line_codes: frozenset[str]) -> frozenset[str]:
        raise FareServiceUnavailableError
