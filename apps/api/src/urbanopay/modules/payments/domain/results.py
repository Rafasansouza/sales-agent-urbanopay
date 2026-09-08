"""Resultados de saída da aplicação de pagamentos (SPEC-003 §9, §12)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from urbanopay.modules.payments.domain.enums import PaymentStatus

if TYPE_CHECKING:
    from uuid import UUID

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
class OrderPaymentStatus:
    """Situação de pagamento de um Order, na chave que a conversa usa (§13).

    A pergunta do cliente é sempre sobre o **pedido**, nunca sobre um
    `payment_id` que ele não conhece — por isso a consulta é por `order_id`, e
    a titularidade é verificada contra o Order.

    `latest` é a tentativa mais recente, em qualquer estado, ou `None` quando
    nenhuma cobrança foi criada. Os invariantes de §13 garantem que ela
    descreve o estado corrente: nenhum Payment nasce enquanto existir
    tentativa ativa ou aprovada.
    """

    order_id: UUID
    latest: Payment | None

    @property
    def has_active_attempt(self) -> bool:
        """Existe tentativa ocupando o slot único do Order (`CREATED`/`PENDING`)."""
        return self.latest is not None and self.latest.is_active

    @property
    def is_approved(self) -> bool:
        return self.latest is not None and self.latest.status is PaymentStatus.APPROVED

    @property
    def outcome_is_unknown(self) -> bool:
        """`CREATED` ativo: existe tentativa cujo estado externo não foi confirmado.

        É o caso da §9.1 — e o único desfecho possível é reconciliar, nunca
        emitir nova cobrança.
        """
        return self.latest is not None and self.latest.status is PaymentStatus.CREATED

    @property
    def previous_terminal_payment_id(self) -> UUID | None:
        """Identidade da tentativa terminal **não aprovada** anterior, se houver.

        É a evidência persistida a partir da qual uma nova tentativa comercial
        deriva sua identidade de idempotência (§13.2). `APPROVED` fica de
        fora de propósito: depois dele não existe nova tentativa a autorizar.
        """
        latest = self.latest
        if latest is None or not latest.is_terminal:
            return None
        if latest.status is PaymentStatus.APPROVED:
            return None
        return latest.id


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
