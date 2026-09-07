"""Entidade `Approval` (SPEC-003 §7)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from tests.unit.orders_payments.builders import FIXED_NOW, make_approval
from urbanopay.modules.approvals.domain.enums import ApprovalStatus
from urbanopay.modules.approvals.domain.errors import InvalidApprovalStateError
from urbanopay.modules.orders.domain.enums import OrderStatus

DECIDED_AT = FIXED_NOW + timedelta(minutes=5)
ACTOR = "operator-7"
FIXED_ORDER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.mark.unit
def test_enum_tem_exatamente_tres_estados() -> None:
    """Sem TTL e sem `CANCELLED`: a SPEC não define nenhum dos dois."""
    assert {status.value for status in ApprovalStatus} == {"PENDING", "APPROVED", "REJECTED"}


@pytest.mark.unit
def test_enums_de_approval_e_order_nao_colidem() -> None:
    """`Approval.APPROVED` existe; `Order.APPROVED` não (§6)."""
    assert ApprovalStatus.APPROVED.value == "APPROVED"
    assert "APPROVED" not in {status.value for status in OrderStatus}


@pytest.mark.unit
def test_aprovacao_registra_ator_e_instante() -> None:
    approval = make_approval(order_id=FIXED_ORDER_ID)
    decidida = approval.approve(ACTOR, DECIDED_AT)

    assert decidida.status is ApprovalStatus.APPROVED
    assert decidida.decided_by == ACTOR
    assert decidida.decided_at == DECIDED_AT


@pytest.mark.unit
def test_rejeicao_registra_ator_e_instante() -> None:
    decidida = make_approval(order_id=FIXED_ORDER_ID).reject(ACTOR, DECIDED_AT)

    assert decidida.status is ApprovalStatus.REJECTED
    assert decidida.decided_by == ACTOR
    assert decidida.decided_at == DECIDED_AT


@pytest.mark.unit
def test_pendente_nao_tem_decisao_registrada() -> None:
    """Espelha `ck_approvals_decision_audit_complete`."""
    approval = make_approval(order_id=FIXED_ORDER_ID)

    assert approval.is_pending
    assert approval.decided_at is None
    assert approval.decided_by is None


@pytest.mark.unit
@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED])
def test_terminal_nao_e_redecidido(status: ApprovalStatus) -> None:
    """Estados terminais não retornam a `PENDING` nem trocam de decisão."""
    approval = make_approval(order_id=FIXED_ORDER_ID, status=status)

    with pytest.raises(InvalidApprovalStateError) as exc:
        approval.approve(ACTOR, DECIDED_AT)
    # Reutiliza código documentado da §16: nenhum código novo foi inventado.
    assert exc.value.code == "INVALID_ORDER_STATE"

    with pytest.raises(InvalidApprovalStateError):
        approval.reject(ACTOR, DECIDED_AT)


@pytest.mark.unit
def test_decisao_devolve_nova_instancia() -> None:
    approval = make_approval(order_id=FIXED_ORDER_ID)
    decidida = approval.approve(ACTOR, DECIDED_AT)

    assert approval.status is ApprovalStatus.PENDING
    assert decidida is not approval
    assert decidida.id == approval.id
    assert decidida.order_id == approval.order_id
