"""Fixtures da camada E2E.

Requisitos de ambiente: PostgreSQL no ar com as migrations aplicadas, e as
variáveis `POSTGRES_*` definidas (ambiente, `.env` local, ou o job da CI).

Providers: `FakeLLMProvider`, `FakePaymentProvider` e o OTP em modo dev.
**Nenhuma chamada de rede real**, nenhuma credencial — nem a jornada nem os
evals dependem de provider externo (ADR-007, ADR-010, ADR-015).

`APP_ENV=local` é forçado aqui porque a jornada demonstrável inclui a
superfície de demonstração: o canal do OTP (H-12) e a liquidação do sandbox só
existem em `local`, por decisão. Testar a demo exige subir a demo.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient

from urbanopay.core.config import get_settings
from urbanopay.core.event_loop import ensure_selector_event_loop_policy
from urbanopay.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def migrated_e2e() -> None:
    """Garante o banco em `head` antes da jornada."""
    cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location",
        str(REPO_ROOT / "apps" / "api" / "src" / "urbanopay" / "db" / "migrations"),
    )
    command.upgrade(cfg, "head")


@pytest.fixture
def demo_client(
    monkeypatch: pytest.MonkeyPatch,
    migrated_e2e: None,
) -> Iterator[TestClient]:
    """Aplicação completa, com providers falsos e superfície de demonstração."""
    del migrated_e2e
    # O portal do TestClient cria o proprio event loop: a politica precisa
    # estar aplicada antes (ADR-012, Windows).
    ensure_selector_event_loop_policy()
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("PAYMENT_PROVIDER", "fake")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        # Dataset fictício de SPEC-002 §13 (A-12). Idempotente.
        client.post("/api/v1/dev/seed")
        yield client

    get_settings.cache_clear()
