"""Política de idempotência e caminho de pagamento (SPEC-003 §11, §13).

A propriedade que estes testes protegem é uma só, dita de várias formas:

> **Nenhuma sequência de chamadas da camada conversacional produz duas
> cobranças para o mesmo Order.**

E o corolário: a identidade de uma tentativa vem de evidência persistida, não
de contador em memória, não do relógio e nunca do modelo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.unit.agent.world import RECHARGE_AMOUNT, AgentWorld
from urbanopay.modules.agent.application.executor import ToolExecutor
from urbanopay.modules.agent.domain.catalog import ToolCaller
from urbanopay.modules.agent.domain.conversation import ConversationState
from urbanopay.modules.agent.domain.idempotency_keys import IdempotencyKeyPolicy
from urbanopay.modules.agent.domain.results import NextAction
from urbanopay.modules.orders.application.services import (
    OPERATION_CONFIRM_ORDER,
    OPERATION_CREATE_ORDER,
)
from urbanopay.modules.orders.domain.enums import OrderStatus
from urbanopay.modules.payments.application.services import OPERATION_CREATE_PAYMENT
from urbanopay.modules.payments.domain.enums import PaymentStatus

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


def _executor(world: AgentWorld) -> ToolExecutor:
    return ToolExecutor(world.services, clock=lambda: FIXED_NOW)


# --- a política, isolada ------------------------------------------------------


@pytest.mark.unit
def test_key_de_create_order_deriva_da_quote() -> None:
    quote_id = uuid.uuid4()
    key = IdempotencyKeyPolicy.create_order(quote_id)
    assert key == f"create_order:{quote_id}"
    # Determinística: a mesma Quote sempre produz a mesma key.
    assert key == IdempotencyKeyPolicy.create_order(quote_id)


@pytest.mark.unit
def test_key_de_confirm_order_deriva_do_order() -> None:
    order_id = uuid.uuid4()
    key = IdempotencyKeyPolicy.confirm_order(order_id)
    assert key == f"confirm_order:{order_id}"
    assert key == IdempotencyKeyPolicy.confirm_order(order_id)


@pytest.mark.unit
def test_primeira_tentativa_de_pagamento_usa_identidade_inicial() -> None:
    order_id = uuid.uuid4()
    assert (
        IdempotencyKeyPolicy.create_payment(order_id, previous_terminal_payment_id=None)
        == f"create_payment:{order_id}:initial"
    )


@pytest.mark.unit
def test_nova_tentativa_comercial_deriva_da_terminal_anterior() -> None:
    """§13.2: a nova identidade nasce do desfecho anterior, não de um contador.

    Duas chamadas concorrentes que observem o **mesmo** terminal produzem a
    mesma key — e é isso que faz a segunda ser replay, não segunda cobrança.
    """
    order_id = uuid.uuid4()
    terminal = uuid.uuid4()
    key = IdempotencyKeyPolicy.create_payment(order_id, previous_terminal_payment_id=terminal)
    assert key == f"create_payment:{order_id}:after:{terminal}"
    assert key == IdempotencyKeyPolicy.create_payment(
        order_id, previous_terminal_payment_id=terminal
    )
    assert key != IdempotencyKeyPolicy.create_payment(order_id, previous_terminal_payment_id=None)


# --- a política, na jornada ---------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirmacao_repetida_produz_um_unico_efeito() -> None:
    """Segundo "sim" sobre o mesmo Order é replay da mesma key."""
    world = AgentWorld()
    executor = _executor(world)
    state = await _quote_and_order(world, executor, RECHARGE_AMOUNT)

    primeira = await executor.execute(
        state=state, tool_name="confirm_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert primeira.result.ok is True

    # O contexto foi consumido: um segundo "sim" nem chega ao serviço.
    segunda = await executor.execute(
        state=primeira.state, tool_name="confirm_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert segunda.result.ok is False
    assert segunda.result.code == "NO_PENDING_CONFIRMATION"

    # E, mesmo reapresentando o contexto, o efeito continua único.
    replay = await executor.execute(
        state=state, tool_name="confirm_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert replay.result.ok is True
    assert replay.result.data["order_id"] == primeira.result.data["order_id"]

    confirm_keys = [
        key
        for operation, key in world.store.state.idempotency
        if operation == OPERATION_CONFIRM_ORDER
    ]
    assert len(confirm_keys) == 1
    assert len(world.store.state.orders) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_keys_da_jornada_sao_as_derivadas() -> None:
    """As keys persistidas são exatamente as que a política produz."""
    world = AgentWorld()
    executor = _executor(world)
    state = await _quote_and_order(world, executor, RECHARGE_AMOUNT)
    quote_id = state.current_quote_id
    order_id = state.current_order_id
    assert quote_id is not None
    assert order_id is not None

    outcome = await executor.execute(
        state=state, tool_name="confirm_order", caller=ToolCaller.ORCHESTRATOR
    )
    state = outcome.state
    await executor.execute(state=state, tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR)

    assert (OPERATION_CREATE_ORDER, IdempotencyKeyPolicy.create_order(quote_id)) in (
        world.store.state.idempotency
    )
    assert (OPERATION_CONFIRM_ORDER, IdempotencyKeyPolicy.confirm_order(order_id)) in (
        world.store.state.idempotency
    )
    assert (
        OPERATION_CREATE_PAYMENT,
        IdempotencyKeyPolicy.create_payment(order_id, previous_terminal_payment_id=None),
    ) in world.store.state.idempotency


@pytest.mark.unit
@pytest.mark.asyncio
async def test_timeout_do_provider_nao_gera_segunda_cobranca() -> None:
    """§9.1: estado externo desconhecido é terminal para a automação do turno.

    O provider registra a cobrança e só então falha — o cenário perigoso, em
    que uma retentativa cega produziria cobrança dupla.
    """
    world = AgentWorld()
    executor = _executor(world)
    state = await _confirmed(world, executor, RECHARGE_AMOUNT)

    world.provider.register_then_timeout_on_next_create()
    primeira = await executor.execute(
        state=state, tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR
    )
    assert primeira.result.ok is False
    assert primeira.result.code == "PAYMENT_STATUS_UNKNOWN"
    assert primeira.result.next_action is NextAction.WAIT_RECONCILIATION
    assert world.provider.create_calls == 1

    # Segunda chamada: nenhum POST novo, nenhuma key nova, nenhum Payment novo.
    segunda = await executor.execute(
        state=primeira.state, tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR
    )
    assert segunda.result.code == "PAYMENT_STATUS_UNKNOWN"
    assert world.provider.create_calls == 1
    assert len(world.store.state.payments) == 1
    payment = next(iter(world.store.state.payments.values()))
    assert payment.status is PaymentStatus.CREATED
    assert world.store.state.orders[payment.order_id].status is OrderStatus.PAYMENT_PENDING


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tentativa_ativa_pendente_devolve_a_existente() -> None:
    """Cobrança já confirmada pelo provider: devolve, não cria outra."""
    world = AgentWorld()
    executor = _executor(world)
    state = await _confirmed(world, executor, RECHARGE_AMOUNT)

    primeira = await executor.execute(
        state=state, tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR
    )
    assert primeira.result.ok is True
    assert primeira.result.data["status"] == PaymentStatus.PENDING.value

    segunda = await executor.execute(
        state=primeira.state, tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR
    )
    assert segunda.result.ok is True
    assert segunda.result.data["already_existed"] is True
    assert segunda.result.data["payment_id"] == primeira.result.data["payment_id"]
    assert world.provider.create_calls == 1
    assert len(world.store.state.payments) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_terminal_nao_aprovado_permite_nova_tentativa_com_nova_key() -> None:
    """§13.2: Payment rejeitado devolve o Order a `CONFIRMED` e libera nova tentativa."""
    world = AgentWorld()
    executor = _executor(world)
    state = await _confirmed(world, executor, RECHARGE_AMOUNT)

    primeira = await executor.execute(
        state=state, tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR
    )
    payment_id = uuid.UUID(str(primeira.result.data["payment_id"]))
    order_id = uuid.UUID(str(primeira.result.data["order_id"]))

    # O provider recusa; o backend aplica o estado terminal.
    charge_id = world.provider.charge_id_for_key(
        IdempotencyKeyPolicy.create_payment(order_id, previous_terminal_payment_id=None)
    )
    assert charge_id is not None
    world.provider.settle(charge_id, PaymentStatus.REJECTED)
    await world.services.payments.reconcile_payment(payment_id=payment_id)

    assert world.store.state.payments[payment_id].status is PaymentStatus.REJECTED
    assert world.store.state.orders[order_id].status is OrderStatus.CONFIRMED

    segunda = await executor.execute(
        state=primeira.state, tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR
    )
    assert segunda.result.ok is True
    novo_id = uuid.UUID(str(segunda.result.data["payment_id"]))
    assert novo_id != payment_id
    assert (
        OPERATION_CREATE_PAYMENT,
        IdempotencyKeyPolicy.create_payment(order_id, previous_terminal_payment_id=payment_id),
    ) in world.store.state.idempotency


@pytest.mark.unit
@pytest.mark.asyncio
async def test_order_ja_pago_nao_gera_nova_cobranca() -> None:
    world = AgentWorld()
    executor = _executor(world)
    state = await _confirmed(world, executor, RECHARGE_AMOUNT)

    primeira = await executor.execute(
        state=state, tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR
    )
    payment_id = uuid.UUID(str(primeira.result.data["payment_id"]))
    order_id = uuid.UUID(str(primeira.result.data["order_id"]))

    charge_id = world.provider.charge_id_for_key(
        IdempotencyKeyPolicy.create_payment(order_id, previous_terminal_payment_id=None)
    )
    assert charge_id is not None
    world.provider.settle(charge_id, PaymentStatus.APPROVED)
    await world.services.payments.reconcile_payment(payment_id=payment_id)
    assert world.store.state.orders[order_id].status is OrderStatus.PAID

    outcome = await executor.execute(
        state=primeira.state, tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.ok is False
    assert outcome.result.code == "PAYMENT_ALREADY_APPROVED"
    assert outcome.result.next_action is NextAction.CHECK_FULFILLMENT
    assert len(world.store.state.payments) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_status_de_pagamento_e_leitura_pura() -> None:
    """A consulta não fala com o provider e não escreve nada."""
    world = AgentWorld()
    executor = _executor(world)
    state = await _confirmed(world, executor, RECHARGE_AMOUNT)
    outcome = await executor.execute(
        state=state, tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR
    )
    order_id = str(outcome.result.data["order_id"])
    lookups_antes = world.provider.lookup_calls

    consulta = await executor.execute(
        state=outcome.state, tool_name="get_payment_status", arguments={"order_id": order_id}
    )
    assert consulta.result.ok is True
    assert consulta.result.data["has_active_attempt"] is True
    assert world.provider.lookup_calls == lookups_antes
    assert len(world.store.state.payments) == 1


# --- apoio --------------------------------------------------------------------


async def _quote_and_order(
    world: AgentWorld, executor: ToolExecutor, amount: Decimal
) -> ConversationState:
    state = world.state()
    outcome = await executor.execute(
        state=state,
        tool_name="create_recharge_quote",
        arguments={"card_id": str(world.card.id), "amount": str(amount)},
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.ok is True, outcome.result
    outcome = await executor.execute(
        state=outcome.state, tool_name="create_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.ok is True, outcome.result
    return outcome.state


async def _confirmed(
    world: AgentWorld, executor: ToolExecutor, amount: Decimal
) -> ConversationState:
    state = await _quote_and_order(world, executor, amount)
    outcome = await executor.execute(
        state=state, tool_name="confirm_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.ok is True, outcome.result
    return outcome.state
