"""Entidades do domínio de pagamentos (SPEC-003 §9, §12).

Domínio puro e imutável. Dinheiro é sempre `Decimal`; este módulo **não
arredonda** — `Payment.amount` é derivado de `Order.total`, já congelado.

Minimização de dados (decisão aprovada): o payload do provider é **redigido**
antes de qualquer persistência. Nunca são persistidos token, secret,
credencial ou PII desnecessária. O código copia-e-cola do Pix também não é
persistido: ele é devolvido de forma transitória pelo provider e pode ser
reconsultado, então guardá-lo não acrescenta capacidade alguma e amplia a
superfície de exposição.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from urbanopay.modules.payments.domain.enums import (
    PaymentMethod,
    PaymentStatus,
    ProviderName,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

# Chaves do payload de provider que podem ser persistidas. Allowlist, não
# denylist: campo desconhecido é descartado por padrão, porque a lista de
# coisas perigosas nunca está completa.
PERSISTABLE_EVENT_KEYS = frozenset(
    {
        "id",
        "type",
        "action",
        "status",
        "status_detail",
        "external_reference",
        "date_created",
        "date_approved",
        "date_last_updated",
        "live_mode",
    }
)

_MAX_REDACTED_VALUE_LENGTH = 256


def redact_event_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    """Reduz o payload do provider ao mínimo auditável.

    Mantém apenas as chaves da allowlist, converte tudo para texto e limita o
    tamanho. Estruturas aninhadas são descartadas: elas são justamente onde
    dados de pagador e metadados sensíveis costumam viajar.
    """
    redacted: dict[str, str] = {}
    for key in sorted(PERSISTABLE_EVENT_KEYS & payload.keys()):
        value = payload[key]
        if isinstance(value, dict | list | tuple | set):
            continue
        if value is None:
            continue
        redacted[key] = str(value)[:_MAX_REDACTED_VALUE_LENGTH]
    return redacted


@dataclass(frozen=True, slots=True)
class Payment:
    """Tentativa comercial de pagamento (SPEC-003 §9, §13).

    Cada `Payment` **é** uma tentativa comercial; não existe entidade separada
    de tentativa. Um Order possui `1..N` Payments, no máximo um `APPROVED` e
    no máximo um ativo (`CREATED` ou `PENDING`).

    `idempotency_key` é a key da tentativa: o retry técnico reusa a mesma
    (§13.1), e a nova tentativa comercial exige uma nova (§13.2).
    """

    id: UUID
    order_id: UUID
    provider: ProviderName
    provider_payment_id: str | None
    method: PaymentMethod
    amount: Decimal
    currency: str
    status: PaymentStatus
    idempotency_key: str
    created_at: datetime
    updated_at: datetime

    @property
    def is_terminal(self) -> bool:
        """Terminais não regridem e não são redecididos (§9)."""
        return self.status in TERMINAL_PAYMENT_STATUSES

    @property
    def is_active(self) -> bool:
        """Tentativa ativa: ocupa o slot único do Order (§9)."""
        return self.status in ACTIVE_PAYMENT_STATUSES

    def with_status(
        self, status: PaymentStatus, at: datetime, *, provider_payment_id: str | None = None
    ) -> Payment:
        """Devolve uma nova instância com o estado aplicado.

        Não valida a transição: a validação é responsabilidade de
        `state_machine.apply_provider_status`, que é o único ponto autorizado
        a decidir se um estado externo pode ser aplicado.
        """
        return replace(
            self,
            status=status,
            provider_payment_id=provider_payment_id or self.provider_payment_id,
            updated_at=at,
        )


# Definidos após a classe para manter a leitura de cima para baixo.
TERMINAL_PAYMENT_STATUSES = frozenset(
    {
        PaymentStatus.APPROVED,
        PaymentStatus.REJECTED,
        PaymentStatus.CANCELLED,
        PaymentStatus.EXPIRED,
        PaymentStatus.FAILED,
    }
)

ACTIVE_PAYMENT_STATUSES = frozenset({PaymentStatus.CREATED, PaymentStatus.PENDING})


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    """Evento de provider recebido por webhook ou por consulta (§12).

    Unicidade `(provider, provider_event_id)`: webhook duplicado é persistido
    uma única vez e produz efeito único.

    Eventos originados de **consulta ativa** (polling/reconciliação) não
    possuem `provider_event_id` do provider; nesse caso o identificador é
    derivado de forma determinística pelo chamador, para que a mesma leitura
    não seja contada duas vezes.
    """

    id: UUID
    payment_id: UUID
    provider: ProviderName
    provider_event_id: str
    reported_status: PaymentStatus
    payload: dict[str, str]
    received_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderCharge:
    """Resultado de uma criação ou consulta de cobrança no provider.

    Fala o enum **do domínio**: a tradução do vocabulário do provider acontece
    no adaptador (`infrastructure`), nunca aqui. Assim o domínio não conhece
    `"approved"`, `"cancelled"` nem qualquer string de terceiro.

    `qr_code` é transitório e nunca persistido (ver docstring do módulo).
    """

    provider_payment_id: str
    status: PaymentStatus
    qr_code: str | None = None
    raw_payload: dict[str, str] | None = None
