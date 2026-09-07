"""Contrato transversal de idempotência (SPEC-003 §11)."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timedelta

import pytest

from tests.unit.orders_payments.builders import FIXED_NOW
from urbanopay.core.idempotency import (
    IdempotencyConflictError,
    IdempotencyRecord,
    IdempotencyStatus,
    ensure_same_request,
    request_fingerprint,
)


def make_record(
    *,
    status: IdempotencyStatus = IdempotencyStatus.IN_PROGRESS,
    fingerprint: str = "abc",
    updated_at: datetime | None = None,
) -> IdempotencyRecord:
    moment = updated_at if updated_at is not None else FIXED_NOW
    return IdempotencyRecord(
        key="key-1",
        operation="create_payment",
        request_fingerprint=fingerprint,
        status=status,
        resource_id=uuid.uuid4(),
        response_reference=None,
        created_at=FIXED_NOW,
        updated_at=moment,
        completed_at=None,
    )


# --- status (§11.1) ------------------------------------------------------


@pytest.mark.unit
def test_tem_exatamente_tres_status() -> None:
    assert {status.value for status in IdempotencyStatus} == {
        "IN_PROGRESS",
        "COMPLETED",
        "FAILED",
    }


# --- fingerprint ---------------------------------------------------------


@pytest.mark.unit
def test_fingerprint_e_deterministico() -> None:
    payload = {"order_id": "abc", "customer_id": "def"}
    assert request_fingerprint(payload) == request_fingerprint(payload)


@pytest.mark.unit
def test_fingerprint_independe_da_ordem_das_chaves() -> None:
    """Mesma requisição, chaves em ordem diferente, mesma impressão."""
    assert request_fingerprint({"a": "1", "b": "2"}) == request_fingerprint({"b": "2", "a": "1"})


@pytest.mark.unit
def test_fingerprint_muda_com_o_conteudo() -> None:
    assert request_fingerprint({"a": "1"}) != request_fingerprint({"a": "2"})
    assert request_fingerprint({"a": "1"}) != request_fingerprint({"b": "1"})


@pytest.mark.unit
def test_fingerprint_nao_confunde_chave_com_valor() -> None:
    """Concatenação ingênua colidiria; a serialização canônica não."""
    assert request_fingerprint({"ab": "c"}) != request_fingerprint({"a": "bc"})


@pytest.mark.unit
def test_fingerprint_nao_expoe_o_conteudo() -> None:
    """É hash: o valor original não aparece no resultado."""
    impressao = request_fingerprint({"order_id": "pedido-secreto-123"})

    assert "pedido-secreto-123" not in impressao
    assert len(impressao) == 64


# --- conflito ------------------------------------------------------------


@pytest.mark.unit
def test_mesma_requisicao_nao_conflita() -> None:
    ensure_same_request(make_record(fingerprint="abc"), "abc")


@pytest.mark.unit
def test_payload_divergente_produz_conflito() -> None:
    with pytest.raises(IdempotencyConflictError) as exc:
        ensure_same_request(make_record(fingerprint="abc"), "xyz")

    assert exc.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.unit
def test_mensagem_de_conflito_nao_carrega_payload() -> None:
    with pytest.raises(IdempotencyConflictError) as exc:
        ensure_same_request(make_record(fingerprint="abc"), "xyz")

    assert "abc" not in str(exc.value)
    assert "xyz" not in str(exc.value)


# --- obsolescência (§11.3) ----------------------------------------------


@pytest.mark.unit
def test_registro_recente_nao_e_obsoleto() -> None:
    record = make_record(status=IdempotencyStatus.IN_PROGRESS)
    assert record.is_stale(FIXED_NOW + timedelta(seconds=10), 60) is False


@pytest.mark.unit
def test_registro_em_progresso_ha_muito_tempo_e_obsoleto() -> None:
    """Obsolescência autoriza **consultar o provider**, nunca cobrar de novo."""
    record = make_record(status=IdempotencyStatus.IN_PROGRESS)
    assert record.is_stale(FIXED_NOW + timedelta(seconds=60), 60) is True


@pytest.mark.unit
@pytest.mark.parametrize("status", [IdempotencyStatus.COMPLETED, IdempotencyStatus.FAILED])
def test_registro_concluido_nunca_e_obsoleto(status: IdempotencyStatus) -> None:
    """Resultado conhecido não precisa de reconciliação, por mais antigo que seja."""
    record = make_record(status=status)
    assert record.is_stale(FIXED_NOW + timedelta(days=365), 60) is False


@pytest.mark.unit
def test_registro_e_imutavel() -> None:
    record = make_record()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(record, "status", IdempotencyStatus.COMPLETED)  # noqa: B010
