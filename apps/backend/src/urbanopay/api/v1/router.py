"""Agregador dos routers da versão 1 da API.

Cada módulo expõe seu router e o registra aqui. Nenhuma regra de negócio
pertence a este arquivo.

O webhook de pagamento entra por `payments` e **nunca** passa pelo LLM nem pelo
grafo (ADR-002): ele vai direto ao `PaymentService`, que é a única autoridade
capaz de estabelecer `Payment APPROVED`.
"""

from __future__ import annotations

from fastapi import APIRouter

from urbanopay.api.v1 import agent, payments

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(agent.router)
api_v1_router.include_router(payments.router)

# Routers ainda não existentes, por SPEC:
#
#   catalog      — sem SPEC (ver A-05 em docs/OPEN-QUESTIONS.md)
#   fare         — SPEC-001 (hoje alcançado apenas por tool do agente)
#   identity     — SPEC-002 (idem)
#   cards        — SPEC-002 (idem)
#   orders       — SPEC-003 (idem)
#   approvals    — SPEC-003 (ver A-07: falta a superfície administrativa)
#   fulfillment  — SPEC-005 (BACKEND_ONLY; disparado pelo coordenador, A-19)
#   tickets      — SPEC-005 (bloqueado por A-05)
