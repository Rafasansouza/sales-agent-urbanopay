"""Value objects e primitivas criptográficas do domínio de identidade.

Somente biblioteca padrão (`hmac`, `hashlib`) — nenhuma dependência
criptográfica nova (decisão aprovada no plano da SPEC-002).

Estratégia de hashing (decisão aprovada):

- CPF nunca é armazenado em claro nem como SHA-256 puro (espaço pequeno,
  enumerável). O identificador de lookup é `HMAC-SHA256(secret, "cpf:" + cpf)`.
- OTP nunca é armazenado; persiste-se
  `HMAC-SHA256(secret, "otp:" + challenge_id + ":" + otp)`, com verificação em
  tempo constante (`hmac.compare_digest`).
- Os prefixos `cpf:`/`otp:` fazem a separação de domínio sobre o mesmo segredo.

⚠️ Rotação do segredo exige estratégia de migração dos identificadores
derivados (todos os `cpf_hash` mudam) — documentado em `core/config.py`.

Nunca registre em log: OTP, HMAC de OTP, CPF ou o segredo.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

# SPEC-002 §3 exige somente "normalizar; validar formato": 11 dígitos após a
# normalização. Dígitos verificadores NÃO são validados — regra não presente
# na SPEC (decisão aprovada de não inventar norma).
_CPF_LENGTH = 11


def normalize_document(raw: str) -> str | None:
    """Normaliza o documento para dígitos; `None` quando o formato é inválido.

    `None` vira o resultado tipado `INVALID_DOCUMENT` na aplicação (§3) — não
    é exceção, é resultado esperado de fluxo.
    """
    digits = "".join(char for char in raw if char.isdigit())
    if len(digits) != _CPF_LENGTH:
        return None
    return digits


class IdentityHasher:
    """Deriva e verifica os HMACs de identidade com um único segredo.

    O segredo chega como `str` já extraído do `SecretStr` pela composição —
    o domínio não conhece pydantic. Instâncias não expõem o segredo em
    `repr`/`str`.
    """

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError(
                "IDENTITY_HASH_SECRET não configurado. Defina a variável de "
                "ambiente ou o .env local (ver .env.example)."
            )
        self._secret = secret.encode("utf-8")

    def __repr__(self) -> str:  # pragma: no cover - proteção de segredo
        return "IdentityHasher(secret=***)"

    def _digest(self, message: str) -> str:
        return hmac.new(self._secret, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def hash_cpf(self, normalized_cpf: str) -> str:
        """Identificador determinístico de lookup do CPF normalizado."""
        return self._digest(f"cpf:{normalized_cpf}")

    def hash_otp(self, challenge_id: UUID, otp: str) -> str:
        """HMAC do OTP, vinculado ao challenge (anti-replay entre challenges)."""
        return self._digest(f"otp:{challenge_id}:{otp}")

    def verify_otp(self, challenge_id: UUID, otp: str, expected_hash: str) -> bool:
        """Comparação em tempo constante do OTP apresentado."""
        return hmac.compare_digest(self.hash_otp(challenge_id, otp), expected_hash)
