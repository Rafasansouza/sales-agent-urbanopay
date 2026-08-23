# Questões Abertas

**Projeto:** UrbanoPay Mobilidade
**Última atualização:** 2026-08-23
**Origem:** análise documental realizada no bootstrap do repositório.

## Propósito

Registro rastreável de conflitos, lacunas e ambiguidades identificados entre
PRD, SPECs e ADRs, além das pendências que o próprio PRD §19 declara.

Regras de uso:

- Este documento **não decide nada**. Ele apenas torna a pendência visível.
- Nenhum item aqui pode ser resolvido escrevendo código. A resolução acontece
  em PRD, SPEC ou ADR.
- Um item que bloqueia uma SPEC deve ser resolvido **antes** de a SPEC ser
  implementada.
- Quando um item for resolvido, registre aqui o documento e a data que o
  resolveram, mantendo o histórico.

## Legenda de severidade

| Símbolo | Significado |
|---|---|
| 🔴 | Conflito ou lacuna que impede implementação correta. |
| 🟠 | Lacuna relevante: implementação exigiria inventar regra de negócio. |
| 🟡 | Ambiguidade ou risco a alinhar, sem bloqueio imediato. |
| ✅ | Resolvido. |

---

## 🔴 C-01 — Ordem entre confirmação do passageiro e aprovação humana

**Bloqueia:** SPEC-003, SPEC-004
**Fontes em conflito:** PRD §8 vs SPEC-003 §14

PRD §8 ordena: passo 14 cria `Order` em `DRAFT`, passo 15 obtém a **confirmação
explícita do passageiro**, passo 16 exige **aprovação humana** para recarga
acima de R$ 200,00.

SPEC-003 §14 define a ordem inversa:

```text
DRAFT → REQUIRES_APPROVAL → APPROVED → CONFIRMED → PAYMENT_PENDING
```

Ou seja, a aprovação administrativa ocorre **antes** da confirmação do
passageiro.

**O que precisa ser decidido:** para uma recarga acima de R$ 200,00, a
confirmação do passageiro ocorre antes ou depois da aprovação operacional.

**Impacto:** define a máquina de estados de `Order`, o comportamento de
`confirm_order`, o ponto de aplicação de `ApprovalPolicy` e o cumprimento de
RF-12.

---

## 🔴 C-02 — Retentativa de pagamento sem transição de estado definida

**Bloqueia:** SPEC-003
**Fontes:** SPEC-003 §9 vs SPEC-003 §13 e §14

SPEC-003 §9 exige `Order CONFIRMED` para criar um `Payment`. SPEC-003 §13
permite que um Order tenha `1..N` Payments e determina que uma nova tentativa
após rejeição use novo `payment_id` e nova idempotency key.

Porém, ao criar o primeiro Payment o Order passa a `PAYMENT_PENDING`, e §14
**não define nenhuma transição de volta a `CONFIRMED`**. Lido literalmente, todo
segundo pagamento é rejeitado com `INVALID_ORDER_STATE`.

**O que precisa ser decidido:** existe transição
`PAYMENT_PENDING → CONFIRMED` quando o Payment termina em
`REJECTED`/`EXPIRED`/`FAILED`, ou a criação de Payment passa a ser permitida em
`PAYMENT_PENDING` desde que não exista Payment `APPROVED`.

**Impacto:** sem isso a jornada "pagamento rejeitado e nova tentativa" —
exigida nos testes de SPEC-003 §17 — é inalcançável.

---

## 🟠 A-03 — Estados de Order sem transições declaradas

**Bloqueia:** SPEC-003
**Fonte:** SPEC-003 §6 vs §14

O enum de §6 inclui `FAILED`, `CANCELLED` e `EXPIRED`. No diagrama de §14,
`FAILED` **não possui nenhuma aresta de entrada**, e `CANCELLED`/`EXPIRED` só
são alcançáveis a partir de `DRAFT`.

**O que precisa ser decidido:**

- Para qual estado vai o Order quando o Pix expira em `PAYMENT_PENDING`?
- `CONFIRMED` e `PAYMENT_PENDING` podem ser cancelados pelo passageiro?
- Quando `FAILED` é alcançado, e como ele se distingue de
  `FULFILLMENT_FAILED`?

---

## 🟠 A-04 — Composição de viagem exclusivamente de metrô é indefinida

**Bloqueia:** SPEC-001
**Fonte:** SPEC-001 §5

As três classes cobrem: `SINGLE` (exatamente um segmento), `COMMON` (dois ou
mais segmentos exclusivamente de ônibus) e `INTEGRATION` (ao menos um ônibus e
ao menos um metrô).

