"""Estado como cache e tradução de erro em comportamento (SPEC-004 §3.1, §18).

Duas propriedades:

1. o estado guarda **referências**, e nada que possa ficar obsoleto vira
   decisão — o valor apresentado é explicitamente não autoritativo;
2. todo erro conhecido dos módulos tem comportamento conversacional definido,
   e o desconhecido nunca vira sucesso.
"""

from __future__ import annotations

import uuid
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.unit.agent.world import ABOVE_APPROVAL_THRESHOLD, RECHARGE_AMOUNT, AgentWorld
from urbanopay.core.idempotency import IdempotencyConflictError
from urbanopay.modules.agent.application.error_mapping import map_domain_error
from urbanopay.modules.agent.application.executor import ToolExecutor
from urbanopay.modules.agent.domain.catalog import ToolCaller
from urbanopay.modules.agent.domain.conversation import (
    SENSITIVE_INPUT_PHASES,
    ConversationPhase,
    ConversationState,
    PendingConfirmation,
    new_conversation,
)
from urbanopay.modules.agent.domain.results import GuardCode, NextAction
from urbanopay.modules.cards.domain.errors import CardNotAccessibleError, CardNotActiveError
from urbanopay.modules.fare.domain.errors import EmptyTripError, UnsupportedTripCompositionError
from urbanopay.modules.fulfillment.domain.errors import (
    EffectConflictError,
    OrderNotPaidError,
    ReceiptNotAvailableError,
    ReconciliationRequiredError,
)
from urbanopay.modules.identity.domain.errors import NotAuthenticatedError, SessionExpiredError
from urbanopay.modules.orders.domain.errors import (
    InvalidRechargeAmountError,
    OrderExpiredError,
    UnsupportedOperationTypeError,
)
from urbanopay.modules.payments.domain.errors import (
    PaymentAlreadyApprovedError,
    PaymentProviderTimeoutError,
    PaymentStatusUnknownError,
)

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


def _executor(world: AgentWorld) -> ToolExecutor:
    return ToolExecutor(world.services, clock=lambda: FIXED_NOW)


# --- estado: só referência ----------------------------------------------------

# SPEC-004 §3.1: nada aqui pode ficar obsoleto e virar decisão.
FORBIDDEN_STATE_FIELDS = frozenset(
    {
        "balance",
        "fare_profile",
        "order_status",
        "payment_status",
        "approval_status",
        "fulfillment_status",
        "card_status",
        "requires_approval",
        "authenticated",
        "customer_id",
        "document",
        "cpf",
        "otp",
        "challenge_id",
    }
)


@pytest.mark.unit
def test_estado_nao_guarda_autoridade_de_negocio() -> None:
    """O estado é cache de orquestração — saldo e status vêm do backend."""
    names = {field.name for field in fields(ConversationState)}
    assert names.isdisjoint(FORBIDDEN_STATE_FIELDS)
    assert names == {
        "conversation_id",
        "session_id",
        "phase",
        "selected_card_id",
        "current_quote_id",
        "current_order_id",
        "current_payment_id",
        "pending_confirmation",
        "tool_calls_this_turn",
        "last_tool",
        "last_code",
    }


@pytest.mark.unit
def test_confirmacao_pendente_guarda_valor_apenas_para_exibicao() -> None:
    """O total apresentado é string de exibição, nunca insumo de decisão."""
    names = {field.name for field in fields(PendingConfirmation)}
    assert names == {"order_id", "display_total", "presented_at"}
    pending = PendingConfirmation(
        order_id=uuid.uuid4(), display_total="100.00", presented_at=FIXED_NOW
    )
    assert isinstance(pending.display_total, str)
    assert pending.binds(pending.order_id)
    assert not pending.binds(uuid.uuid4())


@pytest.mark.unit
def test_fases_de_entrada_sensivel_sao_declaradas() -> None:
    """§13.1: as fases em que a mensagem carrega CPF/OTP são explícitas."""
    assert {
        ConversationPhase.AWAITING_DOCUMENT,
        ConversationPhase.AWAITING_OTP,
    } == SENSITIVE_INPUT_PHASES


