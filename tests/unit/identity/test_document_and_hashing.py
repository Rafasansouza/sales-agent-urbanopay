"""Normalização de documento (SPEC-002 §3) e primitivas HMAC."""

from __future__ import annotations

import uuid

import pytest

from tests.unit.identity.fakes import TEST_SECRET, test_hasher
from urbanopay.modules.identity.domain.value_objects import IdentityHasher, normalize_document


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("111.222.333-44", "11122233344", id="pontuado"),
        pytest.param("11122233344", "11122233344", id="digitos"),
        pytest.param(" 111 222 333 44 ", "11122233344", id="espacos"),
    ],
)
def test_normalizacao_valida(raw: str, expected: str) -> None:
    assert normalize_document(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    ["", "123", "123456789012", "abc.def.ghi-jk", "1112223334"],
    ids=["vazio", "curto", "longo", "letras", "dez-digitos"],
)
def test_formato_invalido_retorna_none(raw: str) -> None:
    """`None` vira o resultado INVALID_DOCUMENT na aplicação — não é exceção.

    SPEC-002 §3 exige apenas normalizar e validar formato (11 dígitos);
    dígitos verificadores NÃO são validados — regra ausente da SPEC.
    """
    assert normalize_document(raw) is None


@pytest.mark.unit
def test_hash_cpf_deterministico_e_sem_plaintext() -> None:
    hasher = test_hasher()
    digest = hasher.hash_cpf("11122233344")

    assert digest == hasher.hash_cpf("11122233344")
    assert "11122233344" not in digest
    assert TEST_SECRET not in digest


@pytest.mark.unit
def test_hash_muda_com_o_segredo() -> None:
    """HMAC com segredo: sem o segredo, o hash não é reproduzível."""
    assert IdentityHasher("segredo-a").hash_cpf("11122233344") != IdentityHasher(
        "segredo-b"
    ).hash_cpf("11122233344")


@pytest.mark.unit
def test_separacao_de_dominio_entre_cpf_e_otp() -> None:
    """Prefixos `cpf:`/`otp:` — mesmo insumo nunca colide entre domínios."""
    hasher = test_hasher()
    challenge_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    assert hasher.hash_cpf("123456") != hasher.hash_otp(challenge_id, "123456")


@pytest.mark.unit
def test_hash_otp_vinculado_ao_challenge() -> None:
    """O mesmo OTP em challenges diferentes produz hashes diferentes (anti-replay)."""
    hasher = test_hasher()
    a = uuid.UUID("00000000-0000-4000-8000-00000000000a")
    b = uuid.UUID("00000000-0000-4000-8000-00000000000b")
    assert hasher.hash_otp(a, "123456") != hasher.hash_otp(b, "123456")


@pytest.mark.unit
def test_verificacao_de_otp() -> None:
    hasher = test_hasher()
    challenge_id = uuid.uuid4()
    stored = hasher.hash_otp(challenge_id, "123456")

    assert hasher.verify_otp(challenge_id, "123456", stored) is True
    assert hasher.verify_otp(challenge_id, "654321", stored) is False
    assert hasher.verify_otp(uuid.uuid4(), "123456", stored) is False


@pytest.mark.unit
def test_segredo_vazio_e_rejeitado() -> None:
    with pytest.raises(ValueError, match="IDENTITY_HASH_SECRET"):
        IdentityHasher("")


@pytest.mark.unit
def test_repr_do_hasher_nao_expoe_segredo() -> None:
    assert TEST_SECRET not in repr(test_hasher())
