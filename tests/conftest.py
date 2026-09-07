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

import sys
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from urbanopay.core.config import Settings, get_settings
from urbanopay.core.event_loop import selector_loop_factory
from urbanopay.main import create_app

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable

# Em Windows, o ProactorEventLoop padrão é incompatível com psycopg async
# (ADR-012). O hook do pytest-asyncio abaixo fornece um SelectorEventLoop para
# todos os testes async. O hook só é REGISTRADO em Windows: em Linux/macOS ele
# nem existe, preservando o comportamento padrão do plugin.
#
# Nota: solução específica do Python 3.13 — ver urbanopay/core/event_loop.py.
if sys.platform == "win32":

    def pytest_asyncio_loop_factories(
        config: pytest.Config,
        item: pytest.Item,
    ) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
        return {"selector": selector_loop_factory}


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
