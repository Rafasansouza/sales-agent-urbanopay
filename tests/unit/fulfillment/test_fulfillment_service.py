"""Serviço de fulfillment (SPEC-005 §6, §8.1, §11, §12.1, §13, §14).

Os cenários daqui são os que separam "não credita duas vezes" de
"provavelmente não credita duas vezes": replay, conflito de efeito, cartão
inativo, pagamento ausente e rollback.
"""

from __future__ import annotations

import inspect
import uuid
from decimal import Decimal

import pytest

from tests.unit.fulfillment.builders import (
    FIXED_NOW,
    LATER,
    make_card,
    make_fulfillment,
    make_ledger_entry,
    make_order,
    make_payment,
    make_receipt,
)
from tests.unit.fulfillment.fakes import FakeFulfillmentUnitOfWork, Store
from urbanopay.modules.cards.domain.enums import CardStatus
from urbanopay.modules.fulfillment.application.services import FulfillmentService
from urbanopay.modules.fulfillment.domain.enums import (
    DocumentKind,
    FailureClass,
    FulfillmentStatus,
    LedgerEntryType,
)
from urbanopay.modules.fulfillment.domain.errors import (
    EffectConflictError,
    FulfillmentNotFoundError,
    OrderNotPaidError,
    ReceiptNotAvailableError,
    ReconciliationRequiredError,
)
from urbanopay.modules.orders.domain.enums import OrderStatus
from urbanopay.modules.orders.domain.errors import (
    OrderNotAccessibleError,
    OrderNotFoundError,
)
from urbanopay.modules.payments.domain.enums import PaymentStatus

CUSTOMER = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
OTHER_CUSTOMER = uuid.UUID("00000000-0000-4000-8000-0000000000c2")


def make_service(store: Store) -> FulfillmentService:
    return FulfillmentService(FakeFulfillmentUnitOfWork(store))


def seed(
    store: Store,
    *,
    order_status: OrderStatus = OrderStatus.PAID,
    card_status: CardStatus = CardStatus.ACTIVE,
    balance: Decimal = Decimal("0.00"),
    total: Decimal = Decimal("50.00"),
    payment_status: PaymentStatus | None = PaymentStatus.APPROVED,
    customer_id: uuid.UUID = CUSTOMER,
) -> uuid.UUID:
    """Cenário completo: cartão, Order pago e Payment aprovado."""
    card = make_card(customer_id=customer_id, balance=balance, status=card_status)
    order = make_order(customer_id=customer_id, card_id=card.id, status=order_status, total=total)
    store.state.cards[card.id] = card
    store.state.orders[order.id] = order
    if payment_status is not None:
        payment = make_payment(order_id=order.id, status=payment_status, amount=total)
        store.state.payments[payment.id] = payment
    return order.id


# --- assinatura: autoridade de entrada (§6.1) ----------------------------


@pytest.mark.unit
def test_fulfill_order_recebe_somente_order_id() -> None:
    """Nenhum parâmetro externo de cartão, valor ou pagamento.

    Um `amount` ou `card_id` nesta assinatura permitiria à superfície de
    chamada escolher quanto se credita e para quem.
    """
    parametros = set(inspect.signature(FulfillmentService.fulfill_order).parameters)

    assert parametros == {"self", "order_id", "at"}
    for proibido in ("amount", "card_id", "payment_id", "fare_profile", "balance"):
        assert proibido not in parametros


@pytest.mark.unit
def test_nenhuma_operacao_aceita_texto_do_usuario() -> None:
    """ "eu já paguei" não tem canal para autorizar fulfillment (§2)."""
    proibidos = {"message", "text", "user_message", "user_text", "claim", "statement"}

    for nome, membro in inspect.getmembers(FulfillmentService, inspect.isfunction):
        if nome.startswith("_"):
            continue
        parametros = set(inspect.signature(membro).parameters)
        assert not (parametros & proibidos), f"{nome} aceita texto do usuário"


