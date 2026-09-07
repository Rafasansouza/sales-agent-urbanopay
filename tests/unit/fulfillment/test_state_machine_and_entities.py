"""Máquina de estados, entidades e enums de fulfillment (SPEC-005 §5.1, §7.1)."""

from __future__ import annotations

import dataclasses
import uuid
from decimal import Decimal

import pytest

from tests.unit.fulfillment.builders import FIXED_NOW, LATER, make_fulfillment
from urbanopay.modules.fulfillment.domain.entities import CreditApplication, Fulfillment
from urbanopay.modules.fulfillment.domain.enums import (
    DocumentKind,
    FailureClass,
    FulfillmentStatus,
    FulfillmentType,
    LedgerEntryType,
)
from urbanopay.modules.fulfillment.domain.errors import UnsupportedFulfillmentTypeError
from urbanopay.modules.fulfillment.domain.state_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    InvalidFulfillmentTransitionError,
    complete,
    ensure_transition_allowed,
    fail,
    is_transition_allowed,
    require_reconciliation,
    start_processing,
)

ORDER_ID = uuid.UUID("00000000-0000-4000-8000-00000000000a")
CARD_ID = uuid.UUID("00000000-0000-4000-8000-00000000000b")
PAYMENT_ID = uuid.UUID("00000000-0000-4000-8000-00000000000c")


def fulfillment(status: FulfillmentStatus) -> Fulfillment:
    return make_fulfillment(order_id=ORDER_ID, card_id=CARD_ID, status=status)


# --- enums ---------------------------------------------------------------


@pytest.mark.unit
def test_cinco_estados_documentados() -> None:
    assert {s.value for s in FulfillmentStatus} == {
        "PENDING",
        "PROCESSING",
        "COMPLETED",
        "FAILED",
        "RECONCILIATION_REQUIRED",
    }


@pytest.mark.unit
def test_apenas_completed_e_terminal() -> None:
    """`FAILED` e `RECONCILIATION_REQUIRED` admitem reentrada explícita."""
    assert {FulfillmentStatus.COMPLETED} == TERMINAL_STATUSES


@pytest.mark.unit
def test_todo_estado_tem_caminho_valido_de_entrada() -> None:
    """Percorre o grafo a partir de `PENDING`, o estado de criação."""
    alcancados = {FulfillmentStatus.PENDING}
    fronteira = [FulfillmentStatus.PENDING]
    while fronteira:
        atual = fronteira.pop()
        for destino in ALLOWED_TRANSITIONS[atual]:
            if destino not in alcancados:
                alcancados.add(destino)
                fronteira.append(destino)

    assert alcancados == set(FulfillmentStatus), (
        f"inalcançáveis: {set(FulfillmentStatus) - alcancados}"
    )


@pytest.mark.unit
def test_ledger_tem_um_unico_tipo_no_mvp() -> None:
    """O MVP credita e não debita — débito exigiria decisão documental."""
    assert {t.value for t in LedgerEntryType} == {"RECHARGE_CREDIT"}


@pytest.mark.unit
def test_comprovante_tem_um_unico_tipo_e_e_simulado() -> None:
    assert {k.value for k in DocumentKind} == {"SIMULATED_NON_FISCAL"}


@pytest.mark.unit
def test_recharge_e_suportado_e_ticket_e_recusado() -> None:
    FulfillmentType.RECHARGE.require_supported()
    with pytest.raises(UnsupportedFulfillmentTypeError) as exc:
        FulfillmentType.TICKET_ISSUANCE.require_supported()
    assert exc.value.code == "UNSUPPORTED_FULFILLMENT_TYPE"


# --- transições ----------------------------------------------------------


@pytest.mark.unit
def test_pending_progride_para_processing() -> None:
    resultado = start_processing(
        fulfillment(FulfillmentStatus.PENDING), LATER, payment_id=PAYMENT_ID
    )

    assert resultado.status is FulfillmentStatus.PROCESSING
    assert resultado.payment_id == PAYMENT_ID
    assert resultado.updated_at == LATER
    assert resultado.completed_at is None


@pytest.mark.unit
def test_conclusao_registra_completed_at() -> None:
    resultado = complete(fulfillment(FulfillmentStatus.PROCESSING), LATER)

    assert resultado.status is FulfillmentStatus.COMPLETED
    assert resultado.completed_at == LATER
    assert resultado.is_completed


