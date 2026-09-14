"""Superfície HTTP do agente (ADR-017).

O agente é dono do contrato do próprio endpoint: quem define como se conversa é
quem implementa a conversa. O `backend` apenas monta a aplicação e inclui este
router.
"""

from __future__ import annotations

from urbanopay_agent.api.router import (
    ConversationGateway,
    TurnRequestStore,
    build_agent_router,
)

__all__ = ["ConversationGateway", "TurnRequestStore", "build_agent_router"]