@pytest.mark.unit
def test_conversa_nova_comeca_anonima_e_vazia() -> None:
    session_id = uuid.uuid4()
    state = new_conversation(session_id)
    assert state.session_id == session_id
    assert state.phase is ConversationPhase.DISCOVERY
    assert state.pending_confirmation is None
    assert state.current_order_id is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_jornada_avanca_as_fases_e_o_contexto() -> None:
    """A transição de estado é derivada do resultado, num único lugar."""
    world = AgentWorld()
    executor = _executor(world)

    outcome = await executor.execute(
        state=world.state(),
        tool_name="create_recharge_quote",
        arguments={"card_id": str(world.card.id), "amount": str(RECHARGE_AMOUNT)},
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.state.phase is ConversationPhase.QUOTE
    assert outcome.state.current_quote_id is not None
    assert outcome.state.selected_card_id == world.card.id

    outcome = await executor.execute(
        state=outcome.state, tool_name="create_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.state.phase is ConversationPhase.ORDER_CONFIRMATION
    pending = outcome.state.pending_confirmation
    assert pending is not None
    assert pending.display_total == "100.00"
    assert pending.presented_at == FIXED_NOW

    outcome = await executor.execute(
        state=outcome.state, tool_name="confirm_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.state.phase is ConversationPhase.PAYMENT
    assert outcome.state.pending_confirmation is None
    assert outcome.state.current_order_id == pending.order_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acima_do_limiar_a_fase_para_em_aprovacao() -> None:
    """> R$ 200,00: `REQUIRES_APPROVAL` encerra a automação financeira (§9)."""
    world = AgentWorld()
    executor = _executor(world)

    outcome = await executor.execute(
        state=world.state(),
        tool_name="create_recharge_quote",
        arguments={"card_id": str(world.card.id), "amount": str(ABOVE_APPROVAL_THRESHOLD)},
        caller=ToolCaller.ORCHESTRATOR,
    )
    outcome = await executor.execute(
        state=outcome.state, tool_name="create_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.data["requires_approval"] is True
    assert outcome.result.next_action is NextAction.CONFIRM_ORDER

    outcome = await executor.execute(
        state=outcome.state, tool_name="confirm_order", caller=ToolCaller.ORCHESTRATOR
    )
    assert outcome.result.data["status"] == "REQUIRES_APPROVAL"
    assert outcome.result.next_action is NextAction.AWAIT_HUMAN_APPROVAL
    assert outcome.state.phase is ConversationPhase.APPROVAL

    # A consulta de aprovação confirma a pendência — e é só leitura.
    order_id = str(outcome.result.data["order_id"])
    consulta = await executor.execute(
        state=outcome.state.begin_turn(),
        tool_name="get_approval_status",
        arguments={"order_id": order_id},
    )
    assert consulta.result.data["approval_status"] == "PENDING"
    assert consulta.result.next_action is NextAction.AWAIT_HUMAN_APPROVAL
    assert not world.store.state.payments


@pytest.mark.unit
@pytest.mark.asyncio
async def test_falha_nao_move_o_estado() -> None:
    """Uma recusa não seleciona cartão, não abre confirmação e não avança fase."""
    world = AgentWorld()
    outcome = await _executor(world).execute(
        state=world.state(),
        tool_name="create_recharge_quote",
        arguments={"card_id": str(world.card.id), "amount": "nao-e-numero"},
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.ok is False
    assert outcome.result.code == "INVALID_RECHARGE_AMOUNT"
    assert outcome.state.phase is ConversationPhase.DISCOVERY
    assert outcome.state.current_quote_id is None
    assert outcome.state.selected_card_id is None
    assert outcome.state.tool_calls_this_turn == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cartao_nao_ativo_nao_e_selecionado() -> None:
    """Consultar um cartão bloqueado não o torna o cartão da jornada."""
    from tests.unit.cards.fakes import make_card
    from tests.unit.identity.fakes import make_customer
    from urbanopay.modules.cards.domain.enums import CardStatus

    customer = make_customer()
    bloqueado = make_card(customer_id=customer.id, status=CardStatus.BLOCKED)
    world = AgentWorld(customer=customer, cards=[bloqueado])

    outcome = await _executor(world).execute(
        state=world.state(),
        tool_name="get_card_details",
        arguments={"card_id": str(bloqueado.id)},
    )
    assert outcome.result.ok is True
    assert outcome.result.data["status"] == "BLOCKED"
    assert outcome.state.selected_card_id is None


# --- tradução de erro ---------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "code", "next_action"),
    [
        (NotAuthenticatedError(), "NOT_AUTHENTICATED", NextAction.AUTHENTICATE),
        (SessionExpiredError(), "SESSION_EXPIRED", NextAction.AUTHENTICATE),
        (CardNotAccessibleError(), "CARD_NOT_ACCESSIBLE", NextAction.SELECT_CARD),
        (CardNotActiveError(), "CARD_NOT_ACTIVE", NextAction.SELECT_CARD),
        (EmptyTripError(), "EMPTY_TRIP", NextAction.ASK_TRIP),
        (
            UnsupportedTripCompositionError(),
            "UNSUPPORTED_TRIP_COMPOSITION",
            NextAction.ASK_TRIP,
        ),
        (InvalidRechargeAmountError(), "INVALID_RECHARGE_AMOUNT", NextAction.ASK_AMOUNT),
        (OrderExpiredError(), "ORDER_EXPIRED", NextAction.RECREATE_ORDER),
        (
            UnsupportedOperationTypeError(),
            "UNSUPPORTED_OPERATION_TYPE",
            NextAction.STOP,
        ),
        (
            PaymentStatusUnknownError(),
            "PAYMENT_STATUS_UNKNOWN",
            NextAction.WAIT_RECONCILIATION,
        ),
        (
            PaymentProviderTimeoutError(),
            "PAYMENT_STATUS_UNKNOWN",
            NextAction.WAIT_RECONCILIATION,
        ),
        (
            PaymentAlreadyApprovedError(),
            "PAYMENT_ALREADY_APPROVED",
            NextAction.CHECK_FULFILLMENT,
        ),
        (OrderNotPaidError(), "ORDER_NOT_PAID", NextAction.AWAIT_PAYMENT),
        (
            ReconciliationRequiredError(),
            "RECONCILIATION_REQUIRED",
            NextAction.HUMAN_REVIEW,
        ),
        (EffectConflictError(), "EFFECT_CONFLICT", NextAction.HUMAN_REVIEW),
        (ReceiptNotAvailableError(), "RECEIPT_NOT_AVAILABLE", NextAction.WAIT),
        (IdempotencyConflictError(), "IDEMPOTENCY_CONFLICT", NextAction.STOP),
    ],
)
def test_erro_de_dominio_tem_comportamento_definido(
    error: Exception, code: str, next_action: NextAction
) -> None:
    """SPEC-004 §18: cada erro conhecido vira uma conduta explícita."""
    mapped = map_domain_error(error)
    assert mapped == (code, next_action)


@pytest.mark.unit
def test_reconciliacao_e_conflito_param_a_automacao() -> None:
    """§11: evidência inconsistente exige gente, não retentativa."""
    for error in (ReconciliationRequiredError(), EffectConflictError()):
        mapped = map_domain_error(error)
        assert mapped is not None
        assert mapped[1] is NextAction.HUMAN_REVIEW


@pytest.mark.unit
@pytest.mark.parametrize(
    "error", [RuntimeError("falha inesperada"), ValueError("dado interno"), KeyError("x")]
)
def test_excecao_desconhecida_nao_e_mapeada(error: Exception) -> None:
    assert map_domain_error(error) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_excecao_desconhecida_vira_internal_error_sanitizado() -> None:
    """§20: desconhecida nunca vira sucesso, e a mensagem não vaza."""

    class ExplodingCards:
        async def list_for_customer(self, customer_id: uuid.UUID) -> list[object]:
            raise RuntimeError(f"detalhe interno sensivel {customer_id}")

        async def get_owned(self, customer_id: uuid.UUID, card_id: uuid.UUID) -> None:
            raise RuntimeError("detalhe interno sensivel")

    from dataclasses import replace

    from urbanopay.modules.cards.application.services import CardService

    world = AgentWorld()
    services = replace(world.services, cards=CardService(ExplodingCards()))  # type: ignore[arg-type]
    executor = ToolExecutor(services, clock=lambda: FIXED_NOW)

    outcome = await executor.execute(state=world.state(), tool_name="get_customer_cards")
    assert outcome.result.ok is False
    assert outcome.result.code == GuardCode.INTERNAL_ERROR.value
    assert outcome.result.next_action is NextAction.STOP
    assert outcome.result.data == {}


@pytest.mark.unit
def test_valor_monetario_nunca_e_float_no_contrato() -> None:
    """ADR-012: `float` é proibido em qualquer ponto do caminho do dinheiro."""
    assert isinstance(RECHARGE_AMOUNT, Decimal)
    assert isinstance(ABOVE_APPROVAL_THRESHOLD, Decimal)
