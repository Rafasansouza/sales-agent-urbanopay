"""Aplicador monotônico de estado de Payment (SPEC-003 §9, §12).

Cobre a regra que impede o efeito financeiro mais perigoso da integração:
um evento fora de ordem transformando estado terminal em aprovado.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from tests.unit.orders_payments.builders import FIXED_NOW, make_payment
from urbanopay.modules.payments.domain.entities import (
    ACTIVE_PAYMENT_STATUSES,
    TERMINAL_PAYMENT_STATUSES,
)
from urbanopay.modules.payments.domain.enums import PaymentStatus
from urbanopay.modules.payments.domain.state_machine import (
    ApplicationOutcome,
    apply_provider_status,
)

LATER = FIXED_NOW + timedelta(minutes=1)
ORDER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")

TERMINAIS = sorted(TERMINAL_PAYMENT_STATUSES, key=lambda status: status.value)
NAO_APROVADOS = [status for status in TERMINAIS if status is not PaymentStatus.APPROVED]


# --- enum (§9) -----------------------------------------------------------


@pytest.mark.unit
def test_enum_tem_exatamente_os_sete_estados() -> None:
    assert {status.value for status in PaymentStatus} == {
        "CREATED",
        "PENDING",
        "APPROVED",
        "REJECTED",
        "CANCELLED",
        "EXPIRED",
        "FAILED",
    }


@pytest.mark.unit
def test_nao_existe_estado_unknown() -> None:
    """Incerteza não é estado persistido: é `CREATED` + `PAYMENT_STATUS_UNKNOWN`."""
    assert "UNKNOWN" not in {status.value for status in PaymentStatus}


@pytest.mark.unit
def test_classificacao_de_ativo_e_terminal() -> None:
    assert {PaymentStatus.CREATED, PaymentStatus.PENDING} == ACTIVE_PAYMENT_STATUSES
    assert {
        PaymentStatus.APPROVED,
        PaymentStatus.REJECTED,
        PaymentStatus.CANCELLED,
        PaymentStatus.EXPIRED,
        PaymentStatus.FAILED,
    } == TERMINAL_PAYMENT_STATUSES
    # Nenhum estado é ativo e terminal ao mesmo tempo.
    assert not (ACTIVE_PAYMENT_STATUSES & TERMINAL_PAYMENT_STATUSES)


# --- progressões válidas -------------------------------------------------


@pytest.mark.unit
def test_created_progride_para_pending() -> None:
    payment = make_payment(order_id=ORDER_ID, status=PaymentStatus.CREATED)
    resultado = apply_provider_status(
        payment, PaymentStatus.PENDING, LATER, provider_payment_id="ext-1"
    )

    assert resultado.outcome is ApplicationOutcome.APPLIED
    assert resultado.changed is True
    assert resultado.payment.status is PaymentStatus.PENDING
    assert resultado.payment.provider_payment_id == "ext-1"
    assert resultado.payment.updated_at == LATER


@pytest.mark.unit
@pytest.mark.parametrize("terminal", TERMINAIS)
def test_created_progride_para_qualquer_terminal(terminal: PaymentStatus) -> None:
    payment = make_payment(order_id=ORDER_ID, status=PaymentStatus.CREATED)
    resultado = apply_provider_status(payment, terminal, LATER)

    assert resultado.changed is True
    assert resultado.payment.status is terminal


@pytest.mark.unit
@pytest.mark.parametrize("terminal", TERMINAIS)
def test_pending_progride_para_qualquer_terminal(terminal: PaymentStatus) -> None:
    payment = make_payment(order_id=ORDER_ID, status=PaymentStatus.PENDING)
    resultado = apply_provider_status(payment, terminal, LATER)

    assert resultado.changed is True
    assert resultado.payment.status is terminal


# --- monotonicidade ------------------------------------------------------


@pytest.mark.unit
def test_pending_nao_regride_para_created() -> None:
    payment = make_payment(order_id=ORDER_ID, status=PaymentStatus.PENDING)
    resultado = apply_provider_status(payment, PaymentStatus.CREATED, LATER)

    assert resultado.outcome is ApplicationOutcome.IGNORED_NOT_MONOTONIC
    assert resultado.changed is False
    assert resultado.payment.status is PaymentStatus.PENDING


@pytest.mark.unit
@pytest.mark.parametrize("atual", TERMINAIS)
@pytest.mark.parametrize("reportado", [PaymentStatus.CREATED, PaymentStatus.PENDING])
def test_terminal_nunca_regride(atual: PaymentStatus, reportado: PaymentStatus) -> None:
    payment = make_payment(order_id=ORDER_ID, status=atual)
    resultado = apply_provider_status(payment, reportado, LATER)

    assert resultado.outcome is ApplicationOutcome.IGNORED_TERMINAL
    assert resultado.payment.status is atual


@pytest.mark.unit
def test_terminal_nao_e_substituido_por_outro_terminal() -> None:
    """Evento fora de ordem não troca um desfecho por outro."""
    payment = make_payment(order_id=ORDER_ID, status=PaymentStatus.REJECTED)
    resultado = apply_provider_status(payment, PaymentStatus.EXPIRED, LATER)

    assert resultado.outcome is ApplicationOutcome.IGNORED_TERMINAL
    assert resultado.payment.status is PaymentStatus.REJECTED


@pytest.mark.unit
def test_aprovado_nao_e_derrubado_por_recusa_atrasada() -> None:
    """O caso oposto também é protegido: `APPROVED` não vira `REJECTED`."""
    payment = make_payment(order_id=ORDER_ID, status=PaymentStatus.APPROVED)
    resultado = apply_provider_status(payment, PaymentStatus.REJECTED, LATER)

    assert resultado.changed is False
    assert resultado.payment.status is PaymentStatus.APPROVED
    assert resultado.requires_reconciliation is False


# --- reconciliação -------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("atual", NAO_APROVADOS)
def test_aprovado_sobre_terminal_nao_aprovado_pede_reconciliacao(
    atual: PaymentStatus,
) -> None:
    """Pode haver dinheiro recebido sem `Order PAID` — nunca resolver sozinho.

    Aplicar o `APPROVED` automaticamente seria exatamente o caminho que
    produz efeito financeiro indevido a partir de evento fora de ordem. O
    aplicador ignora e sinaliza.
    """
    payment = make_payment(order_id=ORDER_ID, status=atual)
    resultado = apply_provider_status(payment, PaymentStatus.APPROVED, LATER)

    assert resultado.outcome is ApplicationOutcome.IGNORED_TERMINAL
    assert resultado.changed is False
    assert resultado.requires_reconciliation is True
    assert resultado.payment.status is atual


# --- repetição do mesmo fato ---------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("status", list(PaymentStatus))
def test_mesmo_status_e_duplicata_sem_mudanca(status: PaymentStatus) -> None:
    payment = make_payment(order_id=ORDER_ID, status=status, provider_payment_id="ext-1")
    resultado = apply_provider_status(payment, status, LATER, provider_payment_id="ext-1")

    assert resultado.outcome is ApplicationOutcome.DUPLICATE
    assert resultado.changed is False
    assert resultado.payment is payment


@pytest.mark.unit
def test_identificador_externo_aprendido_na_repeticao_e_registrado() -> None:
    """Timeout na criação pode trazer o identificador só depois (§9.1)."""
    payment = make_payment(
        order_id=ORDER_ID, status=PaymentStatus.CREATED, provider_payment_id=None
    )
    resultado = apply_provider_status(
        payment, PaymentStatus.CREATED, LATER, provider_payment_id="ext-9"
    )

    assert resultado.outcome is ApplicationOutcome.APPLIED
    assert resultado.payment.status is PaymentStatus.CREATED
    assert resultado.payment.provider_payment_id == "ext-9"


@pytest.mark.unit
def test_identificador_externo_nao_e_apagado() -> None:
    payment = make_payment(
        order_id=ORDER_ID, status=PaymentStatus.CREATED, provider_payment_id="ext-1"
    )
    resultado = apply_provider_status(
        payment, PaymentStatus.PENDING, LATER, provider_payment_id=None
    )

    assert resultado.payment.provider_payment_id == "ext-1"
