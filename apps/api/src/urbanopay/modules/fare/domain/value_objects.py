"""Value objects do Fare Engine (SPEC-001 §4, §7, §10).

Todos imutáveis. Dinheiro é sempre `Decimal` — nunca float em nenhum ponto do
caminho (SPEC-001 §7), o que é verificado por teste AST sobre este módulo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from urbanopay.modules.fare.domain.enums import FareProfile, TransportMode, TripType
from urbanopay.modules.fare.domain.errors import (
    BusLineRequiredError,
    InvalidFareProfileError,
    InvalidSegmentStructureError,
    InvalidTransportModeError,
)

if TYPE_CHECKING:
    from uuid import UUID

# Moeda do contrato de saída (SPEC-001 §10). A SPEC não modela moeda por
# tarifa; é uma constante do domínio no MVP.
CURRENCY = "BRL"

_TWO_PLACES = Decimal("0.01")
_HUNDRED = Decimal("100")


def to_money(value: Decimal) -> Decimal:
    """Arredonda para 2 casas com ROUND_HALF_UP (SPEC-001 §7).

    Este é o único ponto de arredondamento monetário do sistema; a
    persistência nunca arredonda (ADR-012).
    """
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def percentage_of(amount: Decimal, percentage: Decimal) -> Decimal:
    """Calcula `percentage`% de `amount`, já arredondado como dinheiro."""
    return to_money(amount * percentage / _HUNDRED)


def parse_fare_profile(raw: str) -> FareProfile:
    """Converte o valor bruto do contrato em `FareProfile` (SPEC-001 §3)."""
    try:
        return FareProfile(raw)
    except ValueError as exc:
        raise InvalidFareProfileError(f"Perfil tarifário inválido: {raw!r}.") from exc


def parse_transport_mode(raw: str) -> TransportMode:
    """Converte o valor bruto do contrato em `TransportMode` (SPEC-001 §4)."""
    try:
        return TransportMode(raw)
    except ValueError as exc:
        raise InvalidTransportModeError(f"Modal de transporte inválido: {raw!r}.") from exc


@dataclass(frozen=True, slots=True)
class FareLookupKey:
    """Chave de consulta de tarifa: modal + linha (SPEC-001 §2, §4).

    METRO não possui linha (`line_code is None`); BUS sempre possui.
    """

    mode: TransportMode
    line_code: str | None


@dataclass(frozen=True, slots=True)
class Segment:
    """Segmento validado do trajeto (SPEC-001 §4).

    Regras estruturais, decididas na aprovação do plano da SPEC-001:

    - BUS sem `line_code` (ou em branco) → `BUS_LINE_REQUIRED`;
    - METRO com `line_code` → `INVALID_SEGMENT_STRUCTURE` — metrô não possui
      código de linha no contrato (§4).

    O `line_code` nunca é normalizado silenciosamente: valor em branco é
    rejeitado, não aparado.
    """

    mode: TransportMode
    line_code: str | None = None

    def __post_init__(self) -> None:
        if self.mode is TransportMode.BUS and (
            self.line_code is None or not self.line_code.strip()
        ):
            raise BusLineRequiredError
        if self.mode is TransportMode.METRO and self.line_code is not None:
            raise InvalidSegmentStructureError("Segmento METRO não aceita line_code (SPEC-001 §4).")

    @property
    def lookup_key(self) -> FareLookupKey:
        return FareLookupKey(self.mode, self.line_code)


@dataclass(frozen=True, slots=True)
class CalculatedSegment:
    """Segmento com a tarifa oficial aplicada, auditável por `fare_id`."""

    mode: TransportMode
    line_code: str | None
    fare_amount: Decimal
    fare_id: UUID


@dataclass(frozen=True, slots=True)
class AppliedDiscount:
    """Desconto aplicado, auditável por `rule_id` (SPEC-001 §10)."""

    type: TripType
    percentage: Decimal
    amount: Decimal
    rule_id: UUID


@dataclass(frozen=True, slots=True)
class FareCalculation:
    """Breakdown completo e determinístico do cálculo (SPEC-001 §10, §13).

    O resultado carrega tudo o que é necessário para reconstruir COMO o valor
    foi calculado: tarifas por segmento com seus IDs, regra aplicada com seu
    ID e o exato instante de referência usado nas consultas de vigência.

    O `__post_init__` valida as invariantes de SPEC-001 §13 e a coerência
    estrutural; violação levanta `ValueError` — resultado inconsistente é bug,
    nunca ganha fallback.
    """

    fare_profile: FareProfile
    trip_type: TripType
    segments: tuple[CalculatedSegment, ...]
    subtotal: Decimal
    discount: AppliedDiscount | None
    total: Decimal
    reference_datetime: datetime
    currency: str = field(default=CURRENCY)

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("FareCalculation exige ao menos um segmento.")

        monetary = [self.subtotal, self.total, *(s.fare_amount for s in self.segments)]
        if self.discount is not None:
            monetary.extend((self.discount.amount, self.discount.percentage))
        for value in monetary:
            # `type is Decimal` (e não isinstance) porque bool/int/float não
            # podem se disfarçar em caminho monetário.
            if type(value) is not Decimal:
                raise ValueError(f"Valor monetário deve ser Decimal, recebido {type(value)!r}.")

        expected_subtotal = sum((s.fare_amount for s in self.segments), start=Decimal("0"))
        if self.subtotal != expected_subtotal:
            raise ValueError("subtotal difere da soma das tarifas dos segmentos.")

        if self.trip_type is TripType.INTEGRATION:
            if self.discount is None:
                raise ValueError("INTEGRATION exige desconto aplicado (SPEC-001 §13).")
        elif self.discount is not None:
            raise ValueError("SINGLE/COMMON não possuem desconto (SPEC-001 §5, §13).")

        if self.discount is None:
            if self.total != self.subtotal:
                raise ValueError("Sem desconto, total deve ser igual ao subtotal.")
        else:
            if self.discount.amount < Decimal("0"):
                raise ValueError("discount_amount não pode ser negativo.")
            if self.discount.amount > self.subtotal:
                raise ValueError("discount_amount não pode exceder o subtotal (SPEC-001 §13).")
            if self.total != self.subtotal - self.discount.amount:
                raise ValueError("total deve ser subtotal - discount_amount.")

        if self.total < Decimal("0"):
            raise ValueError("total não pode ser negativo (SPEC-001 §13).")

        if self.reference_datetime.tzinfo is None:
            raise ValueError("reference_datetime deve ser timezone-aware.")
