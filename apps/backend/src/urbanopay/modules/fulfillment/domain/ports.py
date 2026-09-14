"""Ports do domínio de fulfillment (ADR-012, SPEC-005 §7, §12.1, §20.1).

Contratos comuns:

- implementações devolvem entidades de domínio, nunca modelos ORM;
- implementações **nunca** executam commit — a fronteira transacional é do
  Unit of Work, porque ledger, saldo, fulfillment, Order e comprovante precisam
  comitar juntos;
- nenhuma exceção carrega PII, saldo ou valor monetário;
- **ordem global de lock: `Order → Approval → Payment → Card → Fulfillment`.**

O `Card` precede o `Fulfillment` por necessidade técnica: as chaves
estrangeiras `fulfillments.card_id` e `card_ledger_entries.card_id` fazem o
PostgreSQL travar a linha do cartão em `FOR KEY SHARE` no momento do INSERT.
Adquirir o lock exclusivo depois disso produz deadlock entre dois fulfillments
do mesmo cartão.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from urbanopay.core.persistence import UnitOfWork

if TYPE_CHECKING:
    from uuid import UUID

    from urbanopay.modules.cards.domain.ports import CardBalanceRepository
    from urbanopay.modules.fulfillment.domain.entities import (
        CardLedgerEntry,
        Fulfillment,
        Receipt,
    )
    from urbanopay.modules.orders.domain.ports import OrderRepository
    from urbanopay.modules.payments.domain.ports import PaymentRepository


class FulfillmentRepository(Protocol):
    """Persistência do agregado `Fulfillment`."""

    async def add(self, fulfillment: Fulfillment) -> None: ...

    async def get_for_order(self, order_id: UUID) -> Fulfillment | None: ...

    async def get_for_order_for_update(self, order_id: UUID) -> Fulfillment | None:
        """Fulfillment do Order com lock de linha (`SELECT ... FOR UPDATE`).

        Último elo da ordem global: adquirido **depois** do lock do Order e
        **depois** do lock do Card.
        """
        ...

    async def update(self, fulfillment: Fulfillment) -> None: ...


class CardLedgerRepository(Protocol):
    """Persistência do ledger do cartão.

    Deliberadamente **sem `update` e sem `delete`**: o ledger é imutável
    (§7.1). A ausência dos métodos é a garantia estrutural — um repository que
    os expusesse permitiria reescrever histórico financeiro.
    """

    async def add(self, entry: CardLedgerEntry) -> None: ...

    async def get_recharge_credit_for_order(self, order_id: UUID) -> CardLedgerEntry | None:
        """Entrada `RECHARGE_CREDIT` do Order, se existir.

        É a verificação de idempotência do fluxo: a presença desta entrada
        significa que o efeito já aconteceu, e o comando deve devolver o
        resultado anterior em vez de creditar de novo (§8.1).
        """
        ...


class ReceiptRepository(Protocol):
    """Persistência do comprovante. Um por Order, imutável."""

    async def add(self, receipt: Receipt) -> None: ...

    async def get_for_order(self, order_id: UUID) -> Receipt | None: ...


class FulfillmentRecoveryPort(Protocol):
    """Consultas de recuperação e de consistência (§12.1, §20.1).

    Vive **fora** dos repositories de agregado por decisão: são consultas
    cross-aggregate — cruzam `orders`, `fulfillments` e `card_ledger_entries` —
    e colocá-las em um repository de agregado misturaria responsabilidades.

    Não existe scheduler nesta versão: estas consultas são a capacidade que a
    camada de composição usará quando existir job.

    Todas são **somente leitura**. Nenhuma aplica efeito financeiro: detecção
    nunca é reparo (§12.1).
    """

    async def find_paid_orders_without_completed_fulfillment(self, *, limit: int) -> list[UUID]:
        """Orders `PAID` sem fulfillment `COMPLETED` — elegíveis a nova chamada."""
        ...

    async def find_completed_fulfillments_without_ledger(self, *, limit: int) -> list[UUID]:
        """Fulfillments `COMPLETED` sem entrada de ledger.

        Inconsistência grave. O achado é **reportado**; nunca se credita para
        "consertar", e o estado terminal não regride (§5.1).
        """
        ...

    async def find_ledger_without_completed_fulfillment(self, *, limit: int) -> list[UUID]:
        """Ledger existente com fulfillment não `COMPLETED`.

        O efeito financeiro já aconteceu: o encerramento se dá pela evidência
        persistida, **nunca** por um segundo crédito.
        """
        ...


@runtime_checkable
class FulfillmentUnitOfWork(UnitOfWork, Protocol):
    """Fronteira transacional do módulo, com seus repositories.

    Compõe seis ports, e a atomicidade é o que os reúne: ledger, saldo,
    fulfillment, Order e comprovante comitam **juntos** ou não comitam (§6.2).
    Separá-los em unidades de trabalho distintas por estética criaria
    exatamente o estado financeiro parcial que a SPEC proíbe.

    - `orders` — port público de `orders`, para validar `PAID` e transicionar;
    - `payments` — **somente leitura**: `APPROVED` é terminal e imutável
      (SPEC-003 §9), então não há o que travar;
    - `cards` — port estreito de crédito, do módulo `cards`;
    - `fulfillments`, `ledger`, `receipts` — agregados deste módulo.

    Dependências unidirecionais: `orders`, `payments` e `cards` **nunca**
    importam `fulfillment` (ADR-001).
    """

    fulfillments: FulfillmentRepository
    ledger: CardLedgerRepository
    receipts: ReceiptRepository
    orders: OrderRepository
    payments: PaymentRepository
    cards: CardBalanceRepository
