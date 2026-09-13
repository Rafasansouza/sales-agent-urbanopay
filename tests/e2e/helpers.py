"""Auxiliares da camada E2E.

`Conversa` é um cliente fino da API de conversa: ela **não** contorna serviço
algum e **não** escreve no banco. Tudo passa pelos mesmos endpoints que a
demonstração humana usa.

`saldo_do_cartao` lê o saldo direto do banco, e apenas para **verificação** —
nunca para preparar estado. A diferença importa: preparar estado por escrita
direta invalidaria o teste; conferir o efeito por leitura direta é o que prova
que o efeito aconteceu de verdade.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

import sqlalchemy as sa

from urbanopay.core.config import Settings
from urbanopay.db.engine import build_database_url
from urbanopay.modules.cards.infrastructure.models import CardModel

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

# Mariana, do dataset fictício de SPEC-002 §13. Nenhum CPF real.
DEMO_CPF: Final = "70011122233"

_MESSAGES: Final = "/api/v1/agent/messages"


class Conversa:
    """Conduz uma conversa pela API, mantendo os identificadores do turno."""

    def __init__(self, client: TestClient) -> None:
        self._client = client
        self.conversation_id: str | None = None
        self.session_id: str | None = None
        self.phase: str = "DISCOVERY"

    def diga(self, mensagem: str, *, request_id: str | None = None) -> dict[str, Any]:
        """Envia uma mensagem e devolve o corpo da resposta."""
        payload: dict[str, Any] = {
            "message": mensagem,
            "conversation_id": self.conversation_id,
            "session_id": self.session_id,
            "request_id": request_id or str(uuid4()),
        }
        response = self._client.post(_MESSAGES, json=payload)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        self.conversation_id = body["conversation_id"]
        self.session_id = body["session_id"]
        self.phase = body["phase"]
        return body

    def otp_local(self) -> str:
        """Lê o OTP pelo canal de demonstração (H-12).

        O valor nunca passou por prompt, log, telemetria ou pela tabela da
        conversa: ele existe apenas em memória, no sink de `local`.
        """
        response = self._client.get("/api/v1/dev/otp")
        assert response.status_code == 200, response.text
        otp: str = response.json()["otp"]
        return otp

    def liquidar(self, status: str = "APPROVED") -> dict[str, Any]:
        """Faz o sandbox reportar o desfecho e reconcilia."""
        response = self._client.post(self._settle_url(), json={"status": status})
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    def liquidar_status(self, status: str = "APPROVED") -> int:
        """Código HTTP da liquidação, para os casos em que ela **não** pode ocorrer."""
        return self._client.post(self._settle_url(), json={"status": status}).status_code

    def reconectar(self) -> Conversa:
        """Retoma a mesma conversa a partir do zero de memória de processo.

        Devolve uma instância nova, carregando **apenas** os identificadores —
        que é exatamente o que um cliente teria depois de um restart do
        servidor.
        """
        retomada = Conversa(self._client)
        retomada.conversation_id = self.conversation_id
        retomada.session_id = self.session_id
        return retomada

    def _settle_url(self) -> str:
        return f"/api/v1/dev/conversations/{self.conversation_id}/settle"


def saldo_do_cartao(last4: str) -> Decimal:
    """Saldo oficial do cartão, lido do banco para **verificação**.

    Conexão **síncrona e própria**, deliberadamente: o `TestClient` roda a
    aplicação em um portal com event loop próprio, e emprestar a sessão dele
    para uma leitura de teste misturaria os dois mundos. Ler por fora também
    prova mais — o efeito existe no banco, não apenas na resposta da API.
    """
    engine = sa.create_engine(build_database_url(Settings()), poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as connection:
            balance = connection.execute(
                sa.select(CardModel.balance).where(CardModel.card_last4 == last4)
            ).scalar_one()
    finally:
        engine.dispose()
    assert isinstance(balance, Decimal)
    return balance