# --- sucesso -------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_pago_credita_uma_vez_e_conclui() -> None:
    store = Store()
    order_id = seed(store, balance=Decimal("21.50"), total=Decimal("50.00"))

    resultado = await make_service(store).fulfill_order(order_id=order_id, at=LATER)

    assert resultado.replayed is False
    assert resultado.fulfillment.status is FulfillmentStatus.COMPLETED
    assert resultado.fulfillment.completed_at == LATER
    assert resultado.ledger_entry.entry_type is LedgerEntryType.RECHARGE_CREDIT
    assert len(store.state.ledger) == 1
    assert len(store.state.receipts) == 1
    assert store.state.orders[order_id].status is OrderStatus.COMPLETED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_valor_creditado_e_exatamente_o_total_do_order() -> None:
    """A tarifa não é recalculada e nenhum valor externo é aceito (§17)."""
    store = Store()
    order_id = seed(store, balance=Decimal("21.50"), total=Decimal("137.45"))

    resultado = await make_service(store).fulfill_order(order_id=order_id, at=LATER)
    order = store.state.orders[order_id]

    assert resultado.ledger_entry.amount == Decimal("137.45")
    assert resultado.ledger_entry.amount == order.total
    assert resultado.ledger_entry.balance_before == Decimal("21.50")
    assert resultado.ledger_entry.balance_after == Decimal("158.95")
    # Aritmética exata, sem arredondamento.
    assert (
        resultado.ledger_entry.balance_after
        == resultado.ledger_entry.balance_before + resultado.ledger_entry.amount
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saldo_do_cartao_aumenta_exatamente_uma_vez() -> None:
    store = Store()
    order_id = seed(store, balance=Decimal("10.00"), total=Decimal("40.00"))
    card_id = store.state.orders[order_id].card_id

    await make_service(store).fulfill_order(order_id=order_id, at=LATER)

    assert store.state.cards[card_id].balance == Decimal("50.00")
    assert isinstance(store.state.cards[card_id].balance, Decimal)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cartao_e_derivado_do_order() -> None:
    """O destino do crédito vem de `order.card_id`, nunca de parâmetro (§6.1)."""
    store = Store()
    order_id = seed(store)
    card_do_order = store.state.orders[order_id].card_id

    # Um segundo cartão do mesmo cliente existe, e não pode ser tocado.
    outro = make_card(customer_id=CUSTOMER, balance=Decimal("99.00"))
    store.state.cards[outro.id] = outro

    resultado = await make_service(store).fulfill_order(order_id=order_id, at=LATER)

    assert resultado.ledger_entry.card_id == card_do_order
    assert resultado.fulfillment.card_id == card_do_order
    assert store.state.cards[outro.id].balance == Decimal("99.00")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_payment_aprovado_e_auditado() -> None:
    store = Store()
    order_id = seed(store)
    payment_id = next(iter(store.state.payments))

    resultado = await make_service(store).fulfill_order(order_id=order_id, at=LATER)

    assert resultado.fulfillment.payment_id == payment_id
    assert resultado.receipt.payment_id == payment_id


# --- comprovante (§13) ---------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_comprovante_e_simulado_e_nao_carrega_pii() -> None:
    store = Store()
    order_id = seed(store, total=Decimal("60.00"))

    receipt = (await make_service(store).fulfill_order(order_id=order_id, at=LATER)).receipt

    assert receipt.document_kind is DocumentKind.SIMULATED_NON_FISCAL
    assert receipt.disclaimer_version
    assert receipt.card_last4 == "4821"
    assert receipt.masked_card == "****4821"
    assert receipt.amount == Decimal("60.00")
    # Nenhum campo de PII existe na entidade.
    for proibido in ("cpf", "name", "nome", "email", "phone", "card_number", "otp"):
        assert not hasattr(receipt, proibido)


# --- replay e conflito (§8.1) --------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_devolve_resultado_anterior_sem_creditar() -> None:
    store = Store()
    order_id = seed(store, balance=Decimal("0.00"), total=Decimal("50.00"))
    service = make_service(store)

    primeiro = await service.fulfill_order(order_id=order_id, at=LATER)
    segundo = await service.fulfill_order(order_id=order_id, at=LATER)
    card_id = store.state.orders[order_id].card_id

    assert segundo.replayed is True
    assert segundo.ledger_entry.id == primeiro.ledger_entry.id
    assert segundo.receipt.id == primeiro.receipt.id
    assert len(store.state.ledger) == 1
    assert len(store.state.receipts) == 1
    # Saldo creditado UMA vez.
    assert store.state.cards[card_id].balance == Decimal("50.00")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fulfillment_completed_sem_ledger_e_conflito() -> None:
    """Inconsistência grave: reporta e não credita, nem regride (§12.1)."""
    store = Store()
    order_id = seed(store, order_status=OrderStatus.COMPLETED)
    order = store.state.orders[order_id]
    fulfillment = make_fulfillment(
        order_id=order_id, card_id=order.card_id, status=FulfillmentStatus.COMPLETED
    )
    store.state.fulfillments[fulfillment.id] = fulfillment

    with pytest.raises(EffectConflictError) as exc:
        await make_service(store).fulfill_order(order_id=order_id, at=LATER)

    assert exc.value.code == "EFFECT_CONFLICT"
    assert not store.state.ledger
    assert store.state.fulfillments[fulfillment.id].status is FulfillmentStatus.COMPLETED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ledger_sem_comprovante_e_conflito() -> None:
    """Evidência incompleta não permite fechar o estado — e não credita."""
    store = Store()
    order_id = seed(store)
    order = store.state.orders[order_id]
    fulfillment = make_fulfillment(
        order_id=order_id, card_id=order.card_id, status=FulfillmentStatus.PROCESSING
    )
    store.state.fulfillments[fulfillment.id] = fulfillment
    entry = make_ledger_entry(
        order_id=order_id, card_id=order.card_id, fulfillment_id=fulfillment.id
    )
    store.state.ledger[entry.id] = entry

    with pytest.raises(EffectConflictError):
        await make_service(store).fulfill_order(order_id=order_id, at=LATER)

    assert len(store.state.ledger) == 1


# --- Order não pago ------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.DRAFT,
        OrderStatus.REQUIRES_APPROVAL,
        OrderStatus.CONFIRMED,
        OrderStatus.PAYMENT_PENDING,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    ],
)
async def test_order_nao_pago_produz_zero_efeito(status: OrderStatus) -> None:
    store = Store()
    order_id = seed(store, order_status=status)

    with pytest.raises(OrderNotPaidError) as exc:
        await make_service(store).fulfill_order(order_id=order_id, at=LATER)

    assert exc.value.code == "ORDER_NOT_PAID"
    assert not store.state.ledger
    assert not store.state.receipts
    assert not store.state.fulfillments
    assert store.state.orders[order_id].status is status


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_inexistente_e_recusado() -> None:
    store = Store()
    with pytest.raises(OrderNotFoundError):
        await make_service(store).fulfill_order(order_id=uuid.uuid4(), at=LATER)


