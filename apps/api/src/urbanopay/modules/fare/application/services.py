"""Serviço de aplicação do Fare Engine — o caso de uso `calculate_trip_fare`.

Fonte: SPEC-001 §6. Orquestra a ordem normativa de cálculo usando os ports do
domínio; será a base da tool estreita `calculate_trip_fare` da SPEC-004.

Este módulo depende apenas de `domain` — nunca de `infrastructure` (ADR-001).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from urbanopay.modules.fare.domain.enums import TransportMode, TripType
from urbanopay.modules.fare.domain.errors import (
    EmptyTripError,
    FareLineNotFoundError,
    FareNotAvailableError,
    FareRuleNotFoundError,
)
from urbanopay.modules.fare.domain.services import FareCalculator, TripClassifier
from urbanopay.modules.fare.domain.value_objects import (
    FareLookupKey,
    Segment,
    parse_fare_profile,
    parse_transport_mode,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from collections.abc import Set as AbstractSet

    from urbanopay.modules.fare.domain.ports import FareRepository, FareRuleRepository
    from urbanopay.modules.fare.domain.value_objects import FareCalculation


@dataclass(frozen=True, slots=True)
class SegmentInput:
    """Segmento bruto do contrato de entrada (SPEC-001 §9).

    Valores como chegam da borda; a validação semântica acontece no domínio.
    """

    mode: str
    line_code: str | None = None


class FareService:
    """Calcula tarifas oficiais de trajeto (SPEC-001).

    Somente leitura: nenhum commit, nenhuma mutação de estado. Os repositories
    chegam por injeção explícita (ADR-006); a composição decide de onde vem a
    sessão — `create_session_factory` diretamente ou `SqlAlchemyUnitOfWork`
    em fluxos transacionais futuros.
    """

    def __init__(self, fares: FareRepository, fare_rules: FareRuleRepository) -> None:
        self._fares = fares
        self._fare_rules = fare_rules

    async def calculate_trip_fare(
        self,
        fare_profile: str,
        segments: Sequence[SegmentInput],
        at: datetime | None = None,
    ) -> FareCalculation:
        """Executa a ordem normativa de SPEC-001 §6 e devolve o breakdown.

        `at` é o instante de referência da vigência; quando omitido, o agora
        em UTC. Ele é resolvido UMA única vez e usado idêntico na consulta de
        tarifas, na consulta da regra e no resultado auditável.
        """
        # §6.1 — validar request.
        if not segments:
            raise EmptyTripError

        # §6.2 — validar segmentos (estrutura, modal, linha).
        parsed = tuple(
            Segment(mode=parse_transport_mode(raw.mode), line_code=raw.line_code)
            for raw in segments
        )

        # §6.3 — validar perfil.
        profile = parse_fare_profile(fare_profile)

        # Instante de referência único para toda a operação: usado em §6.4, em
        # §6.8 e no resultado auditável.
        reference = at if at is not None else datetime.now(UTC)
        if reference.tzinfo is None:
            raise ValueError("O instante de referência deve ser timezone-aware.")

        # §6.4 — consultar tarifas vigentes (uma única consulta).
        keys = frozenset(segment.lookup_key for segment in parsed)
        fares = await self._fares.find_active_fares(profile, keys, reference)

        missing = keys - fares.keys()
        if missing:
            await self._raise_for_missing(missing)

        # §6.7 — classificar a viagem, na posição normativa da SPEC: DEPOIS da
        # consulta tarifária. A precedência de erros segue a ordem de §6 —
        # tarifa ausente (§6.4) precede composição não suportada (§6.7).
        # Metrô-só multi-segmento continua rejeitado aqui (A-04, decisão
        # inalterada); apenas o momento respeita o fluxo normativo.
        trip_type = TripClassifier.classify(parsed)

        # §6.8 — consultar regra vigente (somente INTEGRATION consulta; COMMON
        # e SINGLE têm 0% por definição da SPEC §5 — invariante estrutural).
        rule = None
        if trip_type is TripType.INTEGRATION:
            rule = await self._fare_rules.find_active_rule(TripType.INTEGRATION, reference)
            if rule is None:
                raise FareRuleNotFoundError

        # §6.5, §6.6, §6.9, §6.10, §6.11 — matemática pura no domínio.
        return FareCalculator.calculate(profile, parsed, fares, trip_type, rule, reference)

    async def _raise_for_missing(self, missing: AbstractSet[FareLookupKey]) -> None:
        """Traduz chaves sem tarifa vigente no erro correto (SPEC-001 §11).

        - BUS com linha que nunca foi tarifada → `FARE_LINE_NOT_FOUND`;
        - BUS conhecido sem tarifa vigente para perfil/data → `FARE_NOT_AVAILABLE`;
        - METRO sem tarifa vigente → `FARE_NOT_AVAILABLE` (METRO não possui
          linha e nunca produz `FARE_LINE_NOT_FOUND`).
        """
        missing_bus_lines = frozenset(
            key.line_code
            for key in missing
            if key.mode is TransportMode.BUS and key.line_code is not None
        )
        if missing_bus_lines:
            known = await self._fares.known_bus_lines(missing_bus_lines)
            unknown = sorted(missing_bus_lines - known)
            if unknown:
                raise FareLineNotFoundError(f"Linha(s) de ônibus desconhecida(s): {unknown}.")

        raise FareNotAvailableError
