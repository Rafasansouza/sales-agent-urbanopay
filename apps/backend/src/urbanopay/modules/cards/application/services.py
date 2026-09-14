"""Serviço de aplicação de cartões (SPEC-002 §5–§8).

Somente leitura. Recebe `customer_id` já autenticado — a resolução de sessão é
responsabilidade do módulo `identity`, encadeada pela composição (matriz de
autorização de §9: nada aqui atende sessão anônima).

Ordem de verificação fixa: **titularidade antes de status** — cartão de
terceiro responde `CARD_NOT_ACCESSIBLE` sem revelar existência nem estado.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from urbanopay.modules.cards.domain.enums import CardStatus, FareProfileSource
from urbanopay.modules.cards.domain.errors import CardNotAccessibleError, CardNotActiveError
from urbanopay.modules.cards.domain.value_objects import (
    ProfileResolutionResult,
    detect_profile_divergence,
)

if TYPE_CHECKING:
    from decimal import Decimal
    from uuid import UUID

    from urbanopay.modules.cards.domain.entities import Card
    from urbanopay.modules.cards.domain.enums import FareProfile
    from urbanopay.modules.cards.domain.ports import CardRepository


class CardService:
    """Consultas de cartão e autoridade do perfil tarifário oficial."""

    def __init__(self, cards: CardRepository) -> None:
        self._cards = cards

    async def list_cards(self, customer_id: UUID) -> list[Card]:
        """Cartões do próprio cliente (§9: 'Listar cartões — Próprios')."""
        return await self._cards.list_for_customer(customer_id)

    async def get_card(self, customer_id: UUID, card_id: UUID) -> Card:
        """Detalhes de um cartão do próprio cliente (§5)."""
        card = await self._cards.get_owned(customer_id, card_id)
        if card is None:
            raise CardNotAccessibleError
        return card

    async def get_card_balance(self, customer_id: UUID, card_id: UUID) -> Decimal:
        """Saldo oficial (§7): sessão autenticada + titularidade + acesso.

        §7 não restringe a leitura de saldo a cartão ACTIVE — o titular pode
        consultar o saldo de um cartão bloqueado/expirado.
        """
        card = await self.get_card(customer_id, card_id)
        return card.balance

    async def resolve_official_fare_profile(
        self,
        customer_id: UUID,
        card_id: UUID,
        declared_profile: FareProfile | None = None,
    ) -> ProfileResolutionResult:
        """Autoridade do perfil tarifário (§1, §8).

        O perfil oficial é o do cartão — a declaração do usuário NUNCA o
        substitui (hierarquia de confiança, §16). Divergência gera o sinal
        `FARE_PROFILE_CHANGED` (A-11: resultado, não exceção); o recálculo é
        responsabilidade da orquestração (SPEC-003/004).

        Somente cartão ACTIVE é utilizável como autoridade (PRD RN-09);
        titularidade é verificada ANTES do status.
        """
        card = await self.get_card(customer_id, card_id)
        if card.status is not CardStatus.ACTIVE:
            raise CardNotActiveError

        return ProfileResolutionResult(
            card_id=card.id,
            official_profile=card.fare_profile,
            source=FareProfileSource.CARD,
            verified=True,
            declared_profile=declared_profile,
            signal=detect_profile_divergence(declared_profile, card.fare_profile),
        )
