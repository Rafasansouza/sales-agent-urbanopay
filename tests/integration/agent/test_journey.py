"""Jornada de recarga pela camada de tools, contra PostgreSQL real.

O que estes testes acrescentam aos unitários: **constraints e transações de
verdade**. Índice único parcial de tentativa ativa, titularidade em query
única, atomicidade do efeito de recarga — nada disso é observável em memória.

Convenção deste arquivo: quando um cenário precisa de um efeito que só o
backend produz — provider confirmando pagamento, webhook, fulfillment —, o
teste chama o **serviço de backend diretamente**, e isso está sinalizado no
nome do helper. Não é ação do Sales Agent, e não passa por tool alguma.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from tests.integration.agent.conftest import FIXED_OTP, AgentTestData
from urbanopay.modules.agent.application.executor import ExecutionOutcome, ToolExecutor
from urbanopay.modules.agent.domain.catalog import ToolCaller
from urbanopay.modules.agent.domain.conversation import ConversationState
from urbanopay.modules.agent.domain.idempotency_keys import IdempotencyKeyPolicy
from urbanopay.modules.agent.domain.results import GuardCode, NextAction
from urbanopay.modules.agent.infrastructure.composition import AgentServices
from urbanopay.modules.fulfillment.domain.errors import ReconciliationRequiredError
from urbanopay.modules.payments.domain.enums import PaymentStatus
from urbanopay.providers.payments.fake import FakePaymentProvider

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

RECHARGE = Decimal("100.00")
ABOVE_THRESHOLD = Decimal("250.00")


async def _authenticate(
    executor: ToolExecutor, state: ConversationState, *, document: str
) -> ConversationState:
    """Autentica pela jornada real: documento → desafio → OTP."""
    outcome = await executor.execute(
        state=state,
        tool_name="start_authentication",
        arguments={"document": document},
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.ok is True, outcome.result
    assert outcome.result.data["identification_status"] == "CUSTOMER_FOUND"

    outcome = await executor.execute(
        state=outcome.state.begin_turn(),
        tool_name="verify_otp",
        arguments={"otp": FIXED_OTP},
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.ok is True, outcome.result
    assert outcome.result.data["authenticated"] is True
    return outcome.state.begin_turn()


async def _quote_order_confirm(
    executor: ToolExecutor,
    state: ConversationState,
    card_id: uuid.UUID,
    amount: Decimal,
) -> ExecutionOutcome:
    outcome = await executor.execute(
        state=state,
        tool_name="create_recharge_quote",
        arguments={"card_id": str(card_id), "amount": str(amount)},
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.ok is True, outcome.result
    outcome = await executor.execute(
        state=outcome.state.begin_turn(),
        tool_name="create_order",
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.ok is True, outcome.result
    return await executor.execute(
        state=outcome.state.begin_turn(),
        tool_name="confirm_order",
        caller=ToolCaller.ORCHESTRATOR,
    )


async def _backend_settles_payment(
    services: AgentServices,
    provider: FakePaymentProvider,
    *,
    order_id: uuid.UUID,
    payment_id: uuid.UUID,
    status: PaymentStatus,
) -> None:
    """**Backend**, não agente: o provider decide e a reconciliação aplica.

    É o único caminho pelo qual um pagamento se torna `APPROVED` — como em
    produção, onde só o provider estabelece isso (SPEC-003 §9).
    """
    charge_id = provider.charge_id_for_key(
        IdempotencyKeyPolicy.create_payment(order_id, previous_terminal_payment_id=None)
    )
    assert charge_id is not None
    provider.settle(charge_id, status)
    await services.payments.reconcile_payment(payment_id=payment_id)


# --- jornada completa ---------------------------------------------------------


async def test_recarga_ate_200_percorre_a_jornada(
    executor: ToolExecutor,
    services: AgentServices,
    provider: FakePaymentProvider,
    data: AgentTestData,
    anonymous_state: ConversationState,
) -> None:
    """Autenticação → cartão → Quote → Order → confirmação → Pix → entrega."""
    customer = await data.add_customer()
    card_id = await data.add_card(customer_id=customer.id, balance="21.50")

    state = await _authenticate(executor, anonymous_state, document=customer.cpf)

    cards = await executor.execute(state=state, tool_name="get_customer_cards")
    assert cards.result.ok is True
    assert cards.result.data["count"] == 1
    state = cards.state.begin_turn()

    confirmed = await _quote_order_confirm(executor, state, card_id, RECHARGE)
    assert confirmed.result.ok is True
    assert confirmed.result.data["status"] == "CONFIRMED"
    order_id = uuid.UUID(str(confirmed.result.data["order_id"]))

    payment = await executor.execute(
        state=confirmed.state.begin_turn(),
        tool_name="create_payment",
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert payment.result.ok is True, payment.result
    assert payment.result.data["amount"] == "100.00"
    assert payment.result.data["qr_code"]
    assert payment.result.next_action is NextAction.AWAIT_PAYMENT
    payment_id = uuid.UUID(str(payment.result.data["payment_id"]))
    assert await data.order_status(order_id) == "PAYMENT_PENDING"

    await _backend_settles_payment(
        services,
        provider,
        order_id=order_id,
        payment_id=payment_id,
        status=PaymentStatus.APPROVED,
    )
    assert await data.order_status(order_id) == "PAID"

    # **Backend**, não agente: o disparo pertence à composição (SPEC-005 §10.1).
    await services.fulfillment.fulfill_order(order_id=order_id)

    state = payment.state.begin_turn()
    status = await executor.execute(
        state=state, tool_name="get_fulfillment_status", arguments={"order_id": str(order_id)}
    )
    assert status.result.data["status"] == "COMPLETED"
    assert status.result.next_action is NextAction.CONTINUE

    receipt = await executor.execute(
        state=state, tool_name="get_receipt", arguments={"order_id": str(order_id)}
    )
    assert receipt.result.ok is True
    assert receipt.result.data["amount"] == "100.00"
    assert receipt.result.data["masked_card"] == "****4821"
    assert receipt.result.data["document_kind"] == "SIMULATED_NON_FISCAL"

    balance = await executor.execute(
        state=state, tool_name="get_card_balance", arguments={"card_id": str(card_id)}
    )
    assert balance.result.data["balance"] == "121.50"
    assert await data.balance_of(card_id) == Decimal("121.50")
    assert await data.count_ledger(order_id) == 1


async def test_recarga_acima_de_200_para_em_aprovacao(
    executor: ToolExecutor,
    data: AgentTestData,
    anonymous_state: ConversationState,
) -> None:
    """> R$ 200,00: `REQUIRES_APPROVAL`, `Approval PENDING`, zero Payment."""
    customer = await data.add_customer()
    card_id = await data.add_card(customer_id=customer.id)
    state = await _authenticate(executor, anonymous_state, document=customer.cpf)

    confirmed = await _quote_order_confirm(executor, state, card_id, ABOVE_THRESHOLD)
    assert confirmed.result.data["status"] == "REQUIRES_APPROVAL"
    assert confirmed.result.next_action is NextAction.AWAIT_HUMAN_APPROVAL
    order_id = uuid.UUID(str(confirmed.result.data["order_id"]))

    approval = await executor.execute(
        state=confirmed.state.begin_turn(),
        tool_name="get_approval_status",
        arguments={"order_id": str(order_id)},
    )
    assert approval.result.data["approval_status"] == "PENDING"
    assert approval.result.data["requires_approval"] is True
    assert "decided_by" not in approval.result.data

    # A jornada financeira para: o Payment é recusado pela state machine.
    payment = await executor.execute(
        state=approval.state.begin_turn(),
        tool_name="create_payment",
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert payment.result.ok is False
    assert payment.result.code == "ORDER_REQUIRES_APPROVAL"
    assert await data.count_payments(order_id) == 0
    assert await data.order_status(order_id) == "REQUIRES_APPROVAL"


# --- pagamento inconclusivo ---------------------------------------------------


async def test_timeout_do_provider_nao_emite_segunda_cobranca(
    executor: ToolExecutor,
    provider: FakePaymentProvider,
    data: AgentTestData,
    anonymous_state: ConversationState,
) -> None:
    """§9.1 contra o índice único parcial real: uma tentativa ativa, e só."""
    customer = await data.add_customer()
    card_id = await data.add_card(customer_id=customer.id)
    state = await _authenticate(executor, anonymous_state, document=customer.cpf)
    confirmed = await _quote_order_confirm(executor, state, card_id, RECHARGE)
    order_id = uuid.UUID(str(confirmed.result.data["order_id"]))

    provider.register_then_timeout_on_next_create()
    primeira = await executor.execute(
        state=confirmed.state.begin_turn(),
        tool_name="create_payment",
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert primeira.result.code == "PAYMENT_STATUS_UNKNOWN"
    assert primeira.result.next_action is NextAction.WAIT_RECONCILIATION

    segunda = await executor.execute(
        state=primeira.state.begin_turn(),
        tool_name="create_payment",
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert segunda.result.code == "PAYMENT_STATUS_UNKNOWN"
    assert provider.create_calls == 1
    assert await data.count_payments(order_id) == 1
    assert await data.order_status(order_id) == "PAYMENT_PENDING"

    consulta = await executor.execute(
        state=segunda.state.begin_turn(),
        tool_name="get_payment_status",
        arguments={"order_id": str(order_id)},
    )
    assert consulta.result.data["status"] == PaymentStatus.CREATED.value
    assert consulta.result.next_action is NextAction.WAIT_RECONCILIATION


async def test_terminal_nao_aprovado_permite_nova_tentativa_comercial(
    executor: ToolExecutor,
    services: AgentServices,
    provider: FakePaymentProvider,
    data: AgentTestData,
    anonymous_state: ConversationState,
) -> None:
    """§13.2: Payment rejeitado devolve o Order a `CONFIRMED`; nova key, novo id."""
    customer = await data.add_customer()
    card_id = await data.add_card(customer_id=customer.id)
    state = await _authenticate(executor, anonymous_state, document=customer.cpf)
    confirmed = await _quote_order_confirm(executor, state, card_id, RECHARGE)
    order_id = uuid.UUID(str(confirmed.result.data["order_id"]))

    primeira = await executor.execute(
        state=confirmed.state.begin_turn(),
        tool_name="create_payment",
        caller=ToolCaller.ORCHESTRATOR,
    )
    payment_id = uuid.UUID(str(primeira.result.data["payment_id"]))

    await _backend_settles_payment(
        services,
        provider,
        order_id=order_id,
        payment_id=payment_id,
        status=PaymentStatus.REJECTED,
    )
    assert await data.order_status(order_id) == "CONFIRMED"

    segunda = await executor.execute(
        state=primeira.state.begin_turn(),
        tool_name="create_payment",
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert segunda.result.ok is True, segunda.result
    assert segunda.result.data["payment_id"] != str(payment_id)
    assert await data.count_payments(order_id) == 2


# --- pós-venda e reconciliação ------------------------------------------------


async def test_cartao_inativo_apos_pagamento_para_em_reconciliacao(
    executor: ToolExecutor,
    services: AgentServices,
    provider: FakePaymentProvider,
    data: AgentTestData,
    anonymous_state: ConversationState,
) -> None:
    """SPEC-005 §11.2 / A-18: zero crédito, e a conversa pede análise humana."""
    customer = await data.add_customer()
    card_id = await data.add_card(customer_id=customer.id, balance="21.50")
    state = await _authenticate(executor, anonymous_state, document=customer.cpf)
    confirmed = await _quote_order_confirm(executor, state, card_id, RECHARGE)
    order_id = uuid.UUID(str(confirmed.result.data["order_id"]))

    payment = await executor.execute(
        state=confirmed.state.begin_turn(),
        tool_name="create_payment",
        caller=ToolCaller.ORCHESTRATOR,
    )
    payment_id = uuid.UUID(str(payment.result.data["payment_id"]))
    await _backend_settles_payment(
        services,
        provider,
        order_id=order_id,
        payment_id=payment_id,
        status=PaymentStatus.APPROVED,
    )

    # O cartão é bloqueado entre o pagamento e a entrega.
    await data.set_card_status(card_id, "BLOCKED")
    with pytest.raises(ReconciliationRequiredError):
        await services.fulfillment.fulfill_order(order_id=order_id)

    assert await data.balance_of(card_id) == Decimal("21.50")
    assert await data.count_ledger(order_id) == 0

    status = await executor.execute(
        state=payment.state.begin_turn(),
        tool_name="get_fulfillment_status",
        arguments={"order_id": str(order_id)},
    )
    assert status.result.data["status"] == "RECONCILIATION_REQUIRED"
    assert status.result.data["failure_reason"] == "CARD_NOT_ACTIVE"
    assert status.result.next_action is NextAction.HUMAN_REVIEW

    receipt = await executor.execute(
        state=status.state.begin_turn(),
        tool_name="get_receipt",
        arguments={"order_id": str(order_id)},
    )
    assert receipt.result.ok is False
    assert receipt.result.code == "RECEIPT_NOT_AVAILABLE"


# --- autorização contra o banco real ------------------------------------------


async def test_cross_user_nao_alcanca_recurso_alheio(
    executor: ToolExecutor,
    services: AgentServices,
    data: AgentTestData,
    anonymous_state: ConversationState,
) -> None:
    """Titularidade em query única: cartão e Order de terceiro são inacessíveis.

    Os dois sentidos são exercitados, porque são consultas diferentes: o
    cartão do outro cliente, e o Order do primeiro cliente visto por uma
    sessão do segundo.
    """
    dono = await data.add_customer()
    card_id = await data.add_card(customer_id=dono.id)
    state = await _authenticate(executor, anonymous_state, document=dono.cpf)
    confirmed = await _quote_order_confirm(executor, state, card_id, RECHARGE)
    order_id = uuid.UUID(str(confirmed.result.data["order_id"]))

    outro = await data.add_customer()
    cartao_alheio = await data.add_card(customer_id=outro.id, last4="1257")

    intruso = await executor.execute(
        state=confirmed.state.begin_turn(),
        tool_name="get_card_balance",
        arguments={"card_id": str(cartao_alheio)},
    )
    assert intruso.result.code == "CARD_NOT_ACCESSIBLE"
    assert intruso.result.data == {}

    # Sessão do segundo cliente: o Order do primeiro é inacessível, e a
    # resposta não distingue "não existe" de "não é seu".
    outra_sessao = await services.sessions.create_anonymous_session()
    data.track_session(outra_sessao.id)
    estado_do_outro = await _authenticate(
        executor,
        ConversationState(conversation_id=uuid.uuid4(), session_id=outra_sessao.id),
        document=outro.cpf,
    )

    alheio = await executor.execute(
        state=estado_do_outro,
        tool_name="get_order",
        arguments={"order_id": str(order_id)},
    )
    inexistente = await executor.execute(
        state=estado_do_outro.begin_turn(),
        tool_name="get_order",
        arguments={"order_id": str(uuid.uuid4())},
    )
    assert alheio.result.code == inexistente.result.code == "ORDER_NOT_ACCESSIBLE"
    assert alheio.result.data == inexistente.result.data == {}


async def test_sessao_expirada_interrompe_a_jornada(
    executor: ToolExecutor,
    services: AgentServices,
    data: AgentTestData,
    anonymous_state: ConversationState,
) -> None:
    """Sessão vencida não transaciona, mesmo tendo sido autenticada antes."""
    customer = await data.add_customer()
    await data.add_card(customer_id=customer.id)
    state = await _authenticate(executor, anonymous_state, document=customer.cpf)

    await data.expire_session(state.session_id)

    outcome = await executor.execute(state=state, tool_name="get_customer_cards")
    assert outcome.result.code == "SESSION_EXPIRED"
    assert outcome.result.next_action is NextAction.AUTHENTICATE
    del services


async def test_sessao_anonima_conversa_mas_nao_transaciona(
    executor: ToolExecutor,
    data: AgentTestData,
    anonymous_state: ConversationState,
) -> None:
    """PRD RF-05/RF-06: simula tarifa anônimo, transaciona só autenticado."""
    await data.add_customer()

    fare = await executor.execute(
        state=anonymous_state,
        tool_name="calculate_trip_fare",
        arguments={
            "segments": [{"mode": "BUS", "line_code": "101"}, {"mode": "METRO"}],
            "declared_fare_profile": "INTEGRAL",
        },
    )
    assert fare.result.ok is True
    assert fare.result.data["trip_type"] == "INTEGRATION"
    assert fare.result.data["subtotal"] == "16.00"
    assert fare.result.data["total"] == "13.60"
    assert fare.result.data["profile_verified"] is False

    protegida = await executor.execute(
        state=fare.state.begin_turn(), tool_name="get_customer_cards"
    )
    assert protegida.result.code == "NOT_AUTHENTICATED"
    assert protegida.result.next_action is NextAction.AUTHENTICATE


async def test_tools_indisponiveis_e_proibidas_contra_o_banco_real(
    executor: ToolExecutor,
    data: AgentTestData,
    anonymous_state: ConversationState,
) -> None:
    """A-05/A-06 e a denylist continuam valendo com infraestrutura real."""
    await data.add_customer()

    for tool_name in ("search_products", "get_product", "get_ticket", "calculate_usage_cost"):
        outcome = await executor.execute(
            state=anonymous_state, tool_name=tool_name, caller=ToolCaller.ORCHESTRATOR
        )
        assert outcome.result.code == GuardCode.TOOL_UNAVAILABLE.value

    for tool_name in ("fulfill_order", "approve_order", "reconcile_payment", "execute_sql"):
        outcome = await executor.execute(
            state=anonymous_state,
            tool_name=tool_name,
            arguments={"order_id": str(uuid.uuid4())},
            caller=ToolCaller.ORCHESTRATOR,
        )
        assert outcome.result.code == GuardCode.TOOL_NOT_AUTHORIZED.value
