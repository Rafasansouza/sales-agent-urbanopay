# UrbanoPay Mobilidade

Plataforma fictícia de mobilidade urbana com um assistente conversacional de
vendas de produtos tarifários, recarga de cartões e emissão de bilhetes
simulados.

> O modelo de linguagem decide o que dizer. O código decide o que pode ser
> feito.

**Estado:** MVP executável ponta a ponta. A jornada de venda do PRD §18 —
conversa em linguagem natural, cálculo tarifário, autenticação, recarga,
pagamento Pix em sandbox, entrega e comprovante — roda com `git clone` +
`docker compose up --build`.

Fora do caminho feliz, por decisão registrada: compra de bilhete (A-05),
recomendação de valor de recarga (A-06) e superfície administrativa de
aprovação (A-07). Ver [limitações conhecidas](#limitações-conhecidas).

---

## O produto

Um passageiro descreve sua necessidade em linguagem natural — por exemplo
*"pego o 303 e depois metrô, tenho meia e vou trabalhar cinco dias indo e
voltando; quanto preciso carregar?"* — e o sistema:

1. interpreta a intenção e extrai os segmentos do trajeto;
2. calcula o custo de forma determinística;
3. recomenda o produto mais adequado e explica o porquê;
4. autentica o passageiro quando a operação exige;
5. valida titularidade, status e perfil oficial do cartão;
6. gera Quote e Order;
7. obtém confirmação explícita, e aprovação humana quando aplicável;
8. gera pagamento Pix em ambiente de teste;
9. aguarda a confirmação do provider ou do backend;
10. executa a recarga ou emite o bilhete;
11. entrega comprovante e atende o pós-venda.

A IA é responsável por interpretação, recomendação e comunicação. Tarifas,
saldo, autenticação, estados transacionais, pagamentos, recargas e emissão de
bilhetes são controlados por código determinístico.

---

## Documentação

A documentação é a fonte de verdade de engenharia. Leia antes de implementar.

| Documento | Papel |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Contexto operacional e invariantes para o desenvolvimento assistido por IA |
| [`docs/prd/PRD.md`](docs/prd/PRD.md) | Escopo e objetivos de produto |
| [`docs/specs/`](docs/specs/) | Comportamento funcional esperado |
| [`docs/adr/`](docs/adr/) | Decisões arquiteturais |
| [`docs/agent-harness/AGENT-HARNESS.md`](docs/agent-harness/AGENT-HARNESS.md) | Modelo de governança do desenvolvimento |
| [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) | Conflitos, lacunas e ambiguidades conhecidos |
| [`docs/MVP-DEMO-RUNBOOK.md`](docs/MVP-DEMO-RUNBOOK.md) | **Como executar e demonstrar o MVP do zero** |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Fluxo de trabalho e convenções |

Autoridade: `PRD → SPEC → ADR → Agent Harness → Implementação`.
Código não contradiz documento aceito. Divergência é reportada, não resolvida
silenciosamente.

### Especificações

| SPEC | Domínio | Estado |
|---|---|---|
| [SPEC-001](docs/specs/SPEC-001-fare-engine.md) | Fare Engine | **Implementada** |
| [SPEC-002](docs/specs/SPEC-002-cards-identity.md) | Cards & Identity | **Implementada** |
| [SPEC-003](docs/specs/SPEC-003-orders-payments.md) | Orders & Payments | **Implementada** (escopo `RECHARGE`) |
| [SPEC-004](docs/specs/SPEC-004-sales-agent-tools.md) | Sales Agent & Tools | **Implementada** (A-05/A-06 fora do escopo) |
| [SPEC-005](docs/specs/SPEC-005-fulfillment-post-sale.md) | Fulfillment & Post-Sale | Implementada (escopo `RECHARGE`) |
| — | Catalog & Products | **Inexistente** (ver A-05) |

### Decisões arquiteturais

| ADR | Assunto | Status |
|---|---|---|
| [001](docs/adr/ADR-001-modular-monolith-monorepo.md) | Monólito modular em monorepo | Aceito |
| [002](docs/adr/ADR-002-langgraph-runtime.md) | LangGraph como runtime do agente | Aceito |
| [003](docs/adr/ADR-003-single-agent.md) | Agente único | Aceito |
| [004](docs/adr/ADR-004-postgresql-pgvector.md) | PostgreSQL autoritativo, pgvector restrito | Aceito |
| [005](docs/adr/ADR-005-probabilistic-deterministic-boundary.md) | Fronteira probabilístico / determinístico | Aceito |
| [006](docs/adr/ADR-006-fastapi.md) | FastAPI | Aceito |
| [007](docs/adr/ADR-007-mercado-pago.md) | Mercado Pago sandbox, Pix, idempotência | Aceito |
| [008](docs/adr/ADR-008-observability.md) | OpenTelemetry e Langfuse | Aceito |
| [009](docs/adr/ADR-009-redis.md) | Redis restrito a estado efêmero | Aceito |
| [010](docs/adr/ADR-010-llm-strategy.md) | Estratégia de LLM e abstração de provider | Aceito |
| [011](docs/adr/ADR-011-web-frontend-stack.md) | Stack do frontend web: Next.js App Router | Aceito |
| [012](docs/adr/ADR-012-persistence-orm-migrations.md) | Persistência, ORM e migrations | Aceito |
| [013](docs/adr/ADR-013-python-toolchain.md) | Toolchain Python | Aceito |
| [014](docs/adr/ADR-014-agent-state-persistence.md) | Persistência do estado conversacional do agente | Aceito |
| [015](docs/adr/ADR-015-openai-llm-provider.md) | Provider de LLM do MVP: OpenAI | Aceito |
| [016](docs/adr/ADR-016-docker-packaging.md) | Empacotamento e execução local em Docker | Aceito |
| [017](docs/adr/ADR-017-package-split.md) | Separação de `apps/` em pacotes por responsabilidade | Aceito |

---

## Arquitetura

Monorepo com monólito modular. Um único Sales Agent conversacional em runtime;
os domínios de negócio são serviços determinísticos expostos por tools
estreitas e tipadas.

```text
Passageiro
  → Sales Agent (LangGraph, LLM)
      → tools estreitas e tipadas
          → Application Services
              → Domain (regras determinísticas)
                  → PostgreSQL (source of truth)
```

Defesa em profundidade: `prompt → schema → service → authorization → state
machine → constraints de banco`.

### Fronteira LLM ↔ domínio

| O LLM pode | Somente o código pode |
|---|---|
| Interpretar intenção | Autenticar e autorizar |
| Extrair contexto e trajeto | Consultar tarifa, saldo e perfil oficial |
| Perguntar campos ausentes | Calcular e classificar |
| Comparar opções e recomendar | Executar máquinas de estado |
| Explicar | Aplicar política de aprovação |
| Escolher qual tool chamar | Definir `amount` e confirmar pagamento |
| | Executar fulfillment e persistir |

Prompt é orientação, nunca segurança.

### Stack

| Camada | Tecnologia | Fonte |
|---|---|---|
| Backend | Python 3.13 + FastAPI + Pydantic | ADR-006, ADR-013 |
| Runtime do agente | LangGraph | ADR-002 |
| Source of truth | PostgreSQL + pgvector | ADR-004 |
| Persistência | SQLAlchemy 2.x + psycopg 3 + Alembic | ADR-012 |
| Estado conversacional | `agent_conversations`, da aplicação — sem checkpointer de framework | ADR-014 |
| Estado efêmero | Redis — **sem consumidor ainda**, fora do Compose | ADR-009, ADR-016 |
| Pagamento | Mercado Pago sandbox, Pix | ADR-007 |
| Observabilidade | OpenTelemetry + Langfuse | ADR-008 |
| LLM | OpenAI atrás do port `LLMProvider`; `FakeLLMProvider` em CI | ADR-010, ADR-015 |
| Ferramentas | uv, Ruff, mypy, pytest | ADR-013 |
| Frontend | Next.js App Router + TypeScript | ADR-011 |
| Empacotamento | Docker Compose: PostgreSQL, job de migration e API | ADR-016 |

### Estrutura do repositório

```text
urbanopay/
├── apps/
│   ├── api/            backend FastAPI
│   └── web/            frontend (placeholder — ADR-011 Proposta)
├── compose.yaml        sobe o MVP inteiro: banco, migration e API
├── docs/               PRD, SPECs, ADRs, harness, runbook, questões abertas
├── infra/              scripts de inicialização do PostgreSQL
├── tests/              unit, integration, e2e, evals
├── scripts/            utilitários de desenvolvimento
├── .claude/            Agent Harness: rules, agents, skills, hooks, settings
└── .github/            CI e templates
```

### Módulos de domínio

Fronteiras declaradas em ADR-001: `agent`, `catalog`, `fare`, `identity`,
`cards`, `orders`, `payments`, `approvals`, `fulfillment`, `tickets`,
`postsale`, `observability`.

Cada módulo em `apps/backend/src/urbanopay/modules/` possui um `README.md` com a
SPEC aplicável, as tools permitidas, as tools proibidas e os bloqueios
conhecidos.

---

## Começar

### Pré-requisitos

**Git e Docker.** Nada mais.

A máquina **não** precisa de Python, uv, PostgreSQL, Alembic ou qualquer
biblioteca da aplicação: tudo roda em container (ADR-016).

### Subir o MVP

```bash
git clone <repo> && cd urbanopay
cp .env.example .env
docker compose up --build
```

Pronto. O `.env.example` é suficiente **sem credencial alguma**: os providers
de LLM e de pagamento sobem em modo fake e a demo roda inteira.

| Endereço | O que é |
|---|---|
| <http://localhost:3000> | **Interface da UrbanoPay** |
| <http://localhost:8000/docs> | Documentação interativa da API |
| <http://localhost:8000/health> | Liveness |
| <http://localhost:8000/ready> | Readiness: banco e migrations |

O roteiro passo a passo está no
[**MVP Demo Runbook**](docs/MVP-DEMO-RUNBOOK.md).

### Usar um modelo de linguagem real

Opcional. Troque duas linhas no `.env` e suba de novo:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=<sua-chave>
OPENAI_MODEL=gpt-5.6-luna
```

A chave vive **exclusivamente no backend** e entra no container por
environment em runtime. Ela nunca chega ao browser, à resposta HTTP, ao log, ao
estado do grafo, ao banco ou à telemetria (ADR-015). A página de chat não tem
campo de API key — ela conversa apenas com esta API.

Sem a chave e com `LLM_PROVIDER=openai`, a aplicação **falha explicitamente**.
Não existe fallback silencioso para o fake.

### Desenvolver (opcional)

Para rodar a suíte a partir do host, aí sim são necessários
[uv](https://docs.astral.sh/uv/) e um PostgreSQL:

```bash
make up          # apenas o PostgreSQL
make setup
make verify-all  # formato, lint, tipos, unit, integração, e2e e evals
```

Em Windows: `.\scripts\dev.ps1 <alvo>`.

### Comandos

| Alvo | O que faz |
|---|---|
| `demo` | Sobe o MVP inteiro em containers: banco, migration e API |
| `build` / `config` | Constrói a imagem / valida o `compose.yaml` |
| `up` / `down` / `logs` / `ps` | Infraestrutura local (`up` sobe só o PostgreSQL) |
| `setup` | Instala o ambiente Python do host a partir do `uv.lock` |
| `api` | Executa a API no host, com reload |
| `fmt` / `fmt-check` | Formatação |
| `lint` / `typecheck` | Lint e tipos |
| `test-unit` / `test-integration` / `test-e2e` / `evals` | Camadas de teste |
| `verify` | `fmt-check` + `lint` + `typecheck` + `test-unit` |
| `verify-all` | `verify` + integração + e2e + evals |
| `migrate` | Aplica migrations no host (no Compose, é um job dedicado) |
| `clean` | Remove caches |

O `Makefile` é a definição canônica e é o que a CI executa. `scripts/dev.ps1`
espelha os mesmos alvos em Windows.

---

## Invariantes críticas

### Financeiras

- Nunca `float` para dinheiro. `Decimal` em Python, `NUMERIC` no PostgreSQL,
  duas casas, `ROUND_HALF_UP`.
- Mensagem do usuário nunca prova pagamento.
- Somente o provider ou o backend estabelece `PaymentStatus.APPROVED`.
- Fulfillment só após pagamento aprovado **e** Order pago.
- Um Order de recarga produz no máximo **um** efeito financeiro.
- Um Order pode ter `1..N` Payments, no máximo **um** `APPROVED`.
- Idempotência obrigatória em toda operação crítica.
- Webhook duplicado nunca produz efeito duplicado.
- Falha de fulfillment após pagamento **nunca** gera nova cobrança.
- Saldo corresponde ao ledger; ledger, saldo e status na mesma transação.
- Timeout na criação de pagamento é estado desconhecido, não falha.

### Tarifárias

- Tarifa oficial vem do banco, nunca da memória do modelo.
- `MEIA` é aplicada por segmento **antes** do desconto de integração.
- `COMMON` tem desconto 0%; `INTEGRATION` usa a regra vigente.
- Vigência com `valid_from` e `valid_until`; histórico nunca é sobrescrito.
- Nenhum erro do Fare Engine permite fallback estimado pelo LLM.

### Segurança

- `card.fare_profile` é a fonte oficial do perfil em transação.
- Titularidade validada server-side.
- Nunca logar OTP, CPF completo, número completo de cartão ou `qr_token`.
- Secrets fora do código, dos prompts e do contexto do LLM.
- Nenhuma capability genérica para o Sales Agent.
- Busca vetorial nunca é autoritativa para preço, saldo ou pagamento.

---

## Governança do desenvolvimento

O `.claude/` materializa o Agent Harness.

| Diretório | Conteúdo |
|---|---|
| `rules/` | Regras globais e regras por caminho de módulo |
| `agents/` | Quatro revisores read-only: spec, arquitetura, segurança, testes |
| `skills/` | `prepare-task`, `implement-spec`, `review-change`, `new-adr`, `verify` |
| `hooks/` | Contexto de sessão, proteção de operações, verificação ao encerrar |
| `settings.json` | Permissions e registro dos hooks |

Enforcement técnico vem de três fontes independentes: `permissions`, hooks e
CI. As regras e o `CLAUDE.md` são orientação comportamental.

Fluxo esperado:

```text
Issue → Branch → /prepare-task → Plano → Implementação → Testes
→ /review-change → /verify → Revisão humana → Commit → PR → CI → Merge humano
```

Nunca se desenvolve diretamente em `main`.

---

## Limitações conhecidas

Detalhadas em [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md). Nenhuma delas
foi preenchida pela implementação — **lacuna documental não vira código
inventado**.

| ID | O que falta, e o efeito no produto |
|---|---|
| **A-05** | Módulo `catalog` sem SPEC. `search_products`, `get_product` e `get_ticket` resolvem para `TOOL_UNAVAILABLE`, e **compra de bilhete não é jornada**. Nenhum produto, preço ou validade é simulado |
| **A-06** | `calculate_usage_cost` sem contrato. **O agente não recomenda valor de recarga**: o cliente informa, e o domínio valida |
| **A-07** | Sem superfície administrativa de aprovação. Acima de R$ 200,00 a jornada **para** em `REQUIRES_APPROVAL` — e parar é o comportamento correto |
| **A-18** | "Pago e não entregável" termina em `RECONCILIATION_REQUIRED`, sem estorno e sem nova cobrança. A resolução administrativa não existe |
| **A-14 / A-15** | Divergências **documentais** da SPEC-003, sem efeito em comportamento |
| **H-05** (parcial) | SDK do Mercado Pago não validado: o adaptador não existe por falta de credencial de teste. `FakePaymentProvider` é o sandbox do MVP |

**Resolvidas nesta entrega:** A-08 (pelo [ADR-011](docs/adr/ADR-011-web-frontend-stack.md)),
H-11 (pelo [ADR-014](docs/adr/ADR-014-agent-state-persistence.md)),
H-05 na parte `langgraph`, H-07 (tolerância a coleta vazia removida de todas as
camadas), H-12 (canal do OTP de demonstração) e a implementação de A-19
(coordenador pós-pagamento).

---

## Fora de escopo

Fonte: PRD §17.

App móvel nativo; WhatsApp, SMS ou OTP real; cartão de crédito ou débito;
dinheiro real; documento fiscal real; integração real com operadores de
transporte; GPS ou roteirização; tarifa dinâmica; gratuidade; vale-transporte
corporativo; reembolso real; antifraude avançado; modelo próprio ou
fine-tuning; arquitetura multiagente complexa; Kubernetes; microservices
distribuídos.

---

## Nota

Projeto fictício, de portfólio. Nenhum dado pessoal real, nenhum dinheiro real
e nenhuma integração real com operadores de transporte. Os pagamentos usam
exclusivamente o ambiente de teste do Mercado Pago; comprovantes e bilhetes são
simulados e sem validade fiscal.

O nome comercial do agente e a identidade visual permanecem pendentes
(PRD §19) e não devem ser inventados pela implementação.