# --- Order PAID sem Payment APPROVED (§11.1) -----------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_pago_sem_payment_aprovado_vai_para_reconciliacao() -> None:
    """Inconsistência de dados, nunca "corrigida" com crédito."""
    store = Store()
    order_id = seed(store, payment_status=None)

    with pytest.raises(ReconciliationRequiredError) as exc:
        await make_service(store).fulfill_order(order_id=order_id, at=LATER)

    assert exc.value.code == "RECONCILIATION_REQUIRED"
    assert not store.state.ledger
    assert not store.state.receipts

    fulfillment = next(iter(store.state.fulfillments.values()))
    assert fulfillment.status is FulfillmentStatus.RECONCILIATION_REQUIRED
    assert fulfillment.failure_class is FailureClass.UNKNOWN_OUTCOME
    assert fulfillment.payment_id is None
    assert store.state.orders[order_id].status is OrderStatus.FULFILLMENT_FAILED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_payment_pendente_nao_autoriza_fulfillment() -> None:
    store = Store()
    order_id = seed(store, payment_status=PaymentStatus.PENDING)

    with pytest.raises(ReconciliationRequiredError):
        await make_service(store).fulfill_order(order_id=order_id, at=LATER)

    assert not store.state.ledger


# --- cartão não ACTIVE (§11.2) -------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("status", [CardStatus.BLOCKED, CardStatus.EXPIRED, CardStatus.CANCELLED])
async def test_cartao_nao_ativo_vai_para_reconciliacao(status: CardStatus) -> None:
    """Zero crédito, zero ledger, zero comprovante — e nada de estorno."""
    store = Store()
    order_id = seed(store, card_status=status, balance=Decimal("10.00"))
    card_id = store.state.orders[order_id].card_id

    with pytest.raises(ReconciliationRequiredError):
        await make_service(store).fulfill_order(order_id=order_id, at=LATER)

    assert not store.state.ledger
    assert not store.state.receipts
    assert store.state.cards[card_id].balance == Decimal("10.00")

    fulfillment = next(iter(store.state.fulfillments.values()))
    assert fulfillment.status is FulfillmentStatus.RECONCILIATION_REQUIRED
    assert fulfillment.failure_reason == "CARD_NOT_ACTIVE"
    assert store.state.orders[order_id].status is OrderStatus.FULFILLMENT_FAILED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_estado_de_reconciliacao_e_persistido() -> None:
    """O valor do caminho é deixar o caso conhecido e auditável."""
    store = Store()
    order_id = seed(store, card_status=CardStatus.BLOCKED)
    uow = FakeFulfillmentUnitOfWork(store)

    with pytest.raises(ReconciliationRequiredError):
        await FulfillmentService(uow).fulfill_order(order_id=order_id, at=LATER)

    # Comitado: se a exceção subisse antes do commit, a marcação se perderia e
    # o problema voltaria a ser invisível.
    assert uow.commits == 1
    assert store.state.fulfillments


