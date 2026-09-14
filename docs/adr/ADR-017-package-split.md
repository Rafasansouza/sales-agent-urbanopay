# ADR-017 — Separação de `apps/` em pacotes por responsabilidade

**Status:** Aceito
**Data:** 2026-09-14
**Altera:** ADR-001 (estrutura), ADR-012 (localização da foundation)

## Contexto

ADR-001 decidiu monólito modular em monorepo, com `apps/api` e `apps/web`, e as
fronteiras de domínio declaradas como **módulos** dentro de uma única aplicação
Python. Em 2026-09-14 essas pastas foram renomeadas para `apps/backend` e
`apps/frontend` — mudança de nome, registrada no próprio ADR-001.

A avaliação seguinte foi de **legibilidade**: `apps/` mostrava duas pastas, e
tudo o que o produto é — o agente conversacional, os domínios de negócio, a
persistência — vivia indistinto dentro de uma delas. A estrutura real existia
em `src/urbanopay/modules/`, mas não era visível de onde se olha primeiro.

Este ADR torna as camadas **pacotes distribuíveis distintos**, mantendo o
monólito: continua havendo **um processo** servindo HTTP, e nenhuma comunicação
entre camadas passa a ser rede.

## Decisão

Cinco pacotes em `apps/`, com dependência em **uma única direção**:

```text
database  ◀── domains  ◀── agent  ◀── backend        frontend (Next.js)
```

| Pacote | Distribuição | Conteúdo |
|---|---|---|
| `apps/database` | `urbanopay-database` | Foundation de persistência: `Base`, engine, session, Unit of Work. Mais os **contratos transversais** que precisam estar abaixo de todos: o `Protocol` do UoW, o contrato de idempotência, a política de event loop e `DatabaseSettings` |
| `apps/domains` | `urbanopay-domains` | As sete fronteiras de negócio de ADR-001 — `fare`, `identity`, `cards`, `orders`, `payments`, `approvals`, `fulfillment` — cada uma com `domain/`, `application/` e `infrastructure/` |
| `apps/agent` | `urbanopay-agent` | A camada conversacional: catálogo de tools, executor, playbooks, grafo LangGraph, providers de LLM e **o router do próprio endpoint de conversa** |
| `apps/backend` | `urbanopay` | O que resta de aplicação: app FastAPI, composition root, sondas de saúde, webhook de pagamento, superfície de demonstração, coordenador pós-pagamento e provider de pagamento. Mais o **registry de models e as migrations** — ver abaixo |
| `apps/frontend` | — | Next.js (ADR-011) |

### O agente é dono do próprio endpoint

`POST /api/v1/agent/messages` mora em `apps/agent`: quem define o contrato da
conversa é quem implementa a conversa. O `backend` apenas **monta** a aplicação
e inclui o router.

Isso exige que o router não conheça o composition root — senão `agent`
importaria `backend` e o ciclo voltaria. A solução é uma fábrica: o agente
expõe `build_agent_router(provider)` e recebe de quem monta a forma de obter o
serviço. O agente declara o que precisa; o backend decide de onde vem.

### Por que o registry e as migrations ficaram no topo

A intenção inicial era pô-los em `apps/domains`, porque migrations são das
tabelas do negócio. **Não fecha.** O registry existe para reunir *todos* os
modelos num único `MetaData`, e isso inclui `agent_conversations` e
`agent_turn_requests`, que são do agente. Um registry em `domains` importaria
`urbanopay_agent` e inverteria a seta.

A conclusão é a mesma que ADR-012 já registrava por outro caminho — *"`registry`
é o único ponto que conhece todos os módulos"*: **só o topo da direção enxerga
todos sem inverter nada**. Registry e Alembic moram em `apps/backend`.

### O `backend` existe para o que não é do agente

Sondas de saúde, webhook de pagamento, superfície de demonstração e composição.
O **webhook continua fora do agente** — por ADR-002 ele nunca passa pelo grafo,
e agora isso é visível também na estrutura de pacotes, não apenas no código.

### Ciclo evitado por remoção de acoplamento, não por exceção

Duas mudanças tornam a direção única possível, e ambas são melhorias
independentes:

- `build_agent_services` deixa de receber `Settings` e passa a receber os
  valores de política que usa (TTLs e limites). A camada conversacional não
  precisa conhecer a configuração da aplicação inteira para saber o TTL de uma
  Quote;
- `build_llm_provider` deixa de receber `Settings` e passa a receber nome do
  provider, chave e modelo. O provider não precisa da configuração de banco
  para falar com um modelo.

`Settings` continua em `apps/backend`, e **herda** `DatabaseSettings` de
`apps/database`: os campos `POSTGRES_*` têm uma definição só.

## O que este ADR **não** faz

- **Não** extrai serviço. Continua sendo um processo, com chamadas em processo.
  ADR-001 admite extração "só por necessidade real, e sempre via ADR", e
  nenhuma necessidade dessas apareceu;
- **não** cria container novo. O Compose continua com `postgres`, `migrate`,
  `api` e — com ADR-011 — `web`;
- **não** move regra de negócio. Nenhum comportamento muda, e as 834 asserções
  existentes são a prova: elas continuam passando sem alteração de expectativa.

## Consequências

**Positivas.** A primeira coisa que se vê ao abrir o repositório passa a ser o
que o produto é. A direção de dependência deixa de depender só de revisão e de
teste de arquitetura: ela é declarada nos manifestos, e `uv` recusa um ciclo.
Duas acoplagens reais foram removidas no caminho. E fica materialmente mais
barato extrair um serviço no dia em que houver necessidade — sem que isso
signifique que haverá.

**Negativas.** Quatro `pyproject.toml` em vez de um, e um workspace `uv` maior.
Uma mudança que atravessa duas camadas passa a tocar dois pacotes. `apps/database`
carrega, além da persistência, os contratos transversais e `DatabaseSettings` —
um sexto pacote só para eles seria cerimônia, mas o nome da pasta não conta
essa parte da história, e isto fica registrado.

**ADR-012 permanece válido** em tudo: SQLAlchemy 2.x, psycopg 3, Alembic,
Repository, Unit of Work, `Decimal`/`NUMERIC`, constraints e a regra de que
modelos ORM vivem em `infrastructure/` e nunca atravessam a fronteira do
repositório. O que muda é **onde** os diretórios ficam, não como se organizam
por dentro.

## Regra para Claude Code

A direção é `database ← domains ← agent ← backend` e não admite exceção. Se um
import inverter a seta, o problema é o desenho, não o manifesto: extraia um
port em vez de criar dependência de volta. O agente não conhece `Settings`; ele
recebe os valores de que precisa. O webhook de pagamento nunca mora em
`apps/agent`.
