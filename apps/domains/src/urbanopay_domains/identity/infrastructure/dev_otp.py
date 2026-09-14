"""Canal de OTP para demonstração local (H-12).

H-12 registra o problema: o OTP simulado é gerado com aleatoriedade
criptográfica e **nunca** aparece em resultado de serviço, log ou trace — o que
é correto, e deixa a demonstração humana sem canal para conhecer o código.

Este módulo resolve isso do modo mais restrito possível: um decorador do
`OtpGenerator` que guarda **em memória** o último código gerado, exposto por um
endpoint que só existe quando `APP_ENV=local`.

Restrições que tornam isso aceitável, e que não podem ser afrouxadas:

- **não é tool do LLM**, sob nome algum. `get_otp` é proibida (SPEC-004 §7.4), e
  o valor jamais entra em prompt, estado, envelope ou telemetria;
- **não existe fora de `local`.** A composição só instala este decorador
  quando `settings.is_local`; em qualquer outro ambiente o gerador é o de
  produção, sem sink;
- **memória apenas.** Nada é persistido, nada é logado. Reiniciar o processo
  apaga tudo;
- **não cria caminho de autenticação conhecido.** Continua não existindo OTP
  fixo por configuração: o valor é aleatório como sempre, e apenas fica
  legível para quem já está no host da demonstração.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from urbanopay_domains.identity.domain.ports import OtpGenerator


class DevOtpSink:
    """Guarda o último OTP gerado, para a demonstração local."""

    def __init__(self) -> None:
        self._latest: str | None = None

    def record(self, otp: str) -> None:
        self._latest = otp

    def latest(self) -> str | None:
        """Último código gerado, ou `None` se nenhum foi pedido ainda."""
        return self._latest

    def clear(self) -> None:
        self._latest = None


class RecordingOtpGenerator:
    """Decora um `OtpGenerator` registrando o código no sink.

    Decorador em vez de gerador próprio, de propósito: a geração continua
    sendo a de produção — criptograficamente aleatória —, e o que muda é
    apenas a visibilidade local.
    """

    def __init__(self, inner: OtpGenerator, sink: DevOtpSink) -> None:
        self._inner = inner
        self._sink = sink

    def generate(self) -> str:
        otp = self._inner.generate()
        self._sink.record(otp)
        return otp


__all__ = ["DevOtpSink", "RecordingOtpGenerator"]
