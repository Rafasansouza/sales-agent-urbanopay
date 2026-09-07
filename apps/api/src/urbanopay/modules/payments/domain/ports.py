"""Ports do domínio de pagamentos (ADR-007, ADR-012).

Ordem global de lock: `Order` → `Approval` → `Payment`. O Payment é o
**último** elo: toda transação que também trave o Order o faz antes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from urbanopay.core.persistence import UnitOfWork

if TYPE_CHECKING:
    from decimal import Decimal
    from uuid import UUID

    from urbanopay.core.idempotency import IdempotencyRepository
    from urbanopay.modules.orders.domain.ports import OrderRepository
    from urbanopay.modules.payments.domain.entities import (
        Payment,
        PaymentEvent,
        ProviderCharge,
    )
    from urbanopay.modules.payments.domain.enums import ProviderName


class PaymentRepository(Protocol):
    """Persistência de Payments. Nunca executa commit."""

    async def add(self, payment: Payment) -> None: ...

    async def get(self, payment_id: UUID) -> Payment | None: ...

    async def get_for_update(self, payment_id: UUID) -> Payment | None:
        """Payment com lock de linha (`SELECT ... FOR UPDATE`).

        Último elo da ordem global de lock. É sob este lock que webhook e
        consulta ativa convergem, o que serializa aplicações concorrentes do
        mesmo fato.
        """
        ...

    async def get_active_for_order(self, order_id: UUID) -> Payment | None:
        """Tentativa ativa (`CREATED` ou `PENDING`) do Order, se existir.

        Há no máximo uma, garantido por índice único parcial no banco.
        """
        ...

    async def get_approved_for_order(self, order_id: UUID) -> Payment | None:
        """Payment `APPROVED` do Order, se existir. No máximo um (§13)."""
        ...

    async def find_by_provider_payment_id(
        self, *, provider: ProviderName, provider_payment_id: str
    ) -> Payment | None:
        """Resolve o Payment a partir do identificador externo (§12, passo 2).

        É como o webhook identifica o recurso: ele não conhece o nosso UUID.
        O filtro inclui `provider` para que identificadores de providers
        distintos nunca colidam.
        """
        ...

    async def update(self, payment: Payment) -> None: ...


class PaymentEventRepository(Protocol):
    """Persistência dos eventos de provider (§12)."""

    async def record(self, event: PaymentEvent) -> bool:
        """Persiste o evento e informa se ele é **novo**.

        Implementado com `INSERT ... ON CONFLICT DO NOTHING` sobre
        `UNIQUE (provider, provider_event_id)`: devolve `False` quando o
        evento já havia sido registrado. É este retorno que garante efeito
        único para webhook duplicado — a deduplicação é uma constraint de
        banco, não uma verificação em memória.
        """
        ...


class PaymentProvider(Protocol):
    """Fronteira com o provider de pagamento (ADR-007).

    Somente ambiente de teste/sandbox no MVP. O access token vive
    exclusivamente no backend e **nunca** é exposto ao frontend nem ao LLM.

    Implementações levantam `PaymentProviderTimeoutError` para timeout ou
    resposta inconclusiva — estado desconhecido, nunca falha definitiva —,
    `PaymentCreationFailedError` para recusa determinística e
    `PaymentProviderError` para indisponibilidade. A tradução do vocabulário
    do provider para `PaymentStatus` acontece no adaptador.
    """

    @property
    def name(self) -> ProviderName: ...

    async def create_pix_charge(
        self,
        *,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
        external_reference: str,
    ) -> ProviderCharge:
        """Cria a cobrança Pix.

        `external_reference` recebe o identificador opaco do Order — nunca
        CPF, nome, e-mail ou número de cartão.

        `idempotency_key` é repassada ao provider para que uma retentativa
        técnica não gere segunda cobrança.
        """
        ...

    async def get_charge(
        self, *, provider_payment_id: str | None, idempotency_key: str
    ) -> ProviderCharge:
        """Consulta o estado oficial da cobrança, sem criar nada.

        É o único caminho de resolução do estado externo desconhecido (§9.1) e
        precede qualquer novo POST em retry técnico (§13.1).

        Aceita os dois identificadores porque, em timeout de criação, o
        `provider_payment_id` pode nunca ter chegado. **Se um provider real
        suporta consulta apenas por um deles é questão a verificar quando o
        adaptador correspondente for implementado** — nada aqui afirma
        capacidade de API de terceiro que não foi testada.
        """
        ...


@runtime_checkable
class PaymentsUnitOfWork(UnitOfWork, Protocol):
    """Fronteira transacional do módulo, com seus repositories.

    Inclui `orders` — o port público de `orders` — porque o desfecho de um
    Payment transiciona o Order na **mesma** transação: `APPROVED` ⇒ `PAID`,
    terminal não aprovado ⇒ volta a `CONFIRMED` (§13.2). Separar as duas
    escritas admitiria `Payment APPROVED` sem `Order PAID`.

    A dependência é unidirecional: `orders` nunca importa `payments`.
    """

    payments: PaymentRepository
    payment_events: PaymentEventRepository
    orders: OrderRepository
    idempotency: IdempotencyRepository
