"""Máquina de estados do Order (SPEC-003 §6, §14).

Cobre o grafo, a autoria de cada transição e — o ponto que a decisão aprovada
exige — a ausência de estado sem caminho válido de entrada.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.unit.orders_payments.builders import FIXED_NOW, make_order
from urbanopay.modules.orders.domain.enums import CancellationReason, OrderStatus
from urbanopay.modules.orders.domain.errors import (
    InvalidOrderStateError,
    InvalidOrderStateTransitionError,
    OrderAlreadyPaidError,
    OrderExpiredError,
    OrderRequiresApprovalError,
)
from urbanopay.modules.orders.domain.state_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    apply_approval_granted,
    apply_approval_rejected,
    cancel_by_customer,
    confirm,
    ensure_transition_allowed,
    expire,
    is_transition_allowed,
    mark_paid,
    release_for_new_attempt,
    start_payment,
)

LATER = FIXED_NOW + timedelta(minutes=1)


# --- estados do enum (§6) ------------------------------------------------


@pytest.mark.unit
def test_enum_nao_possui_approved_nem_failed() -> None:
    """`APPROVED` e `FAILED` foram removidos por não ter caminho de entrada.

    A aprovação vive em `Approval.status`; o pagamento aprovado em
    `Payment.status`. Reintroduzir qualquer um dos dois aqui reabriria o
    conflito C-01 resolvido.
    """
    nomes = {status.name for status in OrderStatus}
    assert "APPROVED" not in nomes
    assert "FAILED" not in nomes


@pytest.mark.unit
def test_enum_tem_exatamente_os_dez_estados_da_spec() -> None:
    assert {status.value for status in OrderStatus} == {
        "DRAFT",
        "REQUIRES_APPROVAL",
        "CONFIRMED",
        "PAYMENT_PENDING",
        "PAID",
        "FULFILLING",
        "COMPLETED",
        "FULFILLMENT_FAILED",
        "CANCELLED",
        "EXPIRED",
    }


@pytest.mark.unit
def test_todo_estado_tem_caminho_valido_de_entrada() -> None:
    """Nenhum estado persistido sem caminho de entrada, exceto o inicial.

    Percorre o grafo a partir de `DRAFT` e exige alcançar todos os demais.
    É este teste que reprovaria a volta de um estado órfão ao enum.
    """
    alcancados = {OrderStatus.DRAFT}
    fronteira = [OrderStatus.DRAFT]
    while fronteira:
        atual = fronteira.pop()
        for destino in ALLOWED_TRANSITIONS[atual]:
            if destino not in alcancados:
                alcancados.add(destino)
                fronteira.append(destino)

    assert alcancados == set(OrderStatus), (
        f"estados inalcançáveis a partir de DRAFT: {set(OrderStatus) - alcancados}"
    )


@pytest.mark.unit
def test_estados_terminais_sao_os_esperados() -> None:
    assert {
        OrderStatus.COMPLETED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    } == TERMINAL_STATUSES
    # PAID não é terminal: segue para fulfillment (SPEC-005).
    assert OrderStatus.PAID not in TERMINAL_STATUSES
    # `FULFILLMENT_FAILED` deixou de ser terminal na implementação da SPEC-005
    # (§5.1): admite reentrada por comando explícito, para que um Order pago
    # cujo cartão foi reativado possa ser concluído. Continua sem qualquer
    # outra saída — em especial, não volta a `PAID` nem a `CONFIRMED`, o que
    # impediria nova cobrança.
    assert ALLOWED_TRANSITIONS[OrderStatus.FULFILLMENT_FAILED] == frozenset(
        {OrderStatus.FULFILLING}
    )


@pytest.mark.unit
def test_grafo_nao_admite_transicao_fora_da_spec() -> None:
    assert not is_transition_allowed(OrderStatus.DRAFT, OrderStatus.PAID)
    assert not is_transition_allowed(OrderStatus.DRAFT, OrderStatus.PAYMENT_PENDING)
    assert not is_transition_allowed(OrderStatus.CANCELLED, OrderStatus.CONFIRMED)
    assert not is_transition_allowed(OrderStatus.EXPIRED, OrderStatus.DRAFT)
    assert not is_transition_allowed(OrderStatus.PAID, OrderStatus.CONFIRMED)

    with pytest.raises(InvalidOrderStateTransitionError):
        ensure_transition_allowed(OrderStatus.DRAFT, OrderStatus.PAID)


# --- confirmação (§8) ----------------------------------------------------


@pytest.mark.unit
def test_confirmacao_sem_aprovacao_vai_para_confirmed() -> None:
    order = make_order(status=OrderStatus.DRAFT, requires_approval=False)
    confirmado = confirm(order, LATER)

    assert confirmado.status is OrderStatus.CONFIRMED
    assert confirmado.updated_at == LATER
    # Entidade imutável: a original não muda.
    assert order.status is OrderStatus.DRAFT


@pytest.mark.unit
def test_confirmacao_com_aprovacao_vai_para_requires_approval() -> None:
    order = make_order(status=OrderStatus.DRAFT, requires_approval=True)
    confirmado = confirm(order, LATER)

    assert confirmado.status is OrderStatus.REQUIRES_APPROVAL


@pytest.mark.unit
def test_draft_expirado_nao_e_confirmavel() -> None:
    order = make_order(status=OrderStatus.DRAFT, expires_at=FIXED_NOW)

    with pytest.raises(OrderExpiredError) as exc:
        confirm(order, FIXED_NOW)
    assert exc.value.code == "ORDER_EXPIRED"


@pytest.mark.unit
@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.CONFIRMED,
        OrderStatus.REQUIRES_APPROVAL,
        OrderStatus.PAYMENT_PENDING,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    ],
)
def test_confirmacao_so_ocorre_a_partir_de_draft(status: OrderStatus) -> None:
    with pytest.raises(InvalidOrderStateError):
        confirm(make_order(status=status), LATER)


# --- cancelamento (§14) --------------------------------------------------


@pytest.mark.unit
def test_cliente_cancela_somente_em_draft() -> None:
    cancelado = cancel_by_customer(make_order(status=OrderStatus.DRAFT), LATER)

    assert cancelado.status is OrderStatus.CANCELLED
    assert cancelado.cancellation_reason is CancellationReason.CUSTOMER_REQUEST


@pytest.mark.unit
@pytest.mark.parametrize(
    "status",
    [OrderStatus.REQUIRES_APPROVAL, OrderStatus.CONFIRMED, OrderStatus.PAYMENT_PENDING],
)
def test_cliente_nao_cancela_apos_confirmar(status: OrderStatus) -> None:
    """Em especial: `REQUIRES_APPROVAL → CANCELLED` não é pedido do cliente."""
    with pytest.raises(InvalidOrderStateError):
        cancel_by_customer(make_order(status=status), LATER)


@pytest.mark.unit
def test_order_pago_nao_e_cancelavel() -> None:
    with pytest.raises(OrderAlreadyPaidError) as exc:
        cancel_by_customer(make_order(status=OrderStatus.PAID), LATER)
    assert exc.value.code == "ORDER_ALREADY_PAID"


# --- expiração (§5.1) ----------------------------------------------------


@pytest.mark.unit
def test_expiracao_aplica_somente_a_draft() -> None:
    expirado = expire(make_order(status=OrderStatus.DRAFT), LATER)
    assert expirado.status is OrderStatus.EXPIRED

    with pytest.raises(InvalidOrderStateError):
        expire(make_order(status=OrderStatus.CONFIRMED), LATER)


@pytest.mark.unit
def test_confirmado_nao_expira_por_ttl() -> None:
    """Após a confirmação não há TTL automático nesta versão (§5.1)."""
    order = make_order(status=OrderStatus.CONFIRMED, expires_at=FIXED_NOW)
    assert order.is_draft_expired(FIXED_NOW + timedelta(days=30)) is False
    order.ensure_not_expired(FIXED_NOW + timedelta(days=30))


# --- aprovação (§7) -----------------------------------------------------


@pytest.mark.unit
def test_aprovacao_concedida_libera_para_confirmed() -> None:
    order = make_order(status=OrderStatus.REQUIRES_APPROVAL, requires_approval=True)
    liberado = apply_approval_granted(order, LATER)

    assert liberado.status is OrderStatus.CONFIRMED
    assert liberado.cancellation_reason is None


@pytest.mark.unit
def test_aprovacao_rejeitada_cancela_com_motivo_de_rejeicao() -> None:
    """O motivo nunca é apresentado como cancelamento pedido pelo cliente."""
    order = make_order(status=OrderStatus.REQUIRES_APPROVAL, requires_approval=True)
    cancelado = apply_approval_rejected(order, LATER)

    assert cancelado.status is OrderStatus.CANCELLED
    # Motivo exato, não apenas "algum motivo": é o que distingue rejeição
    # administrativa de cancelamento pedido pelo cliente.
    assert cancelado.cancellation_reason is CancellationReason.APPROVAL_REJECTED


@pytest.mark.unit
@pytest.mark.parametrize("status", [OrderStatus.DRAFT, OrderStatus.CONFIRMED, OrderStatus.PAID])
def test_decisao_de_aprovacao_exige_requires_approval(status: OrderStatus) -> None:
    with pytest.raises(InvalidOrderStateError):
        apply_approval_granted(make_order(status=status), LATER)
    with pytest.raises(InvalidOrderStateError):
        apply_approval_rejected(make_order(status=status), LATER)


# --- pagamento (§9, §13, §14) -------------------------------------------


@pytest.mark.unit
def test_confirmed_e_o_unico_estado_pagavel() -> None:
    order = make_order(status=OrderStatus.CONFIRMED)
    assert start_payment(order, LATER).status is OrderStatus.PAYMENT_PENDING


@pytest.mark.unit
def test_pagamento_de_order_aguardando_aprovacao_e_recusado() -> None:
    with pytest.raises(OrderRequiresApprovalError) as exc:
        start_payment(make_order(status=OrderStatus.REQUIRES_APPROVAL), LATER)
    assert exc.value.code == "ORDER_REQUIRES_APPROVAL"


@pytest.mark.unit
def test_pagamento_de_order_pago_e_recusado() -> None:
    with pytest.raises(OrderAlreadyPaidError):
        start_payment(make_order(status=OrderStatus.PAID), LATER)


@pytest.mark.unit
@pytest.mark.parametrize("status", [OrderStatus.DRAFT, OrderStatus.CANCELLED, OrderStatus.EXPIRED])
def test_pagamento_exige_confirmed(status: OrderStatus) -> None:
    with pytest.raises(InvalidOrderStateError):
        start_payment(make_order(status=status), LATER)


@pytest.mark.unit
def test_marcar_pago_a_partir_de_payment_pending() -> None:
    pago = mark_paid(make_order(status=OrderStatus.PAYMENT_PENDING), LATER)
    assert pago.status is OrderStatus.PAID


@pytest.mark.unit
def test_marcar_pago_e_idempotente() -> None:
    """Webhook e polling convergem e podem entregar o mesmo fato duas vezes."""
    order = make_order(status=OrderStatus.PAID)
    assert mark_paid(order, LATER) is order


@pytest.mark.unit
@pytest.mark.parametrize("status", [OrderStatus.CONFIRMED, OrderStatus.DRAFT])
def test_marcar_pago_exige_payment_pending(status: OrderStatus) -> None:
    with pytest.raises(InvalidOrderStateError):
        mark_paid(make_order(status=status), LATER)


@pytest.mark.unit
def test_terminal_nao_aprovado_devolve_order_a_confirmed() -> None:
    """Habilita nova tentativa comercial (§13.2)."""
    liberado = release_for_new_attempt(make_order(status=OrderStatus.PAYMENT_PENDING), LATER)
    assert liberado.status is OrderStatus.CONFIRMED


@pytest.mark.unit
def test_liberacao_para_nova_tentativa_e_idempotente() -> None:
    order = make_order(status=OrderStatus.CONFIRMED)
    assert release_for_new_attempt(order, LATER) is order


@pytest.mark.unit
def test_order_pago_nunca_volta_para_confirmed() -> None:
    """`PAID` é irreversível: reembolso está fora do escopo do MVP."""
    with pytest.raises(OrderAlreadyPaidError):
        release_for_new_attempt(make_order(status=OrderStatus.PAID), LATER)
