# UrbanoPay Mobilidade

Plataforma fictícia de mobilidade urbana com um assistente conversacional de
vendas de produtos tarifários, recarga de cartões e emissão de bilhetes
simulados.

> O modelo de linguagem decide o que dizer. O código decide o que pode ser
> feito.

**Estado:** bootstrap. A estrutura de engenharia e o Agent Harness estão no
lugar; **nenhuma regra de negócio foi implementada**.

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
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Fluxo de trabalho e convenções |

Autoridade: `PRD → SPEC → ADR → Agent Harness → Implementação`.
Código não contradiz documento aceito. Divergência é reportada, não resolvida
silenciosamente.

### Especificações

| SPEC | Domínio | Estado |
|---|---|---|
| [SPEC-001](docs/specs/SPEC-001-fare-engine.md) | Fare Engine | **Implementada** |
| [SPEC-002](docs/specs/SPEC-002-cards-identity.md) | Cards & Identity | **Implementada** |
| [SPEC-003](docs/specs/SPEC-003-orders-payments.md) | Orders & Payments | Não implementada |
| [SPEC-004](docs/specs/SPEC-004-sales-agent-tools.md) | Sales Agent & Tools | Não implementada |
| [SPEC-005](docs/specs/SPEC-005-fulfillment-post-sale.md) | Fulfillment & Post-Sale | Não implementada |
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
| [011](docs/adr/ADR-011-web-frontend-stack.md) | Stack do frontend web | **Proposta** |
| [012](docs/adr/ADR-012-persistence-orm-migrations.md) | Persistência, ORM e migrations | Aceito |
| [013](docs/adr/ADR-013-python-toolchain.md) | Toolchain Python | Aceito |

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
| Persistência | SQLAlchemy 2.x + psycopg 3 + Alembic (decidido; não implementado) | ADR-012 |
| Estado efêmero | Redis | ADR-009 |
| Pagamento | Mercado Pago sandbox, Pix | ADR-007 |
| Observabilidade | OpenTelemetry + Langfuse | ADR-008 |
| LLM | Claude Sonnet 5 atrás de abstração de provider | ADR-010 |
| Ferramentas | uv, Ruff, mypy, pytest | ADR-013 |
| Frontend | **não decidido** | ADR-011 (Proposta) |

### Estrutura do repositório

```text
urbanopay/
├── apps/
│   ├── api/            backend FastAPI
│   └── web/            frontend (placeholder — ADR-011 Proposta)
├── docs/               PRD, SPECs, ADRs, harness, questões abertas
├── infra/              PostgreSQL + pgvector, Redis, OTel Collector
├── tests/              unit, integration, e2e, evals
├── scripts/            utilitários de desenvolvimento
├── .claude/            Agent Harness: rules, agents, skills, hooks, settings
└── .github/            CI e templates
```

### Módulos de domínio

Fronteiras declaradas em ADR-001: `agent`, `catalog`, `fare`, `identity`,
`cards`, `orders`, `payments`, `approvals`, `fulfillment`, `tickets`,
`postsale`, `observability`.

Cada módulo em `apps/api/src/urbanopay/modules/` possui um `README.md` com a
SPEC aplicável, as tools permitidas, as tools proibidas e os bloqueios
conhecidos.

---

## Começar

### Pré-requisitos

- [uv](https://docs.astral.sh/uv/) — gerencia Python e dependências
- Docker com Compose
- Git

`make` é opcional: em Windows use `.\scripts\dev.ps1`.

### Instalar

```powershell
git clone <repo> && cd urbanopay
Copy-Item .env.example .env    # preencha POSTGRES_PASSWORD
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 up
.\scripts\dev.ps1 api
```

```bash
cp .env.example .env
make setup
make up
make api
```

Verificar:

```bash
curl http://127.0.0.1:8000/api/v1/health
# {"status":"ok","service":"urbanopay-api","version":"0.1.0"}
```

Documentação interativa: `http://127.0.0.1:8000/docs` (apenas com
`APP_ENV=local`).

### Comandos

| Alvo | O que faz |
|---|---|
| `setup` | Instala o ambiente a partir do `uv.lock` |
| `up` / `down` / `logs` / `ps` | Infraestrutura local |
| `api` | Executa a API com reload |
| `fmt` / `fmt-check` | Formatação |
| `lint` / `typecheck` | Lint e tipos |
| `test-unit` / `test-integration` / `test-e2e` / `evals` | Camadas de teste |
| `verify` | `fmt-check` + `lint` + `typecheck` + `test-unit` |
| `migrate` | Indisponível: a persistência decidida em ADR-012 ainda não foi implementada |
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

## Pendências que bloqueiam implementação

Detalhadas em [`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md).

| ID | Bloqueio |
|---|---|
| C-01 | PRD §8 e SPEC-003 §14 discordam sobre a ordem entre confirmação do passageiro e aprovação humana |
| C-02 | Não existe transição de estado que permita segunda tentativa de pagamento após rejeição |
| A-05 | Módulo `catalog` sem SPEC — `TICKET_PURCHASE` não é implementável |
| A-06 | `calculate_usage_cost` exposta em SPEC-004 mas não especificada |
| A-07 | Interface administrativa de aprovação humana sem especificação |
| A-08 | Stack do frontend sem ADR aceito |
| A-13 | Ciclo de vida do `IdempotencyRecord` em `IN_PROGRESS` obsoleto — bloqueia SPEC-003 |
| H-11 | Persistência das tabelas internas do LangGraph exige ADR próprio antes da SPEC-004 |

Nenhuma dessas lacunas deve ser preenchida pela implementação.

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
