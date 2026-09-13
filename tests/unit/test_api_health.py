"""Sondas de saúde e versionamento da API (ADR-006, ADR-016).

Existe uma tensão aparente entre os dois ADRs, e ela se resolve por uma
distinção que vale a pena estar escrita: **sonda de infraestrutura não é API
pública**.

ADR-006 versiona a API de negócio em `/api/v1`. ADR-016 exige `/health` e
`/ready` na raiz, porque quem os consulta é o `HEALTHCHECK` do container e o
`depends_on` do Compose — runtime, não cliente. Versionar uma sonda obrigaria a
imagem a conhecer a versão da API que ela hospeda.

O invariante de ADR-006 que de fato importa continua verificado abaixo: nenhum
**endpoint de negócio** responde fora de `/api/v1`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from urbanopay import __version__


@pytest.mark.unit
def test_health_retorna_ok(client: TestClient) -> None:
    """O contrato que já existia sob `/api/v1` permanece."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "urbanopay-api",
        "version": __version__,
    }


@pytest.mark.unit
def test_liveness_na_raiz_para_o_container(client: TestClient) -> None:
    """ADR-016: `/health` é a sonda do `HEALTHCHECK`, e não depende de banco.

    Sem dependência externa de propósito: banco fora do ar não pode ser lido
    como processo morto, ou o orquestrador reiniciaria um container saudável.
    """
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.unit
def test_sonda_nao_vaza_configuracao(client: TestClient) -> None:
    """Nem `/health` nem `/ready` expõem credencial, host ou provider."""
    corpo = client.get("/health").text + client.get("/ready").text
    proibidos = ("postgres", "password", "secret", "openai", "api_key", "sk-", "localhost")

    assert not [termo for termo in proibidos if termo in corpo.lower()], corpo


@pytest.mark.unit
def test_api_de_negocio_permanece_versionada(client: TestClient) -> None:
    """ADR-006: endpoint de negócio só existe sob `/api/v1`.

    É este o invariante que o teste anterior a ADR-016 protegia. As sondas
    saíram do seu escopo; a API de negócio, não.
    """
    assert client.post("/agent/messages", json={"message": "oi"}).status_code == 404
    assert client.post("/payments/webhook", json={}).status_code == 404
