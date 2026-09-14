# ADR-016 — Empacotamento e Execução Local em Docker

**Status:** Aceito
**Data:** 2026-09-13
**Depende de:** ADR-012 (Alembic é autoridade do schema), ADR-013 (Python 3.13, uv)

## Contexto

O MVP precisa ser executável por outra pessoa, em outra máquina, sem preparação manual. A
infraestrutura local até aqui era `infra/docker-compose.yml` com PostgreSQL, Redis e um
OTel Collector, enquanto **a aplicação rodava no host** com `uv run`. Isso exige Python,
uv, Alembic e as bibliotecas instaladas localmente — pré-requisito que o MVP não pode ter.

A experiência alvo é:

```text
git clone → cp .env.example .env → docker compose up --build → sistema no ar
```

Pré-requisitos aceitáveis: **Git e Docker**. Nada além disso.

Existe ainda uma questão de arquitetura real: **quem aplica as migrations?** Depender de um
`alembic upgrade head` manual no host contradiz o alvo, e aplicar migration no startup do
processo da API cria disputa entre réplicas. A-19 já estabeleceu que "worker ou processo
separado" é fronteira que exige ADR — e um job de migration é exatamente isso.

## Decisão

### 1. Imagem da API

`apps/api/Dockerfile`, multi-stage sobre `python:3.13-slim` (ADR-013):

- dependências instaladas de forma reproduzível com `uv sync --frozen`, a partir do
  `uv.lock` versionado — a mesma garantia que a CI usa;
- **nenhum volume com virtualenv do host**; o ambiente vive na imagem;
- usuário **não-root**;
- `HEALTHCHECK` apontando para `/health`;
- **nenhum `.env` copiado para a imagem**, **nenhum `ARG` de secret**, **nenhum segredo em
  layer**. Credencial entra por environment, em runtime.

### 2. Topologia do Compose

`compose.yaml` na raiz, três serviços e nenhum a mais:

```text
postgres  → volume persistente, healthcheck pg_isready
   ↓ service_healthy
migrate   → job: alembic upgrade head; roda até o fim; restart: "no"
   ↓ service_completed_successfully
api       → env_file: .env; healthcheck /health; restart: unless-stopped
```

### 3. Migration como portão de startup

**Um job dedicado, não o processo da API.** Se a migration falhar, a API **não sobe** —
`service_completed_successfully` não é satisfeito. Isso entrega três propriedades:

- schema errado nunca serve tráfego;
- réplicas da API não disputam migration, porque quem migra é um job único;
- **Alembic continua sendo a autoridade do schema.** Nenhum `create_all()`, nenhum
  `setup()` de framework, sob nome algum (ADR-012, ADR-014).

### 4. Serviços deliberadamente ausentes

| Serviço | Decisão |
|---|---|
| **Redis** | **Fora.** ADR-009 o restringe a estado efêmero, e **não existe consumidor no código**. Subir um serviço que ninguém usa é infraestrutura decorativa. Entra quando houver rate limiting ou cache real |
| **OTel Collector** | **Fora.** Telemetria está desligada por padrão e o modo de implantação do Langfuse segue aberto (H-04) |
| **Container web separado** | **Fora.** A página de demonstração é servida pela própria API, em rota `dev`, e por isso **nunca** recebe `OPENAI_API_KEY` |

`infra/docker-compose.yml` é substituído pelo `compose.yaml` da raiz, que preserva os
scripts de init do PostgreSQL por bind mount. `Makefile` e `scripts/dev.ps1` passam a
chamar Docker/Compose no caminho principal.

### 5. Endpoints de saúde

- `GET /health` — **liveness**: o processo está vivo. Sem dependência externa, para que
  banco indisponível não seja lido como processo morto.
- `GET /ready` — **readiness**: banco alcançável e migrations em head.

Nenhum dos dois vaza configuração, credencial ou detalhe interno.

### 6. `.env.example` sobe o sistema sem credencial externa

O arquivo versionado contém **apenas valores fictícios** e é suficiente para executar o
caminho local inteiro: `LLM_PROVIDER=fake`, `PAYMENT_PROVIDER=fake`, OTP em modo dev.

Providers reais são **opt-in por environment** e **nunca** obrigatórios para subir a demo.
O bloco da OpenAI vem presente e vazio, com instrução de ativação (ADR-015).

`.env` permanece no `.gitignore`. Nenhuma chave, token ou senha real é versionada.

### 7. Validação obrigatória em ambiente limpo

Não se aceita como prova o ambiente de desenvolvimento já configurado. A validação roda em
**projeto Compose isolado**, para não destruir volume de desenvolvimento existente:

```text
down -v → build --no-cache → up
→ postgres healthy → migrate em head → api healthy → /health responde
→ jornada E2E contra os containers
→ restart da API preserva ConversationState
→ down + up (sem -v) preserva dados
```

## Alternativas rejeitadas

| Alternativa | Motivo |
|---|---|
| `alembic upgrade head` no entrypoint da API | Duas réplicas disputariam a migration; falha parcial deixaria a API servindo schema errado |
| `create_all()` no startup | Proibido por ADR-012 e ADR-014. Schema nunca é criado por runtime ou framework |
| Manter a API no host, só infra em Docker | É o estado atual, e é exatamente o que exige Python, uv e Alembic na máquina destino |
| Manter Redis e OTel no Compose | Serviços sem consumidor. Aumentam tempo de subida e superfície de falha sem entregar nada |
| Container separado para a página de demo | A página é estática e dev-only; um segundo container só acrescentaria uma fronteira por onde a credencial poderia vazar |

## Consequências

**Positivas:** `git clone` + Docker basta; migration nunca é esquecida nem disputada;
Alembic segue autoridade; a demo sobe sem credencial externa; o ambiente de execução passa
a ser reprodutível e igual para todos.

**Negativas:** o ciclo de desenvolvimento ganha um passo de build de imagem; `make`/`dev.ps1`
passam a ter dois caminhos (container para execução, host para ferramentas de qualidade); e
a CI continua executando Python diretamente — ela valida `compose config` e `docker build`,
mas não roda a suíte dentro dos containers.

## Regra para Claude Code

A execução principal do MVP não depende de Python, uv, Alembic ou pytest no host. Migration
é job dedicado, nunca entrypoint da API, nunca `create_all()`. Secret não entra em imagem,
em `ARG` nem em layer — só em environment de runtime. Não acrescente serviço ao Compose sem
consumidor real no código.