Dois ou mais segmentos exclusivamente de metrô **não pertencem a nenhuma
classe**. O erro `UNSUPPORTED_TRIP_COMPOSITION` existe em §11 e é o candidato
natural, mas a regra de classificação não afirma isso, e §13 exige
determinismo ("mesma entrada + mesmas regras ⇒ mesmo resultado").

**O que precisa ser decidido:** essa composição é erro tipado, ou é `COMMON`
com desconto 0%.

---

## 🟠 A-05 — Módulo `catalog` sem SPEC

**Bloqueia:** SPEC-004 parcialmente, e toda a jornada `TICKET_PURCHASE`
**Fontes:** ADR-001, PRD §6.4, PRD §19, SPEC-004 §7

`catalog` é módulo declarado em ADR-001 e expõe as tools `search_products` e
`get_product` (SPEC-004 §7). O PRD §6.4 lista quatro produtos do MVP: Bilhete
Unitário QR, Passe Diário, Pacote 10 Viagens e Recarga Livre. Não existe SPEC
correspondente.

O PRD §19 mantém explicitamente pendentes as regras detalhadas de Passe Diário
e de Pacote 10 Viagens, e a validade exata do QR/bilhete — exatamente o
conteúdo que essa SPEC precisaria definir.

**Consequência prática:** a operação `RECHARGE` é implementável a partir das
SPECs existentes; `TICKET_PURCHASE` **não é**, sem inventar regra de negócio.

**Encaminhamento:** requer uma `SPEC-006 — Catalog & Products`, escrita como
decisão de produto e não derivada pela implementação.

---

## 🟠 A-06 — Tool `calculate_usage_cost` sem especificação

**Bloqueia:** SPEC-004; requer complemento em SPEC-001
**Fontes:** SPEC-004 §7 vs SPEC-001

SPEC-004 §7 expõe `calculate_usage_cost` no grupo Fare, e o PRD define o intent
`CALCULATE_RECHARGE_NEED`, ilustrado em PRD §4 por "cinco dias indo e voltando".
SPEC-001 especifica apenas `calculate_trip_fare`.

**O que precisa ser decidido:** contrato de entrada (frequência, número de
dias, ida e volta, horizonte semanal ou mensal), contrato de saída, tratamento
de saldo já existente no cartão e casos determinísticos obrigatórios.

---

## 🟠 A-07 — Interface de aprovação humana sem especificação

**Bloqueia:** SPEC-003 no caminho `REQUIRES_APPROVAL`
**Fontes:** SPEC-003 §7, PRD §19, ADR-001

SPEC-003 §7 define a entidade `Approval` e proíbe o Sales Agent de aprovar ou
rejeitar. O PRD §19 mantém "detalhes finais da interface administrativa de
aprovação" como pendência.

Não existe SPEC, endpoint definido, nem aplicação administrativa na estrutura
de ADR-001 (`apps/api` e `apps/web` apenas).

**O que precisa ser decidido:** quem aprova, por qual superfície (endpoint
autenticado, tela administrativa, aplicação separada), com qual modelo de
autorização e qual trilha de auditoria.

---

## 🟠 A-08 — Stack do frontend sem ADR

**Bloqueia:** qualquer implementação em `apps/web`
**Fontes:** ADR-001, AGENT-HARNESS §3

ADR-001 exige `apps/web` e o harness prevê `.claude/rules/frontend/web.md`, mas
nenhum documento aceito define a stack. O `.gitignore` cita `.next/` e
`node_modules/`, o que sugere Next.js — indício, não decisão.

**Encaminhamento:** `ADR-011` foi criado com status **Proposta**. Enquanto não
for aceito, `apps/web/` contém apenas documentação.

---

## 🟡 A-09 — Colisão do nome `APPROVED` em três enums

**Afeta:** SPEC-003, observabilidade
**Fontes:** PRD §12, SPEC-003 §6 e §7, ADR-007

`Order.status = APPROVED` (aprovação administrativa), `Approval.status =
APPROVED` e `Payment.status = APPROVED` coexistem. PRD §12 e SPEC-003 §6 já
determinam enums separados, portanto não há conflito documental — mas o risco de
confusão em código, em log e em trace é alto.

**Encaminhamento:** regra de nomenclatura registrada em
`.claude/rules/backend/orders-payments.md`. Vale considerar renomear o estado
administrativo do Order (por exemplo `APPROVAL_GRANTED`) via ADR.

---

## 🟡 A-10 — TTL de Order indefinido

**Afeta:** SPEC-003
**Fontes:** SPEC-003 §4, PRD §19

SPEC-003 §4 sugere TTL inicial de 10 minutos para `Quote`. Existem o estado
`Order EXPIRED` e o erro `ORDER_EXPIRED`, mas nenhum TTL de Order é definido.

