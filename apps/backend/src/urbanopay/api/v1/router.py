"""Agregador dos routers da versão 1 da API.

Cada pacote expõe seu router e é montado aqui. Nenhuma regra de negócio
pertence a este arquivo.

O router do agente vem de `urbanopay_agent` por **fábrica** (ADR-017): o agente
declara o que precisa, e é aqui — no topo da direção de dependência — que se
decide de onde vem.

O webhook de pagamento entra por `payments` e **nunca** passa pelo LLM nem pelo
grafo (ADR-002): ele vai direto ao `PaymentService`, que é a única autoridade
capaz de estabelecer `Payment APPROVED`. Não é acidente que ele more no
`backend`, e não no pacote do agente.
"""

from __future__ import annotations

from fastapi import APIRouter

from urbanopay.api.dependencies import get_conversation_gateway
from urbanopay.api.v1 import payments
from urbanopay_agent.api import build_agent_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(build_agent_router(get_conversation_gateway))
api_v1_router.include_router(payments.router)

# Routers ainda não existentes, por SPEC:
#
#   catalog      — sem SPEC (ver A-05 em docs/OPEN-QUESTIONS.md)
#   approvals    — SPEC-003 (ver A-07: falta a superfície administrativa)
#   fulfillment  — SPEC-005 (BACKEND_ONLY; disparado pelo coordenador, A-19)
#   tickets      — SPEC-005 (bloqueado por A-05)
