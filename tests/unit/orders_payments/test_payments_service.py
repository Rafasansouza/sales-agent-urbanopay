"""Serviço de aplicação de pagamentos (SPEC-003 §9, §9.1, §11, §12, §13).

Os cenários daqui são os que separam "não duplica cobrança" de "provavelmente
não duplica cobrança": timeout, replay de key em andamento, webhook duplicado,
evento fora de ordem e nova tentativa comercial.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.orders_payments.builders import FIXED_NOW, TTL, make_quote
from urbanopay.core.idempotency import IdempotencyStatus
from urbanopay.modules.orders.application.services import OrderService
from urbanopay.modules.orders.domain.enums import OrderStatus
from urbanopay.modules.orders.domain.errors import (
    OrderNotAccessibleError,
    OrderRequiresApprovalError,
)
from urbanopay.modules.orders.domain.policies import ApprovalPolicy
from urbanopay.modules.payments.application.services import (
    OPERATION_CREATE_PAYMENT,
    PaymentService,
)
from urbanopay.modules.payments.domain.enums import (
    PaymentMethod,
    PaymentStatus,
    ProviderName,
)
from urbanopay.modules.payments.domain.errors import (
    PaymentAlreadyApprovedError,
    PaymentCreationFailedError,
    PaymentStatusUnknownError,
)
from urbanopay.providers.payments.fake import FakePaymentProvider

from .fakes import FakeOrdersUnitOfWork, FakePaymentsUnitOfWork, Store

CUSTOMER = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
OTHER_CUSTOMER = uuid.UUID("00000000-0000-4000-8000-0000000000c2")
LATER = FIXED_NOW + timedelta(minutes=1)

TERMINAIS_NAO_APROVADOS = [
    PaymentStatus.REJECTED,
    PaymentStatus.CANCELLED,
    PaymentStatus.EXPIRED,
    PaymentStatus.FAILED,
]


def make_payment_service(
    store: Store, provider: FakePaymentProvider | None = None
) -> tuple[PaymentService, FakePaymentProvider]:
    resolved = provider or FakePaymentProvider()
    return PaymentService(FakePaymentsUnitOfWork(store), resolved), resolved


async def seed_confirmed_order(
    store: Store,
    *,
    total: Decimal = Decimal("50.00"),
    customer_id: uuid.UUID = CUSTOMER,
) -> uuid.UUID:
    """Order confirmado pelo cliente: Quote → Order → confirmação.

    O destino da confirmação depende de `requires_approval`, então a
    verificação aqui acompanha a política em vez de fixar um estado: acima do
    limiar o Order legitimamente para em `REQUIRES_APPROVAL`.
    """
    orders = OrderService(FakeOrdersUnitOfWork(store), ApprovalPolicy(), draft_ttl=TTL)
    quote = make_quote(customer_id=customer_id, total=total)
    store.state.quotes[quote.id] = quote
    order = await orders.create_order(
        customer_id=customer_id,
        quote_id=quote.id,
        idempotency_key=f"create-{quote.id}",
        at=FIXED_NOW,
    )
    confirmed = await orders.confirm_order(
        customer_id=customer_id,
        order_id=order.id,
        idempotency_key=f"confirm-{order.id}",
        at=FIXED_NOW,
    )
    esperado = OrderStatus.REQUIRES_APPROVAL if order.requires_approval else OrderStatus.CONFIRMED
    assert confirmed.status is esperado
    return order.id


# --- valor derivado (§10) ------------------------------------------------


@pytest.mark.unit
def test_create_payment_nao_aceita_valor_como_parametro() -> None:
    """O backend deriva o valor; nenhuma superfície de chamada o influencia.

    Se um `amount` aparecer nesta assinatura, uma tool do agente passaria a
    poder escolher quanto se cobra.
    """
    parametros = set(inspect.signature(PaymentService.create_payment).parameters)

    assert "amount" not in parametros
    assert "currency" not in parametros
    assert "status" not in parametros
    assert parametros == {"self", "customer_id", "order_id", "idempotency_key", "at"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_valor_do_payment_vem_do_total_do_order() -> None:
    store = Store()
    order_id = await seed_confirmed_order(store, total=Decimal("137.45"))
    service, _ = make_payment_service(store)

    resultado = await service.create_payment(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
    )

    assert resultado.payment.amount == Decimal("137.45")
    assert resultado.payment.amount == store.state.orders[order_id].total
    assert resultado.payment.currency == "BRL"


# --- criação bem-sucedida ------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_criacao_deixa_payment_pending_e_order_payment_pending() -> None:
    store = Store()
    order_id = await seed_confirmed_order(store)
    service, provider = make_payment_service(store)

    resultado = await service.create_payment(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
    )

    assert resultado.payment.status is PaymentStatus.PENDING
    assert resultado.payment.provider is ProviderName.FAKE
    assert resultado.payment.method is PaymentMethod.PIX
    assert resultado.payment.provider_payment_id is not None
    assert resultado.qr_code is not None
    assert resultado.already_existed is False
    assert store.state.orders[order_id].status is OrderStatus.PAYMENT_PENDING
    assert provider.create_calls == 1

    record = store.state.idempotency[(OPERATION_CREATE_PAYMENT, "p1")]
    assert record.status is IdempotencyStatus.COMPLETED
    assert record.resource_id == resultado.payment.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_codigo_pix_nao_e_persistido() -> None:
    """Minimização: o código é transitório e reconsultável (§9, decisão)."""
    store = Store()
    order_id = await seed_confirmed_order(store)
    service, _ = make_payment_service(store)

    resultado = await service.create_payment(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
    )

    persistido = store.state.payments[resultado.payment.id]
    assert resultado.qr_code is not None
    assert not hasattr(persistido, "qr_code")
    assert resultado.qr_code not in str(persistido)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pagamento_exige_order_confirmado() -> None:
    store = Store()
    order_id = await seed_confirmed_order(store, total=Decimal("250.00"))
    # Order de 250 vai para REQUIRES_APPROVAL na confirmação, não CONFIRMED.
    assert store.state.orders[order_id].status is OrderStatus.REQUIRES_APPROVAL
    service, provider = make_payment_service(store)

    with pytest.raises(OrderRequiresApprovalError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )

    assert not store.state.payments
    assert provider.create_calls == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_de_outro_cliente_nao_e_pagavel() -> None:
    store = Store()
    order_id = await seed_confirmed_order(store)
    service, provider = make_payment_service(store)

    with pytest.raises(OrderNotAccessibleError):
        await service.create_payment(
            customer_id=OTHER_CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )
    assert provider.create_calls == 0


# --- estado externo desconhecido (§9.1) ---------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_timeout_deixa_created_pending_e_in_progress() -> None:
    """Timeout é estado desconhecido, nunca falha definitiva (§9.1)."""
    store = Store()
    order_id = await seed_confirmed_order(store)
    provider = FakePaymentProvider()
    provider.register_then_timeout_on_next_create()
    service, _ = make_payment_service(store, provider)

    with pytest.raises(PaymentStatusUnknownError) as exc:
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )
    assert exc.value.code == "PAYMENT_STATUS_UNKNOWN"

    payment = next(iter(store.state.payments.values()))
    assert payment.status is PaymentStatus.CREATED
    assert store.state.orders[order_id].status is OrderStatus.PAYMENT_PENDING
    assert store.state.idempotency[(OPERATION_CREATE_PAYMENT, "p1")].status is (
        IdempotencyStatus.IN_PROGRESS
    )
    assert provider.create_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_de_key_em_andamento_nao_emite_novo_post() -> None:
    """§11.3: o tempo autoriza reconciliação, nunca cobrança."""
    store = Store()
    order_id = await seed_confirmed_order(store)
    provider = FakePaymentProvider()
    provider.register_then_timeout_on_next_create()
    service, _ = make_payment_service(store, provider)

    with pytest.raises(PaymentStatusUnknownError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )

    # Segunda apresentação da MESMA key, ainda IN_PROGRESS.
    with pytest.raises(PaymentStatusUnknownError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )

    assert provider.create_calls == 1, "nenhum POST adicional pode ser emitido"
    assert len(store.state.payments) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nova_key_com_tentativa_created_tambem_e_recusada() -> None:
    """Nenhuma nova tentativa comercial antes de reconciliar (§9.1)."""
    store = Store()
    order_id = await seed_confirmed_order(store)
    provider = FakePaymentProvider()
    provider.register_then_timeout_on_next_create()
    service, _ = make_payment_service(store, provider)

    with pytest.raises(PaymentStatusUnknownError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )

    with pytest.raises(PaymentStatusUnknownError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p2", at=LATER
        )

    assert provider.create_calls == 1
    assert len(store.state.payments) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconciliacao_resolve_o_estado_desconhecido() -> None:
    """Retry técnico (§13.1): mesma cobrança, sem novo POST."""
    store = Store()
    order_id = await seed_confirmed_order(store)
    provider = FakePaymentProvider()
    provider.register_then_timeout_on_next_create()
    service, _ = make_payment_service(store, provider)

    with pytest.raises(PaymentStatusUnknownError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )
    payment_id = next(iter(store.state.payments))

    reconciliado = await service.reconcile_payment(payment_id=payment_id, at=LATER)

    assert reconciliado.id == payment_id, "mesmo payment_id, nenhuma tentativa nova"
    assert reconciliado.status is PaymentStatus.PENDING
    assert reconciliado.provider_payment_id is not None
    assert provider.create_calls == 1
    assert provider.lookup_calls == 1
    assert store.state.idempotency[(OPERATION_CREATE_PAYMENT, "p1")].status is (
        IdempotencyStatus.COMPLETED
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconciliacao_de_cobranca_aprovada_marca_order_pago() -> None:
    store = Store()
    order_id = await seed_confirmed_order(store)
    provider = FakePaymentProvider()
    provider.register_then_timeout_on_next_create()
    service, _ = make_payment_service(store, provider)

    with pytest.raises(PaymentStatusUnknownError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )
    charge_id = provider.charge_id_for_key("p1")
    assert charge_id is not None
    provider.settle(charge_id, PaymentStatus.APPROVED)

    payment_id = next(iter(store.state.payments))
    reconciliado = await service.reconcile_payment(payment_id=payment_id, at=LATER)

    assert reconciliado.status is PaymentStatus.APPROVED
    assert store.state.orders[order_id].status is OrderStatus.PAID


# --- falha determinística (§9, §11.1) -----------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recusa_deterministica_marca_failed_e_devolve_order() -> None:
    store = Store()
    order_id = await seed_confirmed_order(store)
    provider = FakePaymentProvider()
    provider.fail_next_create_deterministically()
    service, _ = make_payment_service(store, provider)

    with pytest.raises(PaymentCreationFailedError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )

    payment = next(iter(store.state.payments.values()))
    assert payment.status is PaymentStatus.FAILED
    # Terminal não aprovado devolve o Order a CONFIRMED (§13.2).
    assert store.state.orders[order_id].status is OrderStatus.CONFIRMED
    assert store.state.idempotency[(OPERATION_CREATE_PAYMENT, "p1")].status is (
        IdempotencyStatus.FAILED
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_de_falha_deterministica_reproduz_a_falha() -> None:
    """`FAILED` é reproduzido em replay, sem nova chamada ao provider (§11.1)."""
    store = Store()
    order_id = await seed_confirmed_order(store)
    provider = FakePaymentProvider()
    provider.fail_next_create_deterministically()
    service, _ = make_payment_service(store, provider)

    with pytest.raises(PaymentCreationFailedError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )

    with pytest.raises(PaymentCreationFailedError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
        )

    assert provider.create_calls == 1
    assert len(store.state.payments) == 1


# --- replay de sucesso ---------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_de_key_concluida_devolve_o_mesmo_payment() -> None:
    store = Store()
    order_id = await seed_confirmed_order(store)
    service, provider = make_payment_service(store)

    primeiro = await service.create_payment(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
    )
    segundo = await service.create_payment(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
    )

    assert segundo.payment.id == primeiro.payment.id
    assert segundo.already_existed is True
    assert segundo.qr_code is None
    assert provider.create_calls == 1
    assert len(store.state.payments) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nova_key_com_tentativa_pending_devolve_a_existente() -> None:
    """No máximo uma tentativa ativa por Order (§9)."""
    store = Store()
    order_id = await seed_confirmed_order(store)
    service, provider = make_payment_service(store)

    primeiro = await service.create_payment(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
    )
    segundo = await service.create_payment(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="p2", at=LATER
    )

    assert segundo.payment.id == primeiro.payment.id
    assert segundo.already_existed is True
    assert provider.create_calls == 1
    assert len(store.state.payments) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_com_pagamento_aprovado_nao_aceita_nova_cobranca() -> None:
    store = Store()
    order_id = await seed_confirmed_order(store)
    service, provider = make_payment_service(store)

    resultado = await service.create_payment(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
    )
    charge_id = resultado.payment.provider_payment_id
    assert charge_id is not None
    await service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id="evt-1",
        provider_payment_id=charge_id,
        reported_status=PaymentStatus.APPROVED,
        payload={"id": charge_id, "status": "approved"},
        at=LATER,
    )

    with pytest.raises(PaymentAlreadyApprovedError):
        await service.create_payment(
            customer_id=CUSTOMER, order_id=order_id, idempotency_key="p2", at=LATER
        )
    assert provider.create_calls == 1


# --- webhook (§12) -------------------------------------------------------


async def seed_pending_payment(store: Store) -> tuple[PaymentService, str, uuid.UUID]:
    order_id = await seed_confirmed_order(store)
    service, _ = make_payment_service(store)
    resultado = await service.create_payment(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="p1", at=LATER
    )
    charge_id = resultado.payment.provider_payment_id
    assert charge_id is not None
    return service, charge_id, order_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webhook_aprovado_marca_order_pago() -> None:
    store = Store()
    service, charge_id, order_id = await seed_pending_payment(store)

    resultado = await service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id="evt-1",
        provider_payment_id=charge_id,
        reported_status=PaymentStatus.APPROVED,
        payload={"id": charge_id, "status": "approved"},
        at=LATER,
    )

    assert resultado.duplicate is False
    assert resultado.applied is True
    assert resultado.payment is not None
    assert resultado.payment.status is PaymentStatus.APPROVED
    assert store.state.orders[order_id].status is OrderStatus.PAID


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webhook_duplicado_nao_produz_efeito_duplicado() -> None:
    store = Store()
    service, charge_id, order_id = await seed_pending_payment(store)
    evento = {
        "provider": ProviderName.FAKE,
        "provider_event_id": "evt-1",
        "provider_payment_id": charge_id,
        "reported_status": PaymentStatus.APPROVED,
        "payload": {"id": charge_id, "status": "approved"},
        "at": LATER,
    }

    primeiro = await service.process_webhook(**evento)  # type: ignore[arg-type]
    segundo = await service.process_webhook(**evento)  # type: ignore[arg-type]

    assert primeiro.applied is True
    assert segundo.duplicate is True
    assert segundo.applied is False
    assert store.state.orders[order_id].status is OrderStatus.PAID
    assert len(store.state.events) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webhook_fora_de_ordem_nao_derruba_estado_terminal() -> None:
    store = Store()
    service, charge_id, order_id = await seed_pending_payment(store)

    await service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id="evt-1",
        provider_payment_id=charge_id,
        reported_status=PaymentStatus.APPROVED,
        payload={"id": charge_id},
        at=LATER,
    )
    atrasado = await service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id="evt-2",
        provider_payment_id=charge_id,
        reported_status=PaymentStatus.REJECTED,
        payload={"id": charge_id},
        at=LATER,
    )

    assert atrasado.applied is False
    assert atrasado.payment is not None
    assert atrasado.payment.status is PaymentStatus.APPROVED
    assert store.state.orders[order_id].status is OrderStatus.PAID


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webhook_de_aprovacao_sobre_terminal_pede_reconciliacao() -> None:
    store = Store()
    service, charge_id, order_id = await seed_pending_payment(store)

    await service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id="evt-1",
        provider_payment_id=charge_id,
        reported_status=PaymentStatus.REJECTED,
        payload={"id": charge_id},
        at=LATER,
    )
    divergente = await service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id="evt-2",
        provider_payment_id=charge_id,
        reported_status=PaymentStatus.APPROVED,
        payload={"id": charge_id},
        at=LATER,
    )

    assert divergente.applied is False
    assert divergente.requires_reconciliation is True
    # O Order NÃO é marcado como pago automaticamente.
    assert store.state.orders[order_id].status is OrderStatus.CONFIRMED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webhook_persiste_apenas_payload_redigido() -> None:
    store = Store()
    service, charge_id, _ = await seed_pending_payment(store)

    resultado = await service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id="evt-1",
        provider_payment_id=charge_id,
        reported_status=PaymentStatus.APPROVED,
        payload={
            "id": charge_id,
            "status": "approved",
            "access_token": "TEST-token-secreto",
            "payer_cpf": "12345678901",
        },
        at=LATER,
    )

    assert resultado.applied is True
    # O evento registrado guarda somente identidade; nada do payload bruto
    # sensível transita para o estado persistido.
    registro = str(store.state.events)
    assert "TEST-token-secreto" not in registro
    assert "12345678901" not in registro


# --- nova tentativa comercial (§13.2) -----------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", TERMINAIS_NAO_APROVADOS)
async def test_terminal_nao_aprovado_devolve_order_a_confirmed(
    terminal: PaymentStatus,
) -> None:
    store = Store()
    service, charge_id, order_id = await seed_pending_payment(store)

    await service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id="evt-1",
        provider_payment_id=charge_id,
        reported_status=terminal,
        payload={"id": charge_id},
        at=LATER,
    )

    assert store.state.orders[order_id].status is OrderStatus.CONFIRMED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nova_tentativa_comercial_usa_novo_payment_e_nova_key() -> None:
    store = Store()
    service, charge_id, order_id = await seed_pending_payment(store)
    primeiro_id = next(iter(store.state.payments))

    await service.process_webhook(
        provider=ProviderName.FAKE,
        provider_event_id="evt-1",
        provider_payment_id=charge_id,
        reported_status=PaymentStatus.REJECTED,
        payload={"id": charge_id},
        at=LATER,
    )

    segundo = await service.create_payment(
        customer_id=CUSTOMER, order_id=order_id, idempotency_key="p2", at=LATER
    )

    assert segundo.payment.id != primeiro_id
    assert segundo.payment.idempotency_key == "p2"
    assert segundo.payment.status is PaymentStatus.PENDING
    assert len(store.state.payments) == 2
    assert store.state.orders[order_id].status is OrderStatus.PAYMENT_PENDING


# --- mensagem do usuário (§2, §9) ---------------------------------------


@pytest.mark.unit
def test_nenhuma_operacao_aceita_texto_do_usuario() -> None:
    """ "eu paguei" não é evento de domínio: não existe parâmetro para ele.

    Varre a superfície pública do serviço e reprova qualquer parâmetro que
    aceite mensagem, texto ou afirmação do usuário. É a versão verificável da
    regra — mais forte que confiar em revisão de código.
    """
    proibidos = {"message", "text", "user_message", "user_text", "claim", "statement"}

    for nome, membro in inspect.getmembers(PaymentService, inspect.isfunction):
        if nome.startswith("_"):
            continue
        parametros = set(inspect.signature(membro).parameters)
        assert not (parametros & proibidos), (
            f"{nome} aceita texto do usuário: {parametros & proibidos}"
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_afirmacao_de_pagamento_nao_altera_estado() -> None:
    """Sem webhook e sem consulta, o Order permanece aguardando pagamento."""
    store = Store()
    _, _, order_id = await seed_pending_payment(store)

    # Nada acontece entre a criação e esta verificação: o "cliente disse que
    # pagou" não tem canal para produzir efeito algum.
    payment = next(iter(store.state.payments.values()))
    assert payment.status is PaymentStatus.PENDING
    assert store.state.orders[order_id].status is OrderStatus.PAYMENT_PENDING
    assert store.state.orders[order_id].status is not OrderStatus.PAID
