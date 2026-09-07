"""Limiar de aprovação humana (SPEC-003 §7).

A comparação é **estritamente maior**: R$ 200,00 exatos não exigem aprovação.
O caso de fronteira é obrigatório por §17, e é exatamente onde um `>=` no
lugar de `>` passaria despercebido.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from urbanopay.modules.orders.domain.enums import OperationType
from urbanopay.modules.orders.domain.policies import (
    DEFAULT_APPROVAL_THRESHOLD,
    ApprovalPolicy,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("total", "esperado"),
    [
        ("0.01", False),
        ("50.00", False),
        ("199.99", False),
        ("200.00", False),
        ("200.01", True),
        ("250.00", True),
        ("10000.00", True),
    ],
)
def test_limiar_de_aprovacao(total: str, esperado: bool) -> None:
    policy = ApprovalPolicy()
    resultado = policy.requires_approval(
        operation_type=OperationType.RECHARGE, total=Decimal(total)
    )
    assert resultado is esperado


@pytest.mark.unit
def test_limiar_default_e_o_da_spec() -> None:
    assert Decimal("200.00") == DEFAULT_APPROVAL_THRESHOLD
    assert ApprovalPolicy().threshold == DEFAULT_APPROVAL_THRESHOLD


@pytest.mark.unit
def test_limiar_e_injetavel_sem_reescrever_a_regra() -> None:
    """Teste exercita a fronteira sem duplicar a comparação em outro lugar."""
    policy = ApprovalPolicy(threshold=Decimal("10.00"))

    assert not policy.requires_approval(
        operation_type=OperationType.RECHARGE, total=Decimal("10.00")
    )
    assert policy.requires_approval(operation_type=OperationType.RECHARGE, total=Decimal("10.01"))


@pytest.mark.unit
def test_politica_e_deterministica() -> None:
    policy = ApprovalPolicy()
    total = Decimal("200.01")
    primeiro = policy.requires_approval(operation_type=OperationType.RECHARGE, total=total)
    segundo = policy.requires_approval(operation_type=OperationType.RECHARGE, total=total)
    assert primeiro is segundo is True
