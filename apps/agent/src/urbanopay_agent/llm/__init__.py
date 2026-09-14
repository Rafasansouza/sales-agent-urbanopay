"""Abstração de provider de LLM (ADR-010, ADR-015).

```text
                 ┌─ FakeLLMProvider     ← testes, CI e demo sem credencial
LLMProvider Port ┤
                 └─ OpenAILLMProvider   ← runtime com modelo real
```

`domain`, grafo e tools **não sabem** qual implementação está ativa, e não
existe caminho de negócio especial para o Fake. Nodes nunca instanciam SDK
diretamente: a seleção acontece uma única vez, aqui.
"""

from __future__ import annotations

from urbanopay_agent.llm.base import (
    AgentIntent,
    ConfirmationDecision,
    LLMProvider,
    LLMProviderError,
    ModelResponse,
    TripSegmentDraft,
    TurnContext,
    TurnFact,
    TurnUnderstanding,
)
from urbanopay_agent.llm.fake import FakeLLMProvider

__all__ = [
    "OPENAI",
    "AgentIntent",
    "ConfirmationDecision",
    "FakeLLMProvider",
    "LLMProvider",
    "LLMProviderError",
    "ModelResponse",
    "TripSegmentDraft",
    "TurnContext",
    "TurnFact",
    "TurnUnderstanding",
    "build_llm_provider",
]


OPENAI = "openai"
"""Nome do provider real. Comparado como string, de propósito: o agente não
importa o enum de configuração da aplicação (ADR-017)."""


def build_llm_provider(*, provider: str, api_key: str = "", model: str = "") -> LLMProvider:
    """Seleciona o provider a partir de valores, não de `Settings`.

    Recebe o que usa — nome, chave e modelo — em vez da configuração inteira da
    aplicação (ADR-017). Um provider de linguagem não precisa conhecer a
    configuração de banco para falar com um modelo.

    **Sem fallback silencioso** (ADR-015): `openai` sem chave falha de forma
    explícita, com mensagem acionável e sem imprimir parte alguma dela. Cair no
    Fake em silêncio faria uma demonstração parecer real enquanto responde por
    regra fixa.
    """
    if provider == OPENAI:
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        # Import local: a SDK só é carregada quando de fato será usada.
        from urbanopay_agent.llm.openai_provider import OpenAILLMProvider

        return OpenAILLMProvider(api_key=api_key, model=model)
    return FakeLLMProvider()
