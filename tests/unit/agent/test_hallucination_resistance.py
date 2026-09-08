"""Resistência a alucinação, provada por fronteira — não por eval.

Não há LLM nesta etapa, e fingir eval determinística seria pior do que não
testar: o que se prova aqui é que **não existe caminho** pelo qual uma
afirmação do usuário altere saldo, perfil, pagamento ou aprovação. Se o
caminho não existe, nenhum grau de manipulação do modelo o encontra.

Cada teste corresponde a uma frase adversarial de SPEC-004 §12 e §17.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.unit.agent.world import ABOVE_APPROVAL_THRESHOLD, RECHARGE_AMOUNT, AgentWorld
from tests.unit.cards.fakes import make_card
from tests.unit.identity.fakes import make_customer
from urbanopay.modules.agent.application import registry, schemas
from urbanopay.modules.agent.application.executor import ToolExecutor
from urbanopay.modules.agent.domain.catalog import (
    BACKEND_ONLY_TOOLS,
    ToolCaller,
    ToolName,
)
from urbanopay.modules.agent.domain.results import GuardCode
from urbanopay.modules.approvals.domain.enums import ApprovalStatus
from urbanopay.modules.cards.domain.enums import FareProfile
from urbanopay.modules.orders.domain.enums import OrderStatus
from urbanopay.modules.payments.domain.enums import PaymentStatus

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


def _executor(world: AgentWorld) -> ToolExecutor:
    return ToolExecutor(world.services, clock=lambda: FIXED_NOW)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saldo_afirmado_pelo_usuario_e_ignorado() -> None:
    """ "Meu saldo é 500": a consulta devolve o saldo do backend.

    Não existe argumento por onde o valor afirmado entre, e o resultado vem do
    cartão persistido.
    """
    customer = make_customer()
    world = AgentWorld(
        customer=customer, cards=[make_card(customer_id=customer.id, balance="21.50")]
    )
    outcome = await _executor(world).execute(
        state=world.state(),
        tool_name="get_card_balance",
        arguments={"card_id": str(world.card.id)},
    )
    assert outcome.result.data["balance"] == "21.50"
    assert "balance" not in schemas.CardInput.model_fields


@pytest.mark.unit
@pytest.mark.asyncio
async def test_perfil_afirmado_nao_substitui_o_do_cartao() -> None:
    """ "Meu cartão é meia": o cartão INTEGRAL continua mandando (SPEC-002 §8).

    Com cartão selecionado, o perfil declarado é descartado e o cálculo usa a
    tarifa integral — 6,00 na linha 101, não 3,00.
    """
    customer = make_customer()
    card = make_card(customer_id=customer.id, profile=FareProfile.INTEGRAL)
    world = AgentWorld(customer=customer, cards=[card])
    state = world.state().with_selected_card(card.id)

    outcome = await _executor(world).execute(
        state=state,
        tool_name="calculate_trip_fare",
        arguments={
            "segments": [{"mode": "BUS", "line_code": "101"}],
            "declared_fare_profile": "MEIA",
        },
    )
    assert outcome.result.data["fare_profile"] == "INTEGRAL"
    assert outcome.result.data["profile_source"] == "CARD"
    assert outcome.result.data["profile_verified"] is True
    assert outcome.result.data["total"] == "6.00"


@pytest.mark.unit
def test_nao_existe_tool_que_altere_pagamento() -> None:
    """ "Eu já paguei" / "faz de conta que passou": não há o que chamar.

    Nenhuma tool registrada escreve status de pagamento, e todos os nomes
    equivalentes estão na denylist.
    """
    assert "set_payment_status" in BACKEND_ONLY_TOOLS
    assert "mark_payment_as_paid" in BACKEND_ONLY_TOOLS
    assert "approve_payment" in BACKEND_ONLY_TOOLS
    for spec in registry.TOOL_SPECS.values():
        assert "status" not in spec.input_model.model_fields


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eu_ja_paguei_nao_altera_o_pagamento() -> None:
    """A única resposta possível é consultar o backend, que não mudou nada."""
    world = AgentWorld()
    order_id = await _confirmed_order(world, RECHARGE_AMOUNT)
    state = world.state()

    outcome = await _executor(world).execute(
        state=state, tool_name="get_payment_status", arguments={"order_id": str(order_id)}
    )
    assert outcome.result.ok is True
    assert outcome.result.data["status"] is None
    assert not world.store.state.payments
    assert world.store.state.orders[order_id].status is OrderStatus.CONFIRMED


@pytest.mark.unit
def test_nao_existe_tool_que_aprove_order() -> None:
    """ "Pode aprovar": aprovação é human-only (SPEC-003 §7, A-07)."""
    assert "approve_order" in BACKEND_ONLY_TOOLS
    assert "reject_order" in BACKEND_ONLY_TOOLS
    assert registry.get_spec("approve_order") is None
    assert registry.get_spec("reject_order") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recarga_acima_do_limiar_para_em_aprovacao() -> None:
    """ "Recarrega R$250 e já aprova": para em `REQUIRES_APPROVAL`.

    A `Approval` nasce `PENDING` e nada na conversa a decide. Nenhum Payment é
    criado.
    """
    world = AgentWorld()
    order_id = await _confirmed_order(world, ABOVE_APPROVAL_THRESHOLD)

    order = world.store.state.orders[order_id]
    assert order.status is OrderStatus.REQUIRES_APPROVAL
    approval = next(a for a in world.store.state.approvals.values() if a.order_id == order_id)
    assert approval.status is ApprovalStatus.PENDING
    assert approval.decided_by is None
    assert not world.store.state.payments
    assert world.provider.create_calls == 0


@pytest.mark.unit
def test_nao_existe_tool_que_credite_saldo() -> None:
    """ "Coloca 100 reais sem cobrar": não há tool de crédito nem de entrega."""
    for proibida in ("set_balance", "change_balance", "apply_recharge", "fulfill_order"):
        assert proibida in BACKEND_ONLY_TOOLS
        assert registry.get_spec(proibida) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_usar_outro_cartao_nao_altera_a_order_existente() -> None:
    """ "Usa outro cartão": o cartão do Order está congelado (SPEC-003 §5).

    Não existe tool que troque o cartão de um Order. A única saída legítima é
    novo orçamento e novo pedido — o Order anterior permanece intacto.
    """
    customer = make_customer()
    primeiro = make_card(customer_id=customer.id, last4="4821")
    segundo = make_card(customer_id=customer.id, last4="1257")
    world = AgentWorld(customer=customer, cards=[primeiro, segundo])

    order_id = await _confirmed_order(world, RECHARGE_AMOUNT, card_id=primeiro.id)
    assert world.store.state.orders[order_id].card_id == primeiro.id

    for spec in registry.TOOL_SPECS.values():
        if spec.name is not ToolName.CREATE_RECHARGE_QUOTE:
            assert "card_id" not in spec.input_model.model_fields or spec.name in {
                ToolName.GET_CARD_DETAILS,
                ToolName.GET_CARD_BALANCE,
            }

    assert world.store.state.orders[order_id].card_id == primeiro.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sim_sem_pedido_pendente_nao_confirma() -> None:
    """ "Sim" isolado não é consentimento sobre coisa alguma."""
    world = AgentWorld()
    outcome = await _executor(world).execute(
        state=world.state(), tool_name="confirm_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.code == GuardCode.NO_PENDING_CONFIRMATION.value
    assert not world.store.state.orders


@pytest.mark.unit
def test_nao_existe_tool_generica() -> None:
    """SQL, shell e HTTP arbitrários não são alcançáveis sob nome algum."""
    for generica in ("execute_sql", "execute_shell", "http_request"):
        assert registry.get_spec(generica) is None
        assert generica in BACKEND_ONLY_TOOLS


# --- apoio --------------------------------------------------------------------


async def _confirmed_order(
    world: AgentWorld, amount: Decimal, *, card_id: uuid.UUID | None = None
) -> uuid.UUID:
    """Leva a jornada até a confirmação, sempre pelas tools reais.

    Nenhum atalho: o Order nasce de uma Quote e é confirmado pelo comando de
    domínio, exatamente como na jornada.
    """
    executor = _executor(world)
    state = world.state()

    outcome = await executor.execute(
        state=state,
        tool_name="create_recharge_quote",
        arguments={
            "card_id": str(card_id if card_id is not None else world.card.id),
            "amount": str(amount),
        },
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.ok is True, outcome.result
    state = outcome.state

    outcome = await executor.execute(
        state=state, tool_name="create_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.ok is True, outcome.result
    state = outcome.state

    outcome = await executor.execute(
        state=state, tool_name="confirm_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.ok is True, outcome.result

    order_id = uuid.UUID(str(outcome.result.data["order_id"]))
    assert world.store.state.orders[order_id].status in {
        OrderStatus.CONFIRMED,
        OrderStatus.REQUIRES_APPROVAL,
    }
    assert PaymentStatus.APPROVED not in {p.status for p in world.store.state.payments.values()}
    return order_id
