"""Gerador de OTP do runtime (SPEC-002 §4).

Implementação do port `OtpGenerator` com `secrets` da biblioteca padrão —
aleatoriedade criptográfica, sem OTP fixo por configuração (decisão aprovada:
um código fixo em runtime seria um caminho permanente de autenticação
conhecido). Testes injetam um gerador determinístico próprio.

O valor gerado nunca é registrado em log nem devolvido em resultado de
serviço; a exposição controlada para a jornada demonstrativa é decisão
pendente da SPEC-004 (H-12 em docs/OPEN-QUESTIONS.md).
"""

from __future__ import annotations

import secrets

# Comprimento usual de OTP numérico; a SPEC não fixa formato.
_OTP_DIGITS = 6


class SecretsOtpGenerator:
    """Gera OTPs numéricos aleatórios de 6 dígitos."""

    def generate(self) -> str:
        return "".join(str(secrets.randbelow(10)) for _ in range(_OTP_DIGITS))
