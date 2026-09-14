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

from typing import TYPE_CHECKING

from urbanopay.core.config import LLMProviderName
from urbanopay.providers.llm.base import (
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
from urbanopay.providers.llm.fake import FakeLLMProvider

if TYPE_CHECKING:
    from urbanopay.core.config import Settings

__all__ = [
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


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Seleciona o provider a partir da configuração.

    **Sem fallback silencioso** (ADR-015): `LLM_PROVIDER=openai` sem
    `OPENAI_API_KEY` falha de forma explícita, com mensagem acionável e sem
    imprimir parte alguma da chave. Cair no Fake em silêncio faria uma
    demonstração parecer real enquanto responde por regra fixa.
    """
    if settings.llm_provider is LLMProviderName.OPENAI:
        settings.require_llm_credentials()
        # Import local: a SDK só é carregada quando de fato será usada.
        from urbanopay.providers.llm.openai_provider import OpenAILLMProvider

        return OpenAILLMProvider(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.openai_model,
        )
    return FakeLLMProvider()
