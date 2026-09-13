"""Fábrica da aplicação FastAPI.

Fonte: ADR-006 (camada HTTP), ADR-012 (engine e sessão), ADR-014 (persistência
conversacional), ADR-015 (provider de LLM), ADR-016 (execução em container).

Este módulo apenas monta a aplicação: configuração, logging, telemetria,
tratamento de erro, ciclo de vida e registro de routers. Nenhuma regra de
negócio aqui.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from urbanopay import __version__
from urbanopay.api import health
from urbanopay.api.container import build_container
from urbanopay.api.v1.router import api_v1_router
from urbanopay.core.config import Settings, get_settings
from urbanopay.core.errors import AppError
from urbanopay.core.event_loop import ensure_selector_event_loop_policy
from urbanopay.core.logging import configure_logging
from urbanopay.core.telemetry import configure_telemetry

logger = logging.getLogger(__name__)

# Momento previsto pelo `core/event_loop.py`: "quando a API passar a consumir o
# banco, o boot deve chamar `ensure_selector_event_loop_policy()` antes de criar
# o event loop". A API passou a consumir agora. Em Linux é no-op; em Windows é o
# que torna o psycopg assíncrono utilizável (ADR-012).
ensure_selector_event_loop_policy()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ciclo de vida da aplicação.

    O engine e os serviços nascem aqui, uma única vez, e o engine é descartado
    no encerramento. **Nenhum schema é criado neste ponto**: migrations são
    aplicadas pelo job dedicado do Compose, e Alembic continua sendo a
    autoridade do schema (ADR-012, ADR-014, ADR-016).

    Credencial ausente falha **aqui**, no startup, e não no meio de uma
    conversa: `LLM_PROVIDER=openai` sem `OPENAI_API_KEY` não sobe (ADR-015).
    """
    settings: Settings = get_settings()
    configure_logging(settings.log_level)
    configure_telemetry(settings)

    container = build_container(settings)
    app.state.container = container

    logger.info(
        "aplicacao iniciada",
        extra={
            "app_env": settings.app_env.value,
            # Somente o **nome** do provider: nenhuma credencial, nem parte
            # dela, aparece em log (ADR-015).
            "llm_provider": settings.llm_provider.value,
            "payment_provider": settings.payment_provider.value,
        },
    )
    try:
        yield
    finally:
        await container.dispose()
        logger.info("aplicacao encerrada")


def create_app() -> FastAPI:
    """Constrói e devolve a aplicação FastAPI."""
    settings = get_settings()

    app = FastAPI(
        title="UrbanoPay Mobilidade — API",
        description=(
            "Backend do assistente inteligente de vendas da UrbanoPay Mobilidade. "
            "O LLM interpreta, recomenda e explica; o código valida, calcula, "
            "autoriza, transiciona estado, executa e persiste."
        ),
        version=__version__,
        lifespan=lifespan,
        # A documentação interativa fica restrita ao ambiente local.
        docs_url="/docs" if settings.is_local else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.is_local else None,
    )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """Converte erro de aplicação no envelope padrão.

        Nunca expõe stack trace nem detalhe interno na resposta (ADR-006).
        """
        logger.warning(
            "erro de aplicacao",
            extra={"error_code": exc.code, "path": request.url.path, **exc.context},
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_response().model_dump(mode="json"),
        )

    # Sondas na raiz: é o que o `HEALTHCHECK` do container e o `depends_on` do
    # Compose consultam (ADR-016).
    app.include_router(health.router)
    # E também sob /api/v1, preservando o contrato que já existia.
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(api_v1_router)

    if settings.is_local:
        # Superfície de demonstração: OTP simulado (H-12), liquidação do
        # sandbox e a página de chat. **Não existe fora de `local`** — as rotas
        # sequer são registradas, em vez de dependerem de uma checagem em
        # tempo de request que alguém possa contornar.
        from urbanopay.api.dev import dev_router

        app.include_router(dev_router)

    return app


app = create_app()
