# ADR-015 — Provider de LLM do MVP: OpenAI

**Status:** Aceito
**Data:** 2026-09-13
**Altera:** ADR-010 (apenas a escolha de provider/baseline)
**Resolve:** H-05 na parte de `langgraph`

## Contexto

ADR-010 decidiu a **arquitetura** de acesso ao modelo — abstração `LLMProvider`, contratos
tipados, structured outputs validados por Pydantic **e** por domínio, `FakeLLMProvider` em
CI, sem fallback automático entre providers — e, dentro dela, fixou um baseline concreto:
*"Claude Sonnet 5, configurável"*.

A demonstração do MVP será executada com a API da OpenAI. Trocar o provider real do
runtime é decisão de arquitetura e não pode entrar calada (CLAUDE.md: *"New infrastructure,
providers, major dependencies … require an ADR before implementation"*).

## Decisão

1. **`OpenAILLMProvider` é o provider real do MVP.** O adaptador usa a SDK oficial
   `openai` e a **Responses API**.
2. **`FakeLLMProvider` é o provider de testes e CI**, determinístico, e implementa
   **o mesmo contrato estruturado**.
3. **Um único port** `LLMProvider` é compartilhado pelos dois. `domain`, grafo e tools
   **não sabem** qual implementação está ativa, e **não existe caminho de negócio especial
   para o Fake**.
4. **Anthropic não é implementado nesta etapa.** ADR-010 deixa de nomear Claude Sonnet 5
   como baseline do MVP; a substituibilidade que ele exige continua valendo — e é
   exatamente o que torna esta troca barata.
5. **O modelo nunca é hardcoded**: vem de `OPENAI_MODEL`. Default documentado no
   `.env.example`: `gpt-5.6-luna`.
6. **Encapsulamento total da SDK.** Nenhum tipo, objeto ou exceção da OpenAI atravessa a
   fronteira do provider: não alcança `domain`, `application`, contratos de tool nem
   `ConversationState`. Verificado por teste de arquitetura, como já se faz com SQLAlchemy.

## Segurança da credencial

`OPENAI_API_KEY` existe **apenas no backend**, como `SecretStr`, e entra no container por
environment em runtime.

Nunca é enviada para: HTML, JavaScript, browser, resposta HTTP, log, estado do LangGraph,
`ConversationState`, PostgreSQL, telemetria ou `ToolResult`.

```text
Browser → UrbanoPay API → OpenAILLMProvider → OpenAI API
```

Nunca `Browser → OpenAI API`. A página de demonstração não possui campo de API key: a
configuração acontece exclusivamente no `.env` antes de subir o Compose.

Proibido, por decorrência: `ARG` de build para a chave, cópia de `.env` para dentro da
imagem e qualquer secret gravado em layer Docker.

## Falha sem credencial

`LLM_PROVIDER=openai` com `OPENAI_API_KEY` vazia ou ausente ⇒ **falha explícita**, com a
mensagem `OPENAI_API_KEY is required when LLM_PROVIDER=openai`, **sem imprimir parte
alguma da chave**.

**Não existe fallback silencioso para o Fake.** Um fallback silencioso faria uma
demonstração parecer real enquanto responde por regra fixa — e, pior, tornaria
indistinguível o caso "configurei errado" do caso "está funcionando".

## Structured outputs

O provider real devolve **os mesmos contratos internos** que o Fake para intent,
confirmação, extração estruturada e resposta conversacional. Parsing crítico não fica
baseado em texto livre quando já existe contrato estruturado.

Schema válido **não** implica regra válida (ADR-010): a validação de domínio continua
depois do Pydantic.

## Boundaries preservadas

Nenhuma muda por causa desta decisão. O LLM não calcula saldo, não determina
`fare_profile`, não marca `Payment` como `APPROVED`, não aprova `Approval`, não executa
fulfillment, não recebe CPF nem OTP, não escolhe idempotency key e não alcança tools
`BACKEND_ONLY`.

## O que permanece de ADR-010

Tudo, menos o nome do provider baseline: abstração obrigatória; nodes nunca instanciam SDK
diretamente; contratos internos tipados; structured outputs + Pydantic + validação de
domínio; `FakeLLMProvider` em CI, sem chamada real; sem fallback automático entre
providers; outage do LLM não pode parar webhook, payment ou fulfillment já persistidos;
minimizar PII enviada ao provider.

## Alternativas rejeitadas

| Alternativa | Motivo |
|---|---|
| Manter Anthropic como baseline | A demonstração será feita com OpenAI; manter o documento apontando para outro provider criaria divergência entre documento e execução |
| Implementar os dois providers agora | Dois adaptadores, sendo um sem consumidor real — ADR-010 já rejeita fallback automático, e ADR-013 rejeita dependência sem consumidor |
| Fake como único provider | A jornada nunca exercitaria linguagem natural real; RF-01 do PRD ficaria por demonstrar |
| Chave no frontend | Expõe credencial ao browser. Inegociável |

## Consequências

**Positivas:** a demonstração usa linguagem natural real; a troca de provider custou um
adaptador, provando a substituibilidade que ADR-010 pedia; CI segue sem credencial.

**Negativas:** a SDK `openai` entra como dependência instalada e nunca exercitada em CI —
o adaptador real só é validado manualmente, na demonstração. O identificador de modelo
default (`gpt-5.6-luna`) não é verificado por este repositório: ele é o que a conta do
usuário suportar, e por isso é configurável.

## Regra para Claude Code

A SDK da OpenAI vive apenas dentro do adaptador. O modelo vem de `OPENAI_MODEL`, nunca do
código. A chave é `SecretStr`, só no backend, e nunca aparece em resposta, log, estado ou
telemetria. Sem chave e com `LLM_PROVIDER=openai`, falhe explicitamente — jamais caia no
Fake em silêncio.
