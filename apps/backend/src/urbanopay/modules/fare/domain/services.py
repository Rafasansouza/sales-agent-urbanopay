"""Serviços puros do domínio tarifário: classificação e cálculo.

Fonte: SPEC-001 §5 (classificação), §6 (ordem de cálculo), §7 (dinheiro),
§13 (invariantes). Nenhum I/O aqui — os dados chegam prontos e o resultado é
determinístico: mesma entrada + mesmas regras ⇒ mesmo resultado.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from urbanopay.modules.fare.domain.enums import FareProfile, TransportMode, TripType
from urbanopay.modules.fare.domain.errors import (
    EmptyTripError,
    FareRuleNotFoundError,
    UnsupportedTripCompositionError,
)
from urbanopay.modules.fare.domain.value_objects import (
    AppliedDiscount,
    CalculatedSegment,
    FareCalculation,
    percentage_of,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from urbanopay.modules.fare.domain.entities import Fare, FareRule
    from urbanopay.modules.fare.domain.value_objects import FareLookupKey, Segment


class TripClassifier:
    """Classifica o trajeto conforme SPEC-001 §5."""

    @staticmethod
    def classify(segments: Sequence[Segment]) -> TripType:
        if not segments:
            raise EmptyTripError

        if len(segments) == 1:
            return TripType.SINGLE

        modes = {segment.mode for segment in segments}
        if modes == {TransportMode.BUS}:
            return TripType.COMMON
        if TransportMode.BUS in modes and TransportMode.METRO in modes:
            return TripType.INTEGRATION

        # Dois ou mais segmentos exclusivamente de METRO: composição não
        # coberta pelas três classes da SPEC §5. Decisão registrada em A-04
        # (docs/OPEN-QUESTIONS.md): rejeitar com o erro tipado de §11 —
        # interpretação conservadora aprovada; nunca inventar categoria.
        raise UnsupportedTripCompositionError(
            "Trajeto com múltiplos segmentos exclusivamente de metrô não é suportado."
        )


class FareCalculator:
    """Executa a matemática tarifária (SPEC-001 §6, passos 5-10).

    Pré-condições (responsabilidade do chamador, validadas defensivamente):
    `fares` contém uma tarifa do perfil correto para cada segmento, vigente no
    instante de referência; `rule` está presente quando `trip_type` é
    INTEGRATION.
    """

    @staticmethod
    def calculate(
        profile: FareProfile,
        segments: Sequence[Segment],
        fares: Mapping[FareLookupKey, Fare],
        trip_type: TripType,
        rule: FareRule | None,
        reference_datetime: datetime,
    ) -> FareCalculation:
        calculated: list[CalculatedSegment] = []
        for segment in segments:
            fare = fares[segment.lookup_key]
            # Defesa da invariante §13: MEIA nunca usa tarifa integral e
            # vice-versa. Tarifa de perfil errado aqui é bug de repositório,
            # não erro de negócio.
            if fare.fare_profile is not profile:
                raise ValueError(
                    f"Tarifa {fare.id} é do perfil {fare.fare_profile}, esperado {profile}."
                )
            calculated.append(
                CalculatedSegment(
                    mode=segment.mode,
                    line_code=segment.line_code,
                    fare_amount=fare.amount,
                    fare_id=fare.id,
                )
            )

        subtotal = sum((item.fare_amount for item in calculated), start=Decimal("0"))

        discount: AppliedDiscount | None = None
        total = subtotal
        if trip_type is TripType.INTEGRATION:
            if rule is None:
                # Defesa: o serviço de aplicação já garante a regra vigente.
                raise FareRuleNotFoundError
            discount_amount = percentage_of(subtotal, rule.discount_percentage)
            discount = AppliedDiscount(
                type=TripType.INTEGRATION,
                percentage=rule.discount_percentage,
                amount=discount_amount,
                rule_id=rule.id,
            )
            total = subtotal - discount_amount

        return FareCalculation(
            fare_profile=profile,
            trip_type=trip_type,
            segments=tuple(calculated),
            subtotal=subtotal,
            discount=discount,
            total=total,
            reference_datetime=reference_datetime,
        )