Coerente com PRD §19, que mantém "TTL definitivo de Quote/Order" como
pendência. Nenhum valor foi adotado no `.env.example`.

---

## 🟡 A-11 — `FARE_PROFILE_CHANGED`: erro tipado ou evento de domínio?

**Afeta:** SPEC-002, SPEC-001
**Fonte:** SPEC-002 §8

A SPEC diz "retornar evento/erro semântico `FARE_PROFILE_CHANGED`". As duas
opções têm contratos e efeitos distintos: um erro tipado interrompe a chamada
de tool e exige novo fluxo; um evento de domínio permite prosseguir com
recálculo transparente.

**O que precisa ser decidido:** uma das duas naturezas, e o comportamento
esperado do agente em cada caso.

---

## 🟡 A-12 — Seed fictício não cobre os testes obrigatórios

**Afeta:** SPEC-002
**Fonte:** SPEC-002 §13 vs §14

O seed sugerido em §13 contempla cartões `ACTIVE` e `BLOCKED`. Os testes
obrigatórios de §14 exigem também cartão `EXPIRED` (caso 7) e cenário
cross-user (caso 8).

Contornável via fixtures de teste, mas vale alinhar o seed quando SPEC-002 for
implementada, para que o ambiente de demonstração cubra os mesmos cenários.

---

## Pendências declaradas pelo próprio PRD §19

Reproduzidas aqui apenas para consolidar a visão. A fonte permanece o PRD.

| Item | Bloqueia |
|---|---|
| Nome comercial final do agente | Documentação de produto, README, prompts |
| Identidade visual | `apps/web` |
| Regras detalhadas do Passe Diário | SPEC-006 (ver A-05) |
| Regras detalhadas do Pacote 10 Viagens | SPEC-006 (ver A-05) |
| Validade exata do QR/bilhete | SPEC-005, SPEC-006 |
| TTL definitivo de Quote/Order | SPEC-003 (ver A-10) |
| Detalhes da interface administrativa de aprovação | SPEC-003 (ver A-07) |

---

## Pendências de materialização do harness e da infraestrutura

### ✅ H-01 — Carregamento de `.claude/rules/`

**Resolvido em 2026-08-23.** A hipótese levantada na análise inicial — de que
`.claude/rules/` não seria descoberto automaticamente — estava **incorreta**. O
Claude Code descobre recursivamente os arquivos Markdown em `.claude/rules/`.

Estrutura adotada em consequência:

- regras globais em `.claude/rules/*.md`, **sem** `paths:` no frontmatter, para
  carregamento global;
- regras específicas de módulo em `.claude/rules/backend/` e
  `.claude/rules/frontend/`, **com** `paths:` no frontmatter.

Nenhum `@import` dessas regras foi adicionado ao `CLAUDE.md`.

### 🟡 H-02 — Hooks Python em Windows

Os hooks do harness são scripts Python executados em ambiente Windows. Eles
foram escritos para **falhar aberto**: qualquer erro inesperado resulta em
saída 0, sem bloquear a sessão. O bloqueio é intencional e restrito aos casos
previstos em AGENT-HARNESS §9 e §10.

Pendência: validar o comportamento dos hooks em CI Linux, quando houver
execução do harness fora da máquina de desenvolvimento.

### 🟡 H-03 — `verify_before_stop.py` é advisório

O hook `Stop` executa verificações rápidas e **reporta** o resultado, sem
bloquear o encerramento. Um hook `Stop` bloqueante em falha de lint pode
aprisionar a sessão. A suíte completa permanece em `/verify` e na CI, conforme
AGENT-HARNESS §10.

Pendência: confirmar se esse comportamento advisório é suficiente ou se algum
subconjunto (por exemplo, detecção de secret em arquivo alterado) deve
bloquear.

### 🟡 H-04 — Modo de implantação do Langfuse

ADR-008 exige Langfuse, mas não define self-hosted x cloud. O bootstrap deixou
Langfuse **desligado por padrão** e configurável por ambiente, sem containers
próprios no `docker-compose`, porque o self-host acrescenta ClickHouse, MinIO,
Redis adicional e a aplicação web.

**O que precisa ser decidido:** modo de implantação para desenvolvimento e para
demonstração.

### 🟡 H-05 — Compatibilidade das dependências estruturais com Python 3.13

ADR-013 fixou Python 3.13. As dependências instaladas no bootstrap
(FastAPI, Uvicorn, Pydantic, Ruff, mypy, pytest) são compatíveis.

**Não validado:** `langgraph`, driver PostgreSQL, `pgvector` e SDK do Mercado
Pago. A validação é pré-requisito de ADR-012 e da implementação de SPEC-004.
Incompatibilidade exige novo ADR, não alteração silenciosa do ADR-013.

### 🟡 H-07 — Tolerância ao código de saída 5 do pytest