@pytest.mark.unit
def test_falha_registra_motivo_e_classe() -> None:
    resultado = fail(
        fulfillment(FulfillmentStatus.PROCESSING),
        LATER,
        reason="MOTIVO",
        failure_class=FailureClass.NON_RETRYABLE,
    )

    assert resultado.status is FulfillmentStatus.FAILED
    assert resultado.failure_reason == "MOTIVO"
    assert resultado.failure_class is FailureClass.NON_RETRYABLE
    assert resultado.completed_at is None


@pytest.mark.unit
def test_reconciliacao_e_classificada_como_desfecho_desconhecido() -> None:
    """Os documentos não sustentam que cartão bloqueado seja irreversível."""
    resultado = require_reconciliation(
        fulfillment(FulfillmentStatus.PROCESSING), LATER, reason="CARD_NOT_ACTIVE"
    )

    assert resultado.status is FulfillmentStatus.RECONCILIATION_REQUIRED
    assert resultado.failure_class is FailureClass.UNKNOWN_OUTCOME
    assert resultado.completed_at is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "status", [FulfillmentStatus.FAILED, FulfillmentStatus.RECONCILIATION_REQUIRED]
)
def test_reentrada_limpa_metadados_da_tentativa_anterior(
    status: FulfillmentStatus,
) -> None:
    """Motivo antigo durante nova execução daria impressão de falha atual."""
    anterior = fulfillment(status)
    assert anterior.failure_reason is not None

    resultado = start_processing(anterior, LATER)

    assert resultado.status is FulfillmentStatus.PROCESSING
    assert resultado.failure_reason is None
    assert resultado.failure_class is None


@pytest.mark.unit
def test_completed_nao_reprocessa() -> None:
    """Terminal não regride: a detecção de inconsistência reporta, não muda."""
    with pytest.raises(InvalidFulfillmentTransitionError) as exc:
        start_processing(fulfillment(FulfillmentStatus.COMPLETED), LATER)
    # Reutiliza código documentado, sem inventar nome novo.
    assert exc.value.code == "EFFECT_CONFLICT"


@pytest.mark.unit
def test_grafo_nao_admite_transicao_fora_da_spec() -> None:
    assert not is_transition_allowed(FulfillmentStatus.PENDING, FulfillmentStatus.COMPLETED)
    assert not is_transition_allowed(
        FulfillmentStatus.COMPLETED, FulfillmentStatus.RECONCILIATION_REQUIRED
    )
    assert not is_transition_allowed(FulfillmentStatus.FAILED, FulfillmentStatus.COMPLETED)

    with pytest.raises(InvalidFulfillmentTransitionError):
        ensure_transition_allowed(FulfillmentStatus.PENDING, FulfillmentStatus.COMPLETED)


@pytest.mark.unit
def test_transicao_devolve_nova_instancia() -> None:
    original = fulfillment(FulfillmentStatus.PENDING)
    resultado = start_processing(original, LATER)

    assert original.status is FulfillmentStatus.PENDING
    assert resultado is not original
    assert resultado.id == original.id


@pytest.mark.unit
def test_fulfillment_e_imutavel() -> None:
    alvo = fulfillment(FulfillmentStatus.PENDING)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(alvo, "status", FulfillmentStatus.COMPLETED)  # noqa: B010


# --- crédito -------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("antes", "valor", "depois"),
    [
        ("0.00", "50.00", "50.00"),
        ("21.50", "50.00", "71.50"),
        ("10.05", "0.01", "10.06"),
        ("99.99", "0.02", "100.01"),
    ],
)
def test_credito_soma_exata_sem_arredondamento(antes: str, valor: str, depois: str) -> None:
    resultado = CreditApplication.credit(balance_before=Decimal(antes), amount=Decimal(valor))

    assert resultado.balance_after == Decimal(depois)
    assert str(resultado.balance_after) == depois
    assert resultado.balance_after == resultado.balance_before + resultado.amount


@pytest.mark.unit
def test_credito_preserva_escala_do_decimal() -> None:
    """Escala preservada: nada de `float` e nada de `quantize` implícito."""
    resultado = CreditApplication.credit(balance_before=Decimal("0.00"), amount=Decimal("137.45"))

    assert isinstance(resultado.balance_after, Decimal)
    assert str(resultado.balance_after) == "137.45"


@pytest.mark.unit
def test_created_at_do_builder_e_fixo() -> None:
    assert fulfillment(FulfillmentStatus.PENDING).created_at == FIXED_NOW
