"""Resultados de saída da aplicação de pagamentos (SPEC-003 §9, §12)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from urbanopay.modules.payments.domain.entities import Payment


@dataclass(frozen=True, slots=True)
class PaymentCreationResult:
    """Payment criado e o dado transitório de cobrança.

    `qr_code` **não é persistido** (ver `entities`): existe apenas nesta
    resposta, para que a jornada possa apresentá-lo. Se for necessário
    novamente, é reconsultado no provider.

    `already_existed` marca o caso em que uma tentativa ativa já existia e
    nenhuma cobrança nova foi criada — a garantia de não duplicar efeito
    financeiro fica explícita para quem chama, em vez de silenciosa.
    """

    payment: Payment
    qr_code: str | None
    already_existed: bool = False


@dataclass(frozen=True, slots=True)
class WebhookProcessingResult:
    """Desfecho do processamento de um webhook (§12).

    `duplicate=True` significa que o evento já havia sido registrado e
    **nenhum efeito foi reaplicado** — webhook duplicado nunca produz efeito
    duplicado.

    `requires_reconciliation=True` sinaliza divergência que não pode ser
    resolvida automaticamente: o provider afirmou `APPROVED` sobre um estado
    terminal não aprovado.
    """

    duplicate: bool
    applied: bool
    requires_reconciliation: bool
    payment: Payment | None = None
