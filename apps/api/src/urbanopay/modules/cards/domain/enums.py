"""Enums do domínio de cartões (SPEC-002 §2, §8)."""

from __future__ import annotations

from enum import StrEnum


class CardStatus(StrEnum):
    """Status do cartão (SPEC-002 §2). Nenhuma transição é operada nesta SPEC."""

    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class FareProfile(StrEnum):
    """Perfis tarifários (SPEC-002 §2).

    Enum próprio do módulo — mesmo conjunto de valores do Fare Engine, sem
    import entre módulos: a fronteira com o fare é o valor string, que
    `FareService.calculate_trip_fare` valida (decisão do plano aprovado).
    """

    INTEGRAL = "INTEGRAL"
    MEIA = "MEIA"


class FareProfileSource(StrEnum):
    """Origem do perfil no contrato de §8."""

    USER_DECLARED = "USER_DECLARED"
    CARD = "CARD"
