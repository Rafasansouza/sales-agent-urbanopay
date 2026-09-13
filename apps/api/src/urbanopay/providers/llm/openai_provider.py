"""Adaptador OpenAI do port `LLMProvider` (ADR-015).

Este arquivo é o **único** ponto do projeto que conhece a SDK da OpenAI.
Nenhum tipo, objeto ou exceção dela atravessa esta fronteira: o que sai daqui
são os mesmos contratos internos que o `FakeLLMProvider` devolve, e falha de
provider vira `LLMProviderError`. Verificado por teste de arquitetura.

Credencial: `OPENAI_API_KEY` vive exclusivamente no backend, chega como
`SecretStr` e entra no container por environment em runtime. Ela nunca é
enviada a HTML, JavaScript, browser, resposta HTTP, log, estado do grafo,
`ConversationState`, PostgreSQL, telemetria ou `ToolResult`.

Modelo: vem de `OPENAI_MODEL`, nunca do código.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from urbanopay.providers.llm.base import (
    LLMProviderError,
    ModelResponse,
    TurnUnderstanding,
)
from urbanopay.providers.llm.prompt import COMPOSE_INSTRUCTIONS, UNDERSTAND_INSTRUCTIONS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from urbanopay.providers.llm.base import TurnContext, TurnFact

_MAX_OUTPUT_TOKENS: Final = 700


class OpenAILLMProvider:
    """Implementa `LLMProvider` sobre a Responses API da OpenAI.

    O cliente é criado uma vez e reutilizado. A chave nunca é guardada em
    atributo próprio: ela vai direto para a SDK, que é quem precisa dela.
    """

    def __init__(self, *, api_key: str, model: str) -> None:
        if not api_key.strip():
            # Defesa em profundidade: `Settings.require_llm_credentials` já
            # falha no startup, mas construir um provider sem credencial
            # produziria um erro tardio e confuso, no meio de uma conversa.
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

        # Import local: mantém a SDK fora do caminho de import da aplicação
        # quando o provider ativo é o Fake.
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return "openai"

    async def understand(self, *, message: str, context: TurnContext) -> TurnUnderstanding:
        """Classifica e extrai, com structured output tipado.

        `text_format` faz a própria API garantir o schema, o que elimina
        parsing de texto livre para uma decisão que já tem contrato. Schema
        válido ainda **não** implica regra válida: a validação de domínio
        acontece depois, no grafo e nos serviços.
        """
        parsed = await self._parse(
            instructions=UNDERSTAND_INSTRUCTIONS,
            payload=(
                f"Contexto da conversa: {context.model_dump_json()}\nMensagem do cliente: {message}"
            ),
            text_format=TurnUnderstanding,
        )
        return parsed if parsed is not None else TurnUnderstanding()

    async def compose_reply(
        self, *, message: str, context: TurnContext, facts: Sequence[TurnFact]
    ) -> ModelResponse:
        """Transforma fatos já sanitizados em linguagem.

        O modelo recebe **apenas** o que os presenters produziram. Ele não tem
        acesso a entidade de domínio, a linha de banco nem a credencial.
        """
        rendered = [fact.model_dump_json() for fact in facts]
        parsed = await self._parse(
            instructions=COMPOSE_INSTRUCTIONS,
            payload=(
                f"Contexto da conversa: {context.model_dump_json()}\n"
                f"Mensagem do cliente: {message}\n"
                f"Fatos apurados pelo backend: [{', '.join(rendered)}]"
            ),
            text_format=ModelResponse,
        )
        if not isinstance(parsed, ModelResponse):
            # Contrato quebrado pelo provider e nada a salvar: melhor falhar do
            # que devolver ao cliente uma resposta que ninguem escreveu.
            raise LLMProviderError("Resposta do provider veio sem conteudo estruturado.")
        return parsed

    async def _parse(self, *, instructions: str, payload: str, text_format: type[Any]) -> Any:  # noqa: ANN401 - genérico por construção; o chamador conhece o tipo
        """Chamada única à Responses API, com o erro já traduzido.

        Qualquer exceção da SDK é convertida em `LLMProviderError`: exceção de
        terceiro não pode vazar para `application` nem para o grafo, e a
        mensagem original nunca é ecoada ao cliente — ela poderia conter
        fragmento de requisição.
        """
        try:
            response = await self._client.responses.parse(
                model=self._model,
                instructions=instructions,
                input=payload,
                text_format=text_format,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
            )
        except Exception as exc:
            raise LLMProviderError(
                f"Falha ao consultar o provider de LLM: {type(exc).__name__}"
            ) from exc
        return response.output_parsed
