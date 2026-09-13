"""Superfície de desenvolvimento — registrada somente quando `APP_ENV=local`."""

from __future__ import annotations

from urbanopay.api.dev.router import router as dev_router

__all__ = ["dev_router"]
