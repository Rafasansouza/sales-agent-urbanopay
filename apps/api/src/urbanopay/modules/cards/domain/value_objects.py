"""Value objects da autoridade de perfil tarifário (SPEC-002 §8).

`FARE_PROFILE_CHANGED` é um **sinal semântico de resultado, não exceção**
(decisão A-11 aprovada): a SPEC-002 apenas DETECTA a divergência entre o
perfil declarado e o oficial; recálculo, invalidação de Quote e fluxo da
jornada pertencem às SPEC-003/004.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from urbanopay.modules.cards.domain.enums import FareProfile, FareProfileSource

if TYPE_CHECKING:
    from uuid import UUID


class ProfileSignal(StrEnum):
    """Sinais semânticos da resolução de perfil."""

    FARE_PROFILE_CHANGED = "FARE_PROFILE_CHANGED"


@dataclass(frozen=True, slots=True)
class ProfileResolutionResult:
    """Resultado da resolução do perfil oficial (contrato de §8).

    O perfil oficial vem SEMPRE do cartão (`source=CARD`, `verified=True`);
    a declaração do usuário nunca o substitui. `signal` carrega
    `FARE_PROFILE_CHANGED` quando houve declaração divergente — informação
    suficiente para a orquestração futura acionar o recálculo.
    """

    card_id: UUID
    official_profile: FareProfile
    source: FareProfileSource
    verified: bool
    declared_profile: FareProfile | None
    signal: ProfileSignal | None


def detect_profile_divergence(
    declared: FareProfile | None,
    official: FareProfile,
) -> ProfileSignal | None:
    """Compara declarado × oficial; divergência ⇒ `FARE_PROFILE_CHANGED`."""
    if declared is not None and declared is not official:
        return ProfileSignal.FARE_PROFILE_CHANGED
    return None
