"""Enums do domínio tarifário (SPEC-001 §3, §4, §5)."""

from __future__ import annotations

from enum import StrEnum


class TransportMode(StrEnum):
    """Modais suportados (SPEC-001 §4)."""

    BUS = "BUS"
    METRO = "METRO"


class FareProfile(StrEnum):
    """Perfis tarifários (SPEC-001 §3)."""

    INTEGRAL = "INTEGRAL"
    MEIA = "MEIA"


class TripType(StrEnum):
    """Classificação da viagem (SPEC-001 §5)."""

    SINGLE = "SINGLE"
    COMMON = "COMMON"
    INTEGRATION = "INTEGRATION"
