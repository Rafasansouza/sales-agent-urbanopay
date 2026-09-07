"""Serviços de aplicação de fulfillment (SPEC-005 §6, §11, §12, §13, §14).

Três contratos governam tudo aqui:

1. **Fulfillment é consequência de estado financeiro confirmado.** A entrada é
   `order_id`; nada mais. `card_id`, `amount` e `payment_id` são **derivados
   do estado persistido**. Texto do usuário — "eu já paguei" — não tem canal
   algum para chegar até aqui.
2. **O efeito é atômico.** Ledger, saldo, fulfillment, Order e comprovante
   comitam juntos ou não comitam. Nenhum estado financeiro parcial sobrevive.
3. **Evidência inconsistente nunca é resolvida aplicando crédito.** Quando os
   dados não sustentam o efeito com segurança, o estado vira
   `RECONCILIATION_REQUIRED` — conhecido, auditável e com zero efeito.

Ordem de lock: `Order → Card → Fulfillment`, subconjunto da ordem global
`Order → Approval → Payment → Card → Fulfillment` (ADR-012). O Payment é
**leitura**: `APPROVED` é terminal e imutável, então não há o que travar.

O `Card` vem **antes** do `Fulfillment`, e isso é obrigatório, não estético.
`fulfillments.card_id` e `card_ledger_entries.card_id` são chaves estrangeiras
para `cards`, e o PostgreSQL adquire `FOR KEY SHARE` na linha do cartão ao
inserir. Travar o cartão depois deixaria duas transações concorrentes sobre o
mesmo cartão com lock compartilhado, ambas tentando elevá-lo a exclusivo —
deadlock. Foi observado em teste de integração antes desta ordenação.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from urbanopay.modules.cards.domain.enums import CardStatus
from urbanopay.modules.fulfillment.domain.entities import (
    CardLedgerEntry,
    CreditApplication,
    Fulfillment,
    Receipt,
)
from urbanopay.modules.fulfillment.domain.enums import (
    DISCLAIMER_VERSION,
    DocumentKind,
    FulfillmentStatus,
    FulfillmentType,
    LedgerEntryType,
)
from urbanopay.modules.fulfillment.domain.errors import (
    EffectConflictError,
    FulfillmentNotFoundError,
    OrderNotPaidError,
    ReceiptNotAvailableError,
    ReconciliationRequiredError,
)
from urbanopay.modules.fulfillment.domain.results import (
    ConsistencyReport,
    FulfillmentResult,
)
from urbanopay.modules.fulfillment.domain.state_machine import (
    complete,
    require_reconciliation,
    start_processing,
)
from urbanopay.modules.orders.domain.enums import OrderStatus
from urbanopay.modules.orders.domain.errors import (
    OrderNotAccessibleError,
    OrderNotFoundError,
)
from urbanopay.modules.orders.domain.state_machine import (
    complete_fulfillment,
    fail_fulfillment,
    start_fulfillment,
)

if TYPE_CHECKING:
    from urbanopay.modules.fulfillment.domain.ports import (
        FulfillmentRecoveryPort,
        FulfillmentUnitOfWork,
    )
    from urbanopay.modules.orders.domain.entities import Order

# Estados do Order a partir dos quais o efeito pode ser aplicado. Inclui
# `FULFILLING` (reentrada na mesma jornada) e `FULFILLMENT_FAILED` (reentrada
# por comando explícito, SPEC-005 §5.1).
_FULFILLABLE_ORDER_STATUSES = frozenset(
    {OrderStatus.PAID, OrderStatus.FULFILLING, OrderStatus.FULFILLMENT_FAILED}
)

_REASON_NO_APPROVED_PAYMENT = "ORDER_PAID_WITHOUT_APPROVED_PAYMENT"
_REASON_CARD_NOT_ACTIVE = "CARD_NOT_ACTIVE"

_DEFAULT_RECOVERY_LIMIT = 100


def _now(at: datetime | None) -> datetime:
    reference = at if at is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        raise ValueError("O instante de referência deve ser timezone-aware.")
    return reference


class FulfillmentService:
    """Aplicação do efeito comercial e consultas de pós-venda."""

    def __init__(self, uow: FulfillmentUnitOfWork) -> None:
        self._uow = uow

    async def fulfill_order(
        self, *, order_id: uuid.UUID, at: datetime | None = None
    ) -> FulfillmentResult:
        """Aplica o efeito de recarga de um Order pago (§6.2).

        Assinatura deliberadamente mínima: **somente** `order_id`. Um
        parâmetro de valor, de cartão ou de pagamento aqui permitiria à
        superfície de chamada escolher quanto se credita, para quem, e sob
        qual prova de pagamento.
        """
        now = _now(at)
        async with self._uow:
            # 1. Lock do Order: primeiro elo, e o que serializa execuções
            #    concorrentes do mesmo fulfillment.
            order = await self._uow.orders.get_for_update(order_id)
            if order is None:
                raise OrderNotFoundError

            fulfillment = await self._uow.fulfillments.get_for_order_for_update(order_id)
            existing_entry = await self._uow.ledger.get_recharge_credit_for_order(order_id)

            # 2. Efeito já aplicado ⇒ replay seguro, sem novo crédito (§8.1).
            if existing_entry is not None:
                return await self._replay(order_id, fulfillment)

            # 3. Fulfillment COMPLETED sem ledger: inconsistência grave.
            #    Reporta e não credita — e não regride estado terminal (§12.1).
            if fulfillment is not None and fulfillment.is_completed:
                raise EffectConflictError

            if order.status not in _FULFILLABLE_ORDER_STATUSES:
                raise OrderNotPaidError

            order.operation_type.require_supported()
            FulfillmentType.RECHARGE.require_supported()

            # 4. Payment APPROVED: valida a invariante da SPEC-003 e fornece o
            #    `payment_id` de auditoria. Leitura, sem lock — `APPROVED` é
            #    terminal e imutável.
            payment = await self._uow.payments.get_approved_for_order(order.id)

            # 5. Lock EXCLUSIVO do Card, obrigatoriamente ANTES de qualquer
            #    INSERT que referencie o cartão.
            #
            #    Não é preferência de estilo: `fulfillments.card_id` e
            #    `card_ledger_entries.card_id` são chaves estrangeiras, e o
            #    PostgreSQL adquire `FOR KEY SHARE` na linha de `cards` ao
            #    inserir. Se dois fulfillments de Orders distintos para o
            #    MESMO cartão inserissem antes de travar, ambos ficariam com
            #    lock compartilhado e ambos tentariam elevá-lo a exclusivo —
            #    deadlock, confirmado por teste de integração.
            card = await self._uow.cards.get_for_update(order.card_id)

            if fulfillment is None:
                fulfillment = Fulfillment(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    payment_id=None,
                    # Cartão DERIVADO do Order, nunca recebido.
                    card_id=order.card_id,
                    fulfillment_type=FulfillmentType.RECHARGE,
                    status=FulfillmentStatus.PENDING,
                    failure_reason=None,
                    failure_class=None,
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
                await self._uow.fulfillments.add(fulfillment)

            order = start_fulfillment(order, now)
            await self._uow.orders.update(order)

            fulfillment = start_processing(
                fulfillment, now, payment_id=payment.id if payment is not None else None
            )
            await self._uow.fulfillments.update(fulfillment)

            if payment is None:
                # `Order PAID` sem Payment aprovado é inconsistência de dados,
                # não caso de negócio. Nunca "corrigida" com crédito (§11.1).
                await self._require_reconciliation(
                    order, fulfillment, _REASON_NO_APPROVED_PAYMENT, now
                )
                raise ReconciliationRequiredError

            if card is None or card.status is not CardStatus.ACTIVE:
                # Zero crédito, zero ledger, zero comprovante. Sem retentativa
                # automática, sem troca de cartão, sem estorno (§11.2, A-18).
                await self._require_reconciliation(order, fulfillment, _REASON_CARD_NOT_ACTIVE, now)
                raise ReconciliationRequiredError

            # 6. Efeito. `amount` é exatamente `order.total`: a tarifa não é
            #    recalculada e nenhum valor externo é aceito.
            credit = CreditApplication.credit(balance_before=card.balance, amount=order.total)
            entry = CardLedgerEntry(
                id=uuid.uuid4(),
                fulfillment_id=fulfillment.id,
                order_id=order.id,
                card_id=card.id,
                entry_type=LedgerEntryType.RECHARGE_CREDIT,
                amount=credit.amount,
                currency=order.currency,
                balance_before=credit.balance_before,
                balance_after=credit.balance_after,
                created_at=now,
            )
            await self._uow.ledger.add(entry)
            await self._uow.cards.apply_credit(
                card_id=card.id, new_balance=credit.balance_after, at=now
            )

            fulfillment = complete(fulfillment, now)
            await self._uow.fulfillments.update(fulfillment)

            order = complete_fulfillment(order, now)
            await self._uow.orders.update(order)

            receipt = Receipt(
                id=uuid.uuid4(),
                order_id=order.id,
                payment_id=payment.id,
                fulfillment_id=fulfillment.id,
                card_last4=card.card_last4,
                amount=credit.amount,
                currency=order.currency,
                operation_type=order.operation_type.value,
                document_kind=DocumentKind.SIMULATED_NON_FISCAL,
                disclaimer_version=DISCLAIMER_VERSION,
                issued_at=now,
            )
            await self._uow.receipts.add(receipt)

            await self._uow.commit()

        return FulfillmentResult(fulfillment=fulfillment, ledger_entry=entry, receipt=receipt)

    async def _replay(
        self, order_id: uuid.UUID, fulfillment: Fulfillment | None
    ) -> FulfillmentResult:
        """Devolve o resultado persistido, sem aplicar nada (§8.1).

        Nenhum `commit`: a saída do contexto sem commit desfaz o trabalho
        pendente, e aqui não há trabalho a fazer — é exatamente o ponto.
        """
        entry = await self._uow.ledger.get_recharge_credit_for_order(order_id)
        receipt = await self._uow.receipts.get_for_order(order_id)
        if fulfillment is None or entry is None or receipt is None:
            # Ledger presente mas fulfillment ou comprovante ausentes: a
            # evidência não permite fechar o estado com segurança, e um
            # segundo crédito está fora de questão (§12.1).
            raise EffectConflictError
        return FulfillmentResult(
            fulfillment=fulfillment, ledger_entry=entry, receipt=receipt, replayed=True
        )

    async def _require_reconciliation(
        self, order: Order, fulfillment: Fulfillment, reason: str, now: datetime
    ) -> None:
        """Persiste o estado inconsistente e comita — sem efeito financeiro.

        O commit é essencial: o valor desta função é deixar o caso **conhecido
        e auditável**. Levantar a exceção antes de comitar desfaria a marcação
        e o problema voltaria a ser invisível.
        """
        reconciling = require_reconciliation(fulfillment, now, reason=reason)
        await self._uow.fulfillments.update(reconciling)
        await self._uow.orders.update(fail_fulfillment(order, now))
        await self._uow.commit()

    # --- pós-venda (§14) --------------------------------------------------

    async def get_fulfillment_status(
        self, *, customer_id: uuid.UUID, order_id: uuid.UUID
    ) -> Fulfillment:
        """Estado da entrega, sempre filtrado por titularidade."""
        async with self._uow:
            await self._require_owned_order(customer_id=customer_id, order_id=order_id)
            fulfillment = await self._uow.fulfillments.get_for_order(order_id)
        if fulfillment is None:
            raise FulfillmentNotFoundError
        return fulfillment

    async def get_receipt(self, *, customer_id: uuid.UUID, order_id: uuid.UUID) -> Receipt:
        """Comprovante, disponível somente após `COMPLETED` (§13)."""
        async with self._uow:
            await self._require_owned_order(customer_id=customer_id, order_id=order_id)
            receipt = await self._uow.receipts.get_for_order(order_id)
        if receipt is None:
            raise ReceiptNotAvailableError
        return receipt

    async def _require_owned_order(self, *, customer_id: uuid.UUID, order_id: uuid.UUID) -> Order:
        order = await self._uow.orders.get_owned(customer_id=customer_id, order_id=order_id)
        if order is None:
            raise OrderNotAccessibleError
        return order


class FulfillmentRecoveryService:
    """Consultas de recuperação e consistência (§12.1, §20.1).

    Separado do `FulfillmentService` de propósito: só lê, não participa da
    transação do efeito, e cruza agregados. Misturá-lo ao serviço transacional
    criaria um objeto com duas razões de existir.

    **Nada aqui aplica efeito financeiro.** Detecção nunca é reparo.
    """

    def __init__(self, recovery: FulfillmentRecoveryPort) -> None:
        self._recovery = recovery

    async def build_report(self, *, limit: int = _DEFAULT_RECOVERY_LIMIT) -> ConsistencyReport:
        """Relatório de achados. Vazio é a expectativa em operação normal."""
        recovery = self._recovery
        eligible = await recovery.find_paid_orders_without_completed_fulfillment(limit=limit)
        orphan_completed = await recovery.find_completed_fulfillments_without_ledger(limit=limit)
        orphan_ledger = await recovery.find_ledger_without_completed_fulfillment(limit=limit)
        return ConsistencyReport(
            eligible_orders=eligible,
            completed_without_ledger=orphan_completed,
            ledger_without_completed=orphan_ledger,
        )
