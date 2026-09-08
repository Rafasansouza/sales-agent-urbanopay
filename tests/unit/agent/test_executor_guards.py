"""Guardas do executor: visibilidade, autenticação, contexto e limites.

Prova a propriedade central da Etapa 1: **uma recusa não chega ao serviço.**
Não basta o envelope dizer "não"; o domínio não pode ter sido tocado. Por isso
vários testes verificam o estado do mundo depois da recusa, e não só o código
devolvido.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from tests.unit.agent.world import AgentWorld, other_customer_card
from urbanopay.modules.agent.application.executor import (
    DEFAULT_MAX_TOOL_CALLS_PER_TURN,
    ToolExecutor,
)
from urbanopay.modules.agent.domain.catalog import ToolCaller
from urbanopay.modules.agent.domain.conversation import (
    ConversationState,
    PendingConfirmation,
)
from urbanopay.modules.agent.domain.results import GuardCode, NextAction, ResultType

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


def _executor(world: AgentWorld, **kwargs: int) -> ToolExecutor:
    return ToolExecutor(world.services, clock=lambda: FIXED_NOW, **kwargs)


# --- visibilidade -------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name",
    ["create_order", "confirm_order", "create_payment", "create_recharge_quote"],
)
async def test_llm_nao_executa_graph_only(tool_name: str) -> None:
    world = AgentWorld()
    outcome = await _executor(world).execute(
        state=world.state(), tool_name=tool_name, caller=ToolCaller.LLM
    )
    assert outcome.result.ok is False
    assert outcome.result.code == GuardCode.TOOL_NOT_AUTHORIZED.value
    assert not world.store.state.orders
    assert not world.store.state.quotes


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["start_authentication", "verify_otp"])
async def test_llm_nao_executa_sensitive_input(tool_name: str) -> None:
    """CPF e OTP não são oferecidos ao modelo como argumento de tool (§13.1)."""
    world = AgentWorld(authenticated=False)
    outcome = await _executor(world).execute(
        state=world.state(),
        tool_name=tool_name,
        arguments={"document": "11122233344", "otp": "123456"},
        caller=ToolCaller.LLM,
    )
    assert outcome.result.code == GuardCode.TOOL_NOT_AUTHORIZED.value
    assert not world.identity_uow.challenge_store


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name",
    [
        "approve_order",
        "reject_order",
        "fulfill_order",
        "reconcile_payment",
        "process_payment_webhook",
        "set_payment_status",
        "set_balance",
        "set_fare_profile",
        "apply_recharge",
        "issue_ticket",
        "execute_sql",
        "get_otp",
    ],
)
async def test_tool_proibida_nunca_executa(tool_name: str) -> None:
    """Nem o orquestrador determinístico alcança `BACKEND_ONLY`."""
    world = AgentWorld()
    outcome = await _executor(world).execute(
        state=world.state(),
        tool_name=tool_name,
        arguments={"order_id": str(uuid.uuid4())},
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.ok is False
    assert outcome.result.code == GuardCode.TOOL_NOT_AUTHORIZED.value
    assert outcome.result.next_action is NextAction.STOP


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "blocker"),
    [
        ("search_products", "A-05"),
        ("get_product", "A-05"),
        ("get_ticket", "A-05"),
        ("calculate_usage_cost", "A-06"),
    ],
)
async def test_tool_indisponivel_recusa_nomeando_o_bloqueio(tool_name: str, blocker: str) -> None:
    """A-05/A-06: recusa honesta, nunca tool fictícia (SPEC-004 §7.3).

    `TOOL_UNAVAILABLE` é distinto de `TOOL_NOT_AUTHORIZED` de propósito: a
    capacidade foi prometida pela SPEC e está bloqueada por decisão pendente,
    o que é diferente de nunca ter existido.
    """
    world = AgentWorld()
    outcome = await _executor(world).execute(
        state=world.state(), tool_name=tool_name, caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.code == GuardCode.TOOL_UNAVAILABLE.value
    assert outcome.result.ok is False
    del blocker  # o bloqueio é nomeado no log, não no envelope do modelo


# --- autenticação -------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("get_customer_cards", {}),
        ("get_card_balance", {"card_id": str(uuid.uuid4())}),
        ("get_order", {"order_id": str(uuid.uuid4())}),
        ("get_payment_status", {"order_id": str(uuid.uuid4())}),
        ("get_receipt", {"order_id": str(uuid.uuid4())}),
    ],
)
async def test_sessao_anonima_nao_alcanca_tool_protegida(
    tool_name: str, arguments: dict[str, str]
) -> None:
    """Matriz de SPEC-002 §9: anônimo não lista cartão nem consulta pedido."""
    world = AgentWorld(authenticated=False)
    outcome = await _executor(world).execute(
        state=world.state(), tool_name=tool_name, arguments=arguments
    )
    assert outcome.result.ok is False
    assert outcome.result.code == "NOT_AUTHENTICATED"
    assert outcome.result.next_action is NextAction.AUTHENTICATE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sessao_expirada_interrompe_a_jornada() -> None:
    world = AgentWorld()
    world.expire_session()
    outcome = await _executor(world).execute(state=world.state(), tool_name="get_customer_cards")
    assert outcome.result.code == "SESSION_EXPIRED"
    assert outcome.result.next_action is NextAction.AUTHENTICATE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_simulacao_tarifaria_funciona_anonima() -> None:
    """PRD RF-05: simular tarifa antes da autenticação."""
    world = AgentWorld(authenticated=False)
    outcome = await _executor(world).execute(
        state=world.state(),
        tool_name="calculate_trip_fare",
        arguments={
            "segments": [{"mode": "BUS", "line_code": "101"}],
            "declared_fare_profile": "INTEGRAL",
        },
    )
    assert outcome.result.ok is True
    assert outcome.result.data["total"] == "6.00"
    assert outcome.result.data["profile_source"] == "USER_DECLARED"
    assert outcome.result.data["profile_verified"] is False


# --- titularidade -------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cartao_de_outro_cliente_e_indistinguivel_de_inexistente() -> None:
    """SPEC-002 §5: `CARD_NOT_ACCESSIBLE` sem revelar existência."""
    alheio = other_customer_card()
    world = AgentWorld(extra_cards=[alheio])

    executor = _executor(world)
    do_terceiro = await executor.execute(
        state=world.state(), tool_name="get_card_balance", arguments={"card_id": str(alheio.id)}
    )
    inexistente = await executor.execute(
        state=world.state(),
        tool_name="get_card_balance",
        arguments={"card_id": str(uuid.uuid4())},
    )
    assert do_terceiro.result.code == inexistente.result.code == "CARD_NOT_ACCESSIBLE"
    assert do_terceiro.result.data == inexistente.result.data == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_identificador_malformado_responde_como_inacessivel() -> None:
    """Falha estrutural traduz para código existente (SPEC-004 §20).

    Um `card_id` que não é UUID e um cartão de terceiro devem ser
    indistinguíveis: a mensagem de erro não é canal de enumeração.
    """
    world = AgentWorld()
    outcome = await _executor(world).execute(
        state=world.state(), tool_name="get_card_balance", arguments={"card_id": "nao-e-uuid"}
    )
    assert outcome.result.code == "CARD_NOT_ACCESSIBLE"
    assert outcome.result.next_action is NextAction.SELECT_CARD


@pytest.mark.unit
@pytest.mark.asyncio
async def test_argumento_extra_e_recusado() -> None:
    """Campo não declarado é recusado, nunca ignorado."""
    world = AgentWorld()
    outcome = await _executor(world).execute(
        state=world.state(),
        tool_name="get_card_balance",
        arguments={"card_id": str(world.card.id), "balance": "999.00"},
    )
    assert outcome.result.ok is False
    assert outcome.result.code == "CARD_NOT_ACCESSIBLE"


# --- contexto de confirmação (§9.1) ------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sim_sem_confirmacao_pendente_nao_confirma_nada() -> None:
    """Um `sim` fora de contexto: `NO_PENDING_CONFIRMATION`, zero efeito."""
    world = AgentWorld()
    outcome = await _executor(world).execute(
        state=world.state(), tool_name="confirm_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.code == GuardCode.NO_PENDING_CONFIRMATION.value
    assert outcome.result.next_action is NextAction.STOP
    assert not world.store.state.orders
    assert not world.store.state.idempotency


@pytest.mark.unit
@pytest.mark.asyncio
async def test_confirmar_outra_order_e_recusado() -> None:
    """Confirmação vinculada: outra Order ⇒ `CONFIRMATION_CONTEXT_MISMATCH`."""
    world = AgentWorld()
    pendente = uuid.uuid4()
    state = world.state().awaiting_confirmation(
        PendingConfirmation(order_id=pendente, display_total="100.00", presented_at=FIXED_NOW)
    )
    outcome = await _executor(world).execute(
        state=state,
        tool_name="confirm_order",
        arguments={"order_id": str(uuid.uuid4())},
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.code == GuardCode.CONFIRMATION_CONTEXT_MISMATCH.value
    assert not world.store.state.idempotency


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pagamento_sem_order_no_contexto_e_recusado() -> None:
    """`create_payment` exige contexto comercial confirmado (§9.1)."""
    world = AgentWorld()
    outcome = await _executor(world).execute(
        state=world.state(), tool_name="create_payment", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.code == GuardCode.NO_PENDING_CONFIRMATION.value
    assert not world.store.state.payments
    assert world.provider.create_calls == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pagar_outra_order_e_recusado() -> None:
    world = AgentWorld()
    state = ConversationState(
        conversation_id=uuid.uuid4(),
        session_id=world.session.id,
        current_order_id=uuid.uuid4(),
    )
    outcome = await _executor(world).execute(
        state=state,
        tool_name="create_payment",
        arguments={"order_id": str(uuid.uuid4())},
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.code == GuardCode.CONFIRMATION_CONTEXT_MISMATCH.value
    assert world.provider.create_calls == 0


# --- limites ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_limite_de_tool_calls_por_turno() -> None:
    """SPEC-004 §14: o teto contém laço, inclusive laço de chamadas que falham."""
    world = AgentWorld()
    executor = _executor(world, max_tool_calls_per_turn=2)
    state = world.state()

    for _ in range(2):
        outcome = await executor.execute(state=state, tool_name="get_customer_cards")
        state = outcome.state
    assert state.tool_calls_this_turn == 2

    outcome = await executor.execute(state=state, tool_name="get_customer_cards")
    assert outcome.result.code == GuardCode.TOOL_LIMIT_EXCEEDED.value
    assert outcome.result.next_action is NextAction.STOP


@pytest.mark.unit
def test_limite_default_segue_a_sugestao_da_spec() -> None:
    """SPEC-004 §14 sugere até 5 tool calls por turno."""
    assert DEFAULT_MAX_TOOL_CALLS_PER_TURN == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turno_novo_zera_o_contador() -> None:
    world = AgentWorld()
    executor = _executor(world, max_tool_calls_per_turn=1)
    outcome = await executor.execute(state=world.state(), tool_name="get_customer_cards")
    assert outcome.state.tool_calls_this_turn == 1

    outcome = await executor.execute(
        state=outcome.state.begin_turn(), tool_name="get_customer_cards"
    )
    assert outcome.result.ok is True
    assert outcome.result.result_type is ResultType.CARD_LIST