# --- reentrada por comando explícito (§5.1) ------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reentrada_apos_reconciliacao_credita_quando_o_dado_e_corrigido() -> None:
    """Cartão reativado permite concluir a entrega, sem nova cobrança."""
    import dataclasses

    store = Store()
    order_id = seed(store, card_status=CardStatus.BLOCKED, total=Decimal("30.00"))
    service = make_service(store)

    with pytest.raises(ReconciliationRequiredError):
        await service.fulfill_order(order_id=order_id, at=LATER)

    # Correção administrativa do dado: o cartão volta a ACTIVE.
    card_id = store.state.orders[order_id].card_id
    store.state.cards[card_id] = dataclasses.replace(
        store.state.cards[card_id], status=CardStatus.ACTIVE
    )

    resultado = await service.fulfill_order(order_id=order_id, at=LATER)

    assert resultado.fulfillment.status is FulfillmentStatus.COMPLETED
    assert resultado.fulfillment.failure_reason is None
    assert resultado.fulfillment.failure_class is None
    assert len(store.state.ledger) == 1
    assert store.state.cards[card_id].balance == Decimal("30.00")
    assert store.state.orders[order_id].status is OrderStatus.COMPLETED


# --- rollback ------------------------------------------------------------


class _ReceiptRepositoryQueFalha:
    """Falha na emissão do comprovante — o último passo da transação.

    É o pior momento possível: crédito e ledger já estão no staging, então
    este dublê prova que eles caem junto.
    """

    async def add(self, receipt: object) -> None:
        raise RuntimeError("falha simulada na emissão do comprovante")

    async def get_for_order(self, order_id: uuid.UUID) -> None:
        return None


