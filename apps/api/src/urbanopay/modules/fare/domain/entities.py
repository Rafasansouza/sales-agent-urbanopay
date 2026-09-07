"""Entidades do domínio tarifário (SPEC-001 §2, §8).

Puras: dataclasses imutáveis, sem qualquer dependência de persistência. O
mapeamento de/para ORM acontece exclusivamente em
`modules/fare/infrastructure/repositories.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from urbanopay.modules.fare.domain.enums import FareProfile, TransportMode, TripType

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class Fare:
    """Tarifa oficial vigente em um período (SPEC-001 §2, §8).

    A vigência é o intervalo semiaberto `[valid_from, valid_until)`;
    `valid_until is None` significa vigência aberta. Alteração futura encerra
    a vigência anterior — nunca sobrescreve histórico (§8).
    """

    id: UUID
    mode: TransportMode
    line_code: str | None
    fare_profile: FareProfile
    amount: Decimal
    valid_from: datetime
    valid_until: datetime | None


@dataclass(frozen=True, slots=True)
class FareRule:
    """Regra tarifária vigente por classificação de viagem (SPEC-001 §5, §8).

    No MVP existe apenas a regra de INTEGRATION (desconto inicial de 15%,
    persistido como dado — nunca hardcoded). COMMON e SINGLE têm desconto 0%
    por definição da SPEC §5 e não consultam regra.
    """

    id: UUID
    trip_type: TripType
    discount_percentage: Decimal
    valid_from: datetime
    valid_until: datetime | None
