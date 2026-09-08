"""Envelope e presenters: o que atravessa para o modelo (SPEC-004 §21, §13).

Os presenters são a única passagem de dado de domínio para o lado do modelo.
Testá-los é testar a minimização: cada asserção de campo ausente aqui é uma
categoria de vazamento que não pode acontecer por descuido de um handler.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.unit.agent.world import RECHARGE_AMOUNT, AgentWorld
from tests.unit.cards.fakes import make_card
from tests.unit.identity.fakes import FIXED_OTP, MARIANA_CPF, make_customer
from urbanopay.modules.agent.application import presenters
from urbanopay.modules.agent.application.executor import ToolExecutor
from urbanopay.modules.agent.domain.catalog import ToolCaller
from urbanopay.modules.agent.domain.results import OK_CODE, ResultType, ToolResult
from urbanopay.modules.approvals.domain.enums import ApprovalStatus
from urbanopay.modules.approvals.domain.results import ApprovalDecision
from urbanopay.modules.cards.domain.enums import FareProfile
from urbanopay.modules.fulfillment.domain.entities import Receipt
from urbanopay.modules.fulfillment.domain.enums import DocumentKind
from urbanopay.modules.payments.domain.entities import Payment
from urbanopay.modules.payments.domain.enums import PaymentMethod, PaymentStatus, ProviderName
from urbanopay.modules.payments.domain.results import (
    OrderPaymentStatus,
    PaymentCreationResult,
)

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)

# Segredos fictícios que jamais podem aparecer num envelope.
FORBIDDEN_SUBSTRINGS = (MARIANA_CPF, FIXED_OTP, "secret", "hash")


def _executor(world: AgentWorld) -> ToolExecutor:
    return ToolExecutor(world.services, clock=lambda: FIXED_NOW)


def _payment(order_id: uuid.UUID, status: PaymentStatus) -> Payment:
    return Payment(
        id=uuid.uuid4(),
        order_id=order_id,
        provider=ProviderName.FAKE,
        provider_payment_id="fake-charge-1",
        method=PaymentMethod.PIX,
        amount=Decimal("100.00"),
        currency="BRL",
        status=status,
        idempotency_key="create_payment:x:initial",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


# --- formatação ---------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("21.5"), "21.50"),
        (Decimal("21.50"), "21.50"),
        (Decimal("0"), "0.00"),
        (Decimal("1234.56"), "1234.56"),
    ],
)
def test_dinheiro_sai_como_string_decimal_de_duas_casas(value: Decimal, expected: str) -> None:
    """ADR-006: contrato transporta valor monetário como string decimal."""
    formatted = presenters.money(value)
    assert formatted == expected
    assert isinstance(formatted, str)


@pytest.mark.unit
def test_instante_sai_em_iso_8601() -> None:
    assert presenters.instant(FIXED_NOW) == "2026-09-07T12:00:00+00:00"


@pytest.mark.unit
def test_identificador_sai_como_string_opaca() -> None:
    value = uuid.uuid4()
    assert presenters.opaque(value) == str(value)


# --- minimização --------------------------------------------------------------


@pytest.mark.unit
def test_cartao_sai_mascarado_e_sem_saldo() -> None:
    """SPEC-002 §6: nunca o número completo; saldo tem tool própria."""
    card = make_card(customer_id=uuid.uuid4(), last4="4821", profile=FareProfile.MEIA)
    data = presenters.card(card)
    assert data["masked_number"] == "****4821"
    assert "balance" not in data
    assert "card_last4" not in data
    assert "customer_id" not in data


@pytest.mark.unit
def test_pagamento_nao_expoe_key_nem_referencia_externa() -> None:
    """Nem a idempotency key nem o identificador do provider têm uso conversacional."""
    payment = _payment(uuid.uuid4(), PaymentStatus.PENDING)
    for data in (
        presenters.payment_creation(PaymentCreationResult(payment=payment, qr_code="00020126")),
        presenters.payment_status(OrderPaymentStatus(order_id=payment.order_id, latest=payment)),
    ):
        assert "idempotency_key" not in data
        assert "provider_payment_id" not in data
        assert "provider" not in data


@pytest.mark.unit
def test_aprovacao_nao_expoe_o_ator_da_decisao() -> None:
    """SPEC-003 §7: `decided_by` é trilha de auditoria, não dado de conversa."""
    data = presenters.approval(
        ApprovalDecision(
            order_id=uuid.uuid4(),
            requires_approval=True,
            status=ApprovalStatus.APPROVED,
            requested_at=FIXED_NOW,
            decided_at=FIXED_NOW,
        )
    )
    assert "decided_by" not in data
    assert data["approval_status"] == "APPROVED"


@pytest.mark.unit
def test_comprovante_sai_mascarado_e_qualificado_como_simulado() -> None:
    """SPEC-005 §13.1: o documento é explicitamente não fiscal."""
    receipt = Receipt(
        id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        payment_id=uuid.uuid4(),
        fulfillment_id=uuid.uuid4(),
        card_last4="4821",
        amount=Decimal("100.00"),
        currency="BRL",
        operation_type="RECHARGE",
        document_kind=DocumentKind.SIMULATED_NON_FISCAL,
        disclaimer_version="1",
        issued_at=FIXED_NOW,
    )
    data = presenters.receipt(receipt)
    assert data["masked_card"] == "****4821"
    assert data["document_kind"] == "SIMULATED_NON_FISCAL"
    assert data["disclaimer_version"] == "1"
    assert "card_last4" not in data


@pytest.mark.unit
def test_identificacao_nao_expoe_desafio_nem_documento() -> None:
    from urbanopay.modules.identity.domain.results import (
        IdentificationStatus,
        StartAuthenticationResult,
    )

    data = presenters.start_authentication(
        StartAuthenticationResult(
            status=IdentificationStatus.CUSTOMER_FOUND,
            challenge_id=uuid.uuid4(),
            challenge_expires_at=FIXED_NOW,
        )
    )
    assert "challenge_id" not in data
    assert "document" not in data
    assert set(data) == {"identification_status", "challenge_expires_at"}


@pytest.mark.unit
def test_verificacao_nao_expoe_otp_nem_customer_id() -> None:
    from urbanopay.modules.identity.domain.results import VerificationResult, VerificationStatus

    data = presenters.verification(
        VerificationResult(status=VerificationStatus.AUTHENTICATED, customer_id=uuid.uuid4())
    )
    assert "customer_id" not in data
    assert "otp" not in data
    assert data["authenticated"] is True


# --- o envelope, ponta a ponta ------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_envelope_e_serializavel_e_sem_objeto_de_dominio() -> None:
    """`data` só carrega tipos serializáveis — nunca entidade ou ORM."""
    world = AgentWorld()
    outcome = await _executor(world).execute(state=world.state(), tool_name="get_customer_cards")
    assert outcome.result.ok is True
    assert outcome.result.code == OK_CODE
    assert outcome.result.result_type is ResultType.CARD_LIST
    # Levanta se houver Decimal, UUID, datetime ou dataclass de domínio.
    json.dumps(dict(outcome.result.data), allow_nan=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nenhum_envelope_da_jornada_carrega_pii() -> None:
    """CPF, OTP, hash e segredo não aparecem em nenhum resultado da jornada."""
    customer = make_customer()
    world = AgentWorld(
        customer=customer, cards=[make_card(customer_id=customer.id)], authenticated=False
    )
    executor = _executor(world)
    envelopes: list[ToolResult] = []
    state = world.state()

    outcome = await executor.execute(
        state=state,
        tool_name="start_authentication",
        arguments={"document": MARIANA_CPF},
        caller=ToolCaller.ORCHESTRATOR,
    )
    envelopes.append(outcome.result)
    outcome = await executor.execute(
        state=outcome.state,
        tool_name="verify_otp",
        arguments={"otp": FIXED_OTP},
        caller=ToolCaller.ORCHESTRATOR,
    )
    envelopes.append(outcome.result)
    state = outcome.state

    for tool, arguments in (
        ("get_customer_cards", {}),
        ("get_card_balance", {"card_id": str(world.card.id)}),
    ):
        outcome = await executor.execute(
            state=state.begin_turn(), tool_name=tool, arguments=arguments
        )
        envelopes.append(outcome.result)

    for envelope in envelopes:
        assert envelope.ok is True, envelope
        rendered = json.dumps(dict(envelope.data), ensure_ascii=False).lower()
        for forbidden in FORBIDDEN_SUBSTRINGS:
            assert forbidden.lower() not in rendered, (envelope.result_type, forbidden)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_quote_registra_divergencia_de_perfil_sem_alterar_a_autoridade() -> None:
    """A-11: divergência vira **sinal**, e o perfil oficial permanece o do cartão."""
    customer = make_customer()
    card = make_card(customer_id=customer.id, profile=FareProfile.INTEGRAL)
    world = AgentWorld(customer=customer, cards=[card])

    outcome = await _executor(world).execute(
        state=world.state(),
        tool_name="create_recharge_quote",
        arguments={
            "card_id": str(card.id),
            "amount": str(RECHARGE_AMOUNT),
            "declared_fare_profile": "MEIA",
        },
        caller=ToolCaller.ORCHESTRATOR,
    )
    assert outcome.result.ok is True
    assert outcome.result.data["fare_profile"] == "INTEGRAL"
    assert outcome.result.data["profile_signal"] == "FARE_PROFILE_CHANGED"
    assert outcome.result.data["total"] == "100.00"
