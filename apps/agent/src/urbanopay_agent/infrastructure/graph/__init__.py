"""Adaptador LangGraph do Sales Agent (ADR-002, ADR-014).

**Única** pasta do projeto autorizada a importar `langgraph`. O contrato da
aplicação é `ConversationState`; o grafo se adapta a ele, não o contrário.
Nenhum tipo do framework atravessa esta fronteira — verificado por teste de
arquitetura.
"""

from __future__ import annotations

from urbanopay_agent.infrastructure.graph.graph import LangGraphTurnRunner

__all__ = ["LangGraphTurnRunner"]