As camadas `integration`, `e2e` e `evals` ainda não possuem testes, porque as
SPEC-001 a SPEC-005 não foram implementadas. O pytest retorna **código 5**
quando nenhum teste é coletado, o que reprovaria os alvos de teste e o job de
CI correspondente.

Solução adotada: `Makefile`, `scripts/dev.ps1` e o job `test-integration` da CI
toleram **exclusivamente** o código 5, emitindo aviso explícito. Qualquer outro
código de saída continua reprovando.

**Risco:** se um dia a coleta por marcador quebrar, os testes daquela camada
desaparecem silenciosamente e a tolerância mascara o problema.

**Ação obrigatória:** remover a tolerância de cada camada assim que ela tiver
o primeiro teste. Especificamente:

- `integration` — ao implementar a primeira SPEC com persistência;
- `e2e` — ao implementar a primeira jornada completa;
- `eval` — ao criar o dataset de SPEC-004 §16.

Pontos a alterar: a macro `run_optional_layer` no `Makefile`, o switch
`-AllowNoTests` em `scripts/dev.ps1` e o passo correspondente em
`.github/workflows/ci.yml`.

### ✅ H-08 — Deprecação do `httpx` no TestClient do Starlette

**Resolvido em 2026-08-23.**

A suíte emitia `StarletteDeprecationWarning: Using httpx with
starlette.testclient is deprecated; install httpx2 instead`.

O `starlette.testclient` importa `httpx2` e só recorre a `httpx` emitindo
depreciação. A dependência de desenvolvimento foi migrada de `httpx` para
`httpx2` (2.12.0), o `uv.lock` foi atualizado e o aviso desapareceu.

Nenhum teste precisou ser reescrito: `fastapi.testclient.TestClient` continua
sendo a interface usada, e a troca é transparente para o código de teste.

### 🟡 H-09 — Logs de acesso do uvicorn não são JSON

`configure_logging` produz JSON estruturado para os logs da aplicação,
verificado no bootstrap:

```json
{"timestamp": "...", "level": "INFO", "logger": "urbanopay.main",
 "message": "aplicacao iniciada", "app_env": "local", ...}
```

Porém o uvicorn configura seus próprios loggers (`uvicorn.access`,
`uvicorn.error`) com handlers próprios, que não passam pelo formatador da
aplicação. O resultado é saída mista:

```text
INFO:     127.0.0.1:64041 - "GET /api/v1/health HTTP/1.1" 200 OK
```

ADR-008 determina "logs JSON estruturados correlacionados por `trace_id`".
Enquanto os logs de acesso ficarem fora do formato, a correlação por
`trace_id` não cobre a camada HTTP.

**Ação:** sobrescrever a configuração de log do uvicorn, ou substituir os logs
de acesso por middleware próprio instrumentado. A decisão pertence à tarefa de
instrumentação de observabilidade, junto com o restante do ADR-008.

### 🟠 H-10 — `CODEOWNERS` ausente

O bootstrap chegou a criar `.github/CODEOWNERS`, mas o arquivo foi **removido
antes do commit**: ele continha apenas `@OWNER_PLACEHOLDER`, e versionar um
placeholder produz uma falsa sensação de governança — o GitHub ignora handles
inexistentes, então a exigência de review não teria efeito algum.

**Ação:** criar `.github/CODEOWNERS` quando o repositório remoto no GitHub for
configurado e o owner real estiver definido.

Caminhos que devem ter owner explícito, pela criticidade:

- `/docs/prd/`, `/docs/specs/`, `/docs/adr/`, `/docs/agent-harness/` e
  `/CLAUDE.md` — documentos de autoridade;
- `/.claude/` — permissions, hooks e regras são enforcement técnico;
- `/.github/` — remover ou afrouxar check da CI viola invariante do harness
  (AGENT-HARNESS §16);
- `modules/orders/`, `modules/payments/`, `modules/approvals/`,
  `modules/fulfillment/` e `providers/payments/` — domínios financeiros, com
  maior risco de efeito irreversível.

**Dependência:** enquanto não existir `CODEOWNERS` com handles reais, a branch
protection da `main` só consegue exigir PR e status checks, não revisão de
pessoa responsável. Isso enfraquece o item "código gerado por IA passa por
review" (AGENT-HARNESS §16).

### 🟡 H-06 — `make` ausente no ambiente de desenvolvimento

O `Makefile` é a definição canônica dos comandos e é o que a CI executa, mas
`make` não está instalado na máquina de desenvolvimento Windows atual. O
wrapper `scripts/dev.ps1` cobre os mesmos alvos.

Risco: divergência entre os dois arquivos. Mitigação registrada em
`scripts/README.md`: alterar um exige alterar o outro na mesma mudança.
