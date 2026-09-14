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
from urbanopay.main import create_app
from urbanopay_database.event_loop import selector_loop_factory

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
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Cliente HTTP de teste sobre a aplicação FastAPI.

    A configuração é **injetada, não herdada do ambiente**: um teste de unidade
    não pode depender de existir um `.env` na máquina, nem passar por acidente
    porque o desenvolvedor tem um. Todos os valores são fictícios.

    Isto **não** torna o teste de integração: montar a aplicação cria o engine,
    mas não abre conexão — e as sondas de liveness não tocam o banco, que é
    exatamente a propriedade que elas existem para ter (ADR-016).
    """
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("POSTGRES_PASSWORD", "unit_test_fictitious_password")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", "unit_test_fictitious_secret")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("PAYMENT_PROVIDER", "fake")
    get_settings.cache_clear()

    with TestClient(create_app()) as test_client:
        yield test_client

    get_settings.cache_clear()
