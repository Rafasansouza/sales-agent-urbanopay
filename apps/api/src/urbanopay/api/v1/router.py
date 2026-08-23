"""Agregador dos routers da versão 1 da API.

Conforme as SPECs forem implementadas, cada módulo de domínio expõe seu
próprio router e o registra aqui. Nenhuma regra de negócio pertence a este
arquivo.
"""

from __future__ import annotations

from fastapi import APIRouter

from urbanopay.api.v1 import health

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)

# Routers ainda não existentes, por SPEC:
#
#   catalog      — sem SPEC (ver A-05 em docs/OPEN-QUESTIONS.md)
#   fare         — SPEC-001
#   identity     — SPEC-002
#   cards        — SPEC-002
#   orders       — SPEC-003
#   payments     — SPEC-003 (inclui o webhook, que nunca passa pelo LLM)
#   approvals    — SPEC-003 (ver A-07)
#   agent        — SPEC-004
#   fulfillment  — SPEC-005
#   tickets      — SPEC-005
#   postsale     — SPEC-005
