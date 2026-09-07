"""Erros semânticos do domínio de cartões.

Puros: código estável + mensagem, sem HTTP e sem PII.
"""

from __future__ import annotations

from typing import ClassVar


class CardsError(Exception):
    """Base dos erros de cartões. Mensagens nunca contêm dados do cartão."""

    code: ClassVar[str]
    default_message: ClassVar[str]

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class CardNotAccessibleError(CardsError):
    """Cartão inexistente OU pertencente a outro cliente (SPEC-002 §5).

    Deliberadamente o MESMO erro e a MESMA mensagem para os dois casos: a
    resposta nunca revela se o cartão existe — anti-enumeração.
    """

    code = "CARD_NOT_ACCESSIBLE"
    default_message = "Cartão não acessível para este cliente."


class CardNotActiveError(CardsError):
    """Cartão do próprio cliente, mas fora do estado ACTIVE (PRD RN-09).

    Usado na resolução de perfil oficial: somente cartão ACTIVE é utilizável
    como autoridade tarifária (decisão aprovada no plano da SPEC-002).
    """

    code = "CARD_NOT_ACTIVE"
    default_message = "O cartão não está ativo."
