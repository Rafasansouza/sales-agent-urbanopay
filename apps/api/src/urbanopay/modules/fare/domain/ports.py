"""Ports do domínio tarifário (ADR-012, SPEC-001 §14).

Contratos que a infraestrutura implementa. `Protocol` para tipagem
estrutural: o domínio não é herdado pela infraestrutura e a direção de
dependência permanece limpa.

Contratos comuns:

- implementações devolvem entidades de domínio, nunca modelos ORM;
- implementações nunca executam commit;
- nenhuma regra de classificação ou cálculo aqui — apenas consulta;
- vigência é o intervalo semiaberto `[valid_from, valid_until)`, com
  `valid_until IS NULL` representando vigência aberta;
- falha de conectividade/disponibilidade do banco é traduzida para
  `FareServiceUnavailableError`; qualquer outro erro propaga intacto.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from urbanopay.modules.fare.domain.entities import Fare, FareRule
    from urbanopay.modules.fare.domain.enums import FareProfile, TripType
    from urbanopay.modules.fare.domain.value_objects import FareLookupKey


class FareRepository(Protocol):
    """Consulta de tarifas oficiais (SPEC-001 §2, §8)."""

    async def find_active_fares(
        self,
        profile: FareProfile,
        keys: frozenset[FareLookupKey],
        at: datetime,
    ) -> dict[FareLookupKey, Fare]:
        """Tarifas vigentes em `at` para o perfil, em uma única consulta.

        Chaves sem tarifa vigente simplesmente não aparecem no resultado — a
        decisão de qual erro levantar pertence à camada de aplicação.
        """
        ...

    async def known_bus_lines(self, line_codes: frozenset[str]) -> frozenset[str]:
        """Subconjunto de `line_codes` que já foi tarifado em qualquer período.

        Existe para distinguir `FARE_LINE_NOT_FOUND` (linha de ônibus que
        nunca existiu) de `FARE_NOT_AVAILABLE` (existe, mas nada vigente).
        Específico de BUS: METRO não possui linha.
        """
        ...


class FareRuleRepository(Protocol):
    """Consulta de regras tarifárias vigentes (SPEC-001 §5, §8)."""

    async def find_active_rule(self, trip_type: TripType, at: datetime) -> FareRule | None:
        """Regra vigente em `at` para a classificação, ou `None`.

        A não-sobreposição de vigências é garantida por constraint física:
        existe no máximo uma regra vigente por classificação em qualquer
        instante.
        """
        ...
