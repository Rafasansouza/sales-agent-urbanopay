"""Fixtures compartilhadas da suíte de testes.

Fonte: CLAUDE.md, AGENT-HARNESS §5.

Regras que valem para toda a suíte:

- nenhum teste depende de rede externa;
- nenhuma chamada real a provider de LLM ou de pagamento em CI: use
  `FakeLLMProvider` e `FakePaymentProvider` (ADR-007, ADR-010);
- nenhum dado pessoal real, em nenhum ambiente;
- todo teste possui marcador (`unit`, `integration`, `e2e` ou `eval`).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from urbanopay.core.config import Settings, get_settings
from urbanopay.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Configuração da aplicação usada nos testes.

    O cache de `get_settings` é limpo para que variáveis de ambiente
    manipuladas por um teste não vazem para outro.
    """
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Cliente HTTP de teste sobre a aplicação FastAPI."""
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
