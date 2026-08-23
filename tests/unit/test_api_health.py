"""Teste de fumaça do bootstrap.

Verifica apenas que a aplicação é montável e que o envelope de resposta do
health check é o esperado. Nenhuma regra de negócio é exercitada aqui.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from urbanopay import __version__


@pytest.mark.unit
def test_health_retorna_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "urbanopay-api",
        "version": __version__,
    }


@pytest.mark.unit
def test_health_esta_sob_api_v1(client: TestClient) -> None:
    """ADR-006 exige que a API pública seja versionada em `/api/v1`."""
    assert client.get("/health").status_code == 404
