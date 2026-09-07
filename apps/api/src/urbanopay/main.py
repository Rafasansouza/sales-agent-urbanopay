"""Fábrica da aplicação FastAPI.

Fonte: ADR-006.

Este módulo apenas monta a aplicação: configuração, logging, telemetria,
tratamento de erro e registro de routers. Nenhuma regra de negócio aqui.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from urbanopay import __version__
from urbanopay.api.v1.router import api_v1_router
from urbanopay.core.config import Settings, get_settings
from urbanopay.core.errors import AppError
from urbanopay.core.logging import configure_logging
from urbanopay.core.telemetry import configure_telemetry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ciclo de vida da aplicação.

    Nesta fase não há pool de conexão nem cliente de provider para inicializar:
    a persistência decidida em ADR-012 ainda não foi implementada.
    """
    settings: Settings = get_settings()
    configure_logging(settings.log_level)
    configure_telemetry(settings)

    logger.info(
        "aplicacao iniciada",
        extra={
            "app_env": settings.app_env.value,
            "llm_provider": settings.llm_provider.value,
            "payment_provider": settings.payment_provider.value,
        },
    )
    yield
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

    app.include_router(api_v1_router)
    return app


app = create_app()
