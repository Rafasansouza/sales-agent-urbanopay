"""Entidade Card (SPEC-002 §2).

Decisão de minimização aprovada: **o número completo do cartão não existe no
sistema**. Nenhuma operação da SPEC o consome (as tools trabalham com
`card_id` + `masked_number`, §6), então persiste-se apenas `card_last4` — os
quatro dígitos finais para apresentação. A identidade oficial do cartão é o
UUID interno. Sem número completo, não há o que vazar.

Saldo é `Decimal` e, nesta SPEC, somente leitura (§7) — mutação e ledger
pertencem à SPEC-005.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from urbanopay.modules.cards.domain.enums import CardStatus, FareProfile

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class Card:
    """Cartão de transporte — autoridade determinística do perfil tarifário.

    **`status` é a ÚNICA autoridade operacional do cartão** (decisão
    documentada na aprovação da SPEC-002): todos os comportamentos da SPEC e
    do PRD (§14.7, RN-09) referenciam o status, e a SPEC não define nenhuma
    regra funcional para `expires_at`. O campo `expires_at` é **informativo**
    (data prevista de expiração impressa/registrada); a materialização de
    `status = EXPIRED` é operação administrativa futura, fora desta SPEC.
    Não existem duas fontes de autoridade: um cartão `ACTIVE` é utilizável,
    ponto — se essa regra mudar, muda por documento, não por código.
    """

    id: UUID
    customer_id: UUID
    card_last4: str
    fare_profile: FareProfile
    balance: Decimal
    status: CardStatus
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def masked_number(self) -> str:
        """Apresentação mascarada no formato da SPEC §6 (`****4821`)."""
        return f"****{self.card_last4}"
