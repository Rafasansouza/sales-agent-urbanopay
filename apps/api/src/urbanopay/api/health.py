"""Sondas de saúde (ADR-016).

Duas sondas, com responsabilidades separadas de propósito:

- **`/health` — liveness.** Prova que o processo responde. Deliberadamente
  **sem dependência externa**: banco fora do ar não pode ser lido como
  "processo morto", ou o orquestrador reiniciaria um container saudável e
  transformaria uma indisponibilidade de banco numa de aplicação.
- **`/ready` — readiness.** Verifica o que o processo precisa para servir
  tráfego: banco alcançável e migrations no head.

Nenhuma das duas vaza configuração, credencial, hostname, versão de
dependência ou detalhe interno.
"""

from __future__ import annotations

from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict

from urbanopay import __version__
from urbanopay.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Resposta da sonda de liveness."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str
    version: str


class ReadyResponse(BaseModel):
    """Resposta da sonda de readiness."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "degraded"]
    database: bool
    migrations: bool


@router.get("/health", response_model=HealthResponse, summary="Liveness")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """O processo está vivo.

    Sem I/O: é a sonda que o `HEALTHCHECK` do container usa, e ela precisa
    responder mesmo quando uma dependência está indisponível.
    """
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)


@router.get("/ready", response_model=ReadyResponse, summary="Readiness")
async def ready(request: Request, response: Response) -> ReadyResponse:
    """O processo pode servir tráfego.

    `migrations` é verdadeiro quando `alembic_version` existe e tem revisão
    gravada. A checagem é proposital: schema não migrado é motivo para não
    receber tráfego, e o job de migration do Compose já garante a ordem — esta
    sonda apenas torna a garantia observável.
    """
    container = getattr(request.app.state, "container", None)
    database = False
    migrations = False

    if container is not None:
        try:
            async with container.engine.connect() as connection:
                await connection.execute(sa.text("SELECT 1"))
                database = True
                revision = (
                    await connection.execute(sa.text("SELECT version_num FROM alembic_version"))
                ).scalar_one_or_none()
                migrations = revision is not None
        except Exception:
            database = database and False

    ok = database and migrations
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ready" if ok else "degraded", database=database, migrations=migrations
    )
