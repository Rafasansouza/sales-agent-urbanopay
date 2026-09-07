"""Redação do payload de provider (SPEC-003 §12; regra de segurança).

Persistir payload bruto de provider é o caminho mais comum de vazamento de
token e de PII. A allowlist é a defesa, e este teste prova que ela realmente
descarta o que não foi explicitamente permitido.
"""

from __future__ import annotations

from typing import Any

import pytest

from urbanopay.modules.payments.domain.entities import (
    PERSISTABLE_EVENT_KEYS,
    redact_event_payload,
)

# Chaves plausíveis em payload real de provider que **nunca** podem ser
# persistidas: credenciais e dados pessoais do pagador.
CHAVES_PROIBIDAS = [
    "access_token",
    "refresh_token",
    "client_secret",
    "api_key",
    "authorization",
    "card_number",
    "cvv",
    "payer_email",
    "payer_document",
    "payer_cpf",
    "payer_name",
    "payer_phone",
]


@pytest.mark.unit
def test_mantem_apenas_chaves_da_allowlist() -> None:
    payload: dict[str, Any] = {
        "id": "12345",
        "status": "approved",
        "status_detail": "accredited",
        "external_reference": "order-abc",
        "campo_desconhecido": "valor",
    }
    redigido = redact_event_payload(payload)

    assert set(redigido) == {"id", "status", "status_detail", "external_reference"}
    assert "campo_desconhecido" not in redigido


@pytest.mark.unit
@pytest.mark.parametrize("chave", CHAVES_PROIBIDAS)
def test_descarta_credenciais_e_pii(chave: str) -> None:
    """Allowlist, não denylist: chave sensível cai por não estar permitida."""
    redigido = redact_event_payload({"id": "1", chave: "valor-sensivel"})

    assert chave not in redigido
    assert "valor-sensivel" not in str(redigido)


@pytest.mark.unit
def test_allowlist_nao_contem_chave_sensivel() -> None:
    assert not (PERSISTABLE_EVENT_KEYS & set(CHAVES_PROIBIDAS))


@pytest.mark.unit
@pytest.mark.parametrize(
    "valor",
    [
        {"email": "a@b.c"},
        ["a", "b"],
        ("a", "b"),
        {"a", "b"},
    ],
)
def test_descarta_estruturas_aninhadas(valor: object) -> None:
    """Aninhamento é justamente onde dados de pagador costumam viajar."""
    redigido = redact_event_payload({"id": "1", "status": valor})

    assert "status" not in redigido
    assert redigido == {"id": "1"}


@pytest.mark.unit
def test_descarta_valores_nulos() -> None:
    assert redact_event_payload({"id": "1", "status": None}) == {"id": "1"}


@pytest.mark.unit
def test_converte_para_texto() -> None:
    """A coluna guarda texto: tipos do provider não vazam para o schema."""
    redigido = redact_event_payload({"id": 12345, "live_mode": False})

    assert redigido == {"id": "12345", "live_mode": "False"}


@pytest.mark.unit
def test_limita_o_tamanho_do_valor() -> None:
    redigido = redact_event_payload({"status_detail": "x" * 5_000})

    assert len(redigido["status_detail"]) == 256


@pytest.mark.unit
def test_payload_vazio_produz_dicionario_vazio() -> None:
    assert redact_event_payload({}) == {}


@pytest.mark.unit
def test_resultado_e_deterministico() -> None:
    payload: dict[str, Any] = {"status": "approved", "id": "1", "token": "segredo"}

    assert redact_event_payload(payload) == redact_event_payload(payload)