class _UnitOfWorkComFalhaNoComprovante(FakeFulfillmentUnitOfWork):
    """Substitui o repository de comprovante ao montar o contexto.

    Sobrescrever `_build` é a forma correta de injetar a falha: `async with`
    resolve `__aenter__` no **tipo**, não na instância, então um monkeypatch
    de atributo de instância seria silenciosamente ignorado.
    """

    def _build(self) -> None:
        super()._build()
        # Satisfaz o port estruturalmente, então não precisa de silenciamento.
        self.receipts = _ReceiptRepositoryQueFalha()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_falha_no_meio_nao_deixa_efeito_parcial() -> None:
    """Ledger, saldo, fulfillment, Order e comprovante caem juntos (§6.2).

    A falha é injetada no último passo — a emissão do comprovante — que é
    exatamente o pior momento: crédito e ledger já estão no staging.
    """
    store = Store()
    order_id = seed(store, balance=Decimal("15.00"), total=Decimal("25.00"))
    card_id = store.state.orders[order_id].card_id
    uow = _UnitOfWorkComFalhaNoComprovante(store)

    with pytest.raises(RuntimeError, match="falha simulada"):
        await FulfillmentService(uow).fulfill_order(order_id=order_id, at=LATER)

    # Nada sobreviveu: nem ledger, nem saldo, nem estado.
    assert uow.commits == 0
    assert not store.state.ledger
    assert not store.state.receipts
    assert not store.state.fulfillments
    assert store.state.cards[card_id].balance == Decimal("15.00")
    assert store.state.orders[order_id].status is OrderStatus.PAID


# --- pós-venda (§14) -----------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_consulta_de_status_filtra_por_titularidade() -> None:
    store = Store()
    order_id = seed(store)
    service = make_service(store)
    await service.fulfill_order(order_id=order_id, at=LATER)

    status = await service.get_fulfillment_status(customer_id=CUSTOMER, order_id=order_id)
    assert status.status is FulfillmentStatus.COMPLETED

    with pytest.raises(OrderNotAccessibleError):
        await service.get_fulfillment_status(customer_id=OTHER_CUSTOMER, order_id=order_id)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_status_de_order_sem_fulfillment() -> None:
    store = Store()
    order_id = seed(store)

    with pytest.raises(FulfillmentNotFoundError) as exc:
        await make_service(store).get_fulfillment_status(customer_id=CUSTOMER, order_id=order_id)
    assert exc.value.code == "FULFILLMENT_NOT_FOUND"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_comprovante_indisponivel_antes_da_conclusao() -> None:
    store = Store()
    order_id = seed(store)

    with pytest.raises(ReceiptNotAvailableError) as exc:
        await make_service(store).get_receipt(customer_id=CUSTOMER, order_id=order_id)
    assert exc.value.code == "RECEIPT_NOT_AVAILABLE"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_comprovante_disponivel_apos_conclusao() -> None:
    store = Store()
    order_id = seed(store, total=Decimal("80.00"))
    service = make_service(store)
    await service.fulfill_order(order_id=order_id, at=LATER)

    receipt = await service.get_receipt(customer_id=CUSTOMER, order_id=order_id)

    assert receipt.amount == Decimal("80.00")
    assert receipt.issued_at == LATER

    with pytest.raises(OrderNotAccessibleError):
        await service.get_receipt(customer_id=OTHER_CUSTOMER, order_id=order_id)


@pytest.mark.unit
def test_builders_produzem_receipt_coerente() -> None:
    """Sanidade do próprio builder, usado pelos testes de integração."""
    receipt = make_receipt(
        order_id=uuid.uuid4(), payment_id=uuid.uuid4(), fulfillment_id=uuid.uuid4()
    )
    assert receipt.issued_at == FIXED_NOW
    assert receipt.document_kind is DocumentKind.SIMULATED_NON_FISCAL
