"""Tool tarifária (SPEC-001, SPEC-004 §7).

O Fare Engine é a única autoridade do cálculo. O modelo escolhe **perguntar**;
nunca calcula, nunca estima e nunca preenche uma lacuna com valor plausível —
nenhum erro de SPEC-001 §11 autoriza fallback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from urbanopay.modules.agent.application import presenters
from urbanopay.modules.agent.domain.results import NextAction, ResultType, ToolResult
from urbanopay.modules.cards.domain.enums import FareProfileSource
from urbanopay.modules.fare.application.services import SegmentInput

if TYPE_CHECKING:
    from urbanopay.modules.agent.application.schemas import CalculateTripFareInput
    from urbanopay.modules.agent.application.tools import ToolContext


async def calculate_trip_fare(ctx: ToolContext, payload: CalculateTripFareInput) -> ToolResult:
    """Tarifa oficial de um trajeto (SPEC-001 §6).

    O perfil declarado só vale enquanto não houver cartão: numa sessão
    autenticada com cartão selecionado, o perfil **oficial do cartão**
    substitui a declaração (SPEC-002 §8, §15). É por isso que "meu cartão é
    meia" não muda o preço — a afirmação nem chega ao cálculo.

    O resultado carrega `profile_source` e `profile_verified` para que a
    resposta possa dizer de onde veio o perfil, em vez de deixar o modelo
    supor.
    """
    fare_profile = payload.declared_fare_profile
    profile_source = FareProfileSource.USER_DECLARED.value
    profile_verified = False

    if ctx.customer_id is not None and ctx.state.selected_card_id is not None:
        resolution = await ctx.services.cards.resolve_official_fare_profile(
            ctx.customer_id, ctx.state.selected_card_id
        )
        fare_profile = resolution.official_profile.value
        profile_source = resolution.source.value
        profile_verified = resolution.verified

    calculation = await ctx.services.fare.calculate_trip_fare(
        fare_profile=fare_profile,
        segments=[
            SegmentInput(mode=segment.mode, line_code=segment.line_code)
            for segment in payload.segments
        ],
    )
    return ToolResult.success(
        ResultType.FARE_CALCULATION,
        presenters.fare_calculation(
            calculation,
            profile_source=profile_source,
            profile_verified=profile_verified,
        ),
        next_action=NextAction.CONTINUE,
    )
