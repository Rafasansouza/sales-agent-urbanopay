"""Endpoint de health check.

Único endpoint desta fase do bootstrap. Não expõe informação sensível: nem
versão de dependência, nem hostname, nem configuração de provider.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from urbanopay import __version__
from urbanopay.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Resposta do health check."""

    status: Literal["ok"]
    service: str
    version: str


@router.get("/health", response_model=HealthResponse, summary="Health check")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Indica que o processo da API está no ar.

    Deliberadamente não verifica PostgreSQL nem Redis: essas verificações
    dependem da camada de persistência (ADR-012, aceito), que ainda não foi
    implementada.
    """
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)
