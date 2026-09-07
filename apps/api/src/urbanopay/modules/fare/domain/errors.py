"""Erros tipados do Fare Engine — exatamente os de SPEC-001 §11.

Os erros do domínio são **puros**: derivam de `Exception` e carregam apenas o
código semântico estável e uma mensagem. Eles não herdam de
`urbanopay.core.errors.AppError` porque aquela classe carrega `http_status`,
que é detalhe de apresentação — o mapeamento para HTTP acontecerá na camada de
borda quando existir endpoint, nunca aqui.

Nenhum erro admite fallback: tarifa estimada não existe (SPEC-001 §11).
"""

from __future__ import annotations

from typing import ClassVar


class FareError(Exception):
    """Base dos erros do Fare Engine.

    `code` é o identificador estável de SPEC-001 §11, destinado a consumo
    programático; a mensagem é destinada a leitura humana e nunca contém dado
    sensível.
    """

    code: ClassVar[str]
    default_message: ClassVar[str]

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class InvalidFareProfileError(FareError):
    code = "INVALID_FARE_PROFILE"
    default_message = "Perfil tarifário inválido."


class InvalidTransportModeError(FareError):
    code = "INVALID_TRANSPORT_MODE"
    default_message = "Modal de transporte inválido."


class InvalidSegmentStructureError(FareError):
    code = "INVALID_SEGMENT_STRUCTURE"
    default_message = "Estrutura de segmento inválida."


class EmptyTripError(FareError):
    code = "EMPTY_TRIP"
    default_message = "O trajeto não possui segmentos."


class BusLineRequiredError(FareError):
    code = "BUS_LINE_REQUIRED"
    default_message = "Segmento de ônibus exige o código da linha."


class FareLineNotFoundError(FareError):
    """Linha de ônibus que nunca foi tarifada.

    Específico de BUS: METRO não possui linha e nunca produz este erro —
    ausência de tarifa vigente para METRO é `FARE_NOT_AVAILABLE`.
    """

    code = "FARE_LINE_NOT_FOUND"
    default_message = "Linha de ônibus desconhecida."


class FareNotAvailableError(FareError):
    """Modal/linha conhecidos, mas sem tarifa vigente para o perfil e a data."""

    code = "FARE_NOT_AVAILABLE"
    default_message = "Não há tarifa vigente para os parâmetros informados."


class FareRuleNotFoundError(FareError):
    code = "FARE_RULE_NOT_FOUND"
    default_message = "Não há regra tarifária vigente para a classificação."


class UnsupportedTripCompositionError(FareError):
    code = "UNSUPPORTED_TRIP_COMPOSITION"
    default_message = "Composição de trajeto não suportada."


class FareServiceUnavailableError(FareError):
    """Indisponibilidade de infraestrutura — nunca erro de programação.

    Levantado pela camada de infraestrutura exclusivamente ao traduzir falhas
    de conectividade/disponibilidade do banco. Bugs, queries inválidas e
    violações inesperadas NÃO são mascarados com este erro.
    """

    code = "FARE_SERVICE_UNAVAILABLE"
    default_message = "O serviço tarifário está temporariamente indisponível."
