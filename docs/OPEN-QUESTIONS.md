# Questões Abertas

**Projeto:** UrbanoPay Mobilidade
**Última atualização:** 2026-09-07
**Origem:** análise documental realizada no bootstrap do repositório, atualizada
pela aceitação do ADR-012, pela persistence foundation, pelas implementações
das SPEC-001 e SPEC-002, e pela correção documental da state machine da
SPEC-003 (C-01, C-02, A-03, A-09, A-10, A-13).

Nota de segurança registrada (evolução futura, sem item próprio): a sessão
mantém o mesmo ID após a autenticação (decisão aprovada para o MVP); rotação
de session ID contra fixation é candidata a melhoria quando houver contrato
definido.

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

## ✅ C-01 — Ordem entre confirmação do passageiro e aprovação humana

**Resolvido em 2026-09-07.** A confirmação explícita do cliente **precede** a
aprovação humana. `SPEC-003 §14` foi corrigida e passou a ser a máquina de
estados oficial:

```text
sem aprovação:  DRAFT →(confirma)→ CONFIRMED → PAYMENT_PENDING
com aprovação:  DRAFT →(confirma)→ REQUIRES_APPROVAL →(Approval APPROVED)→ CONFIRMED → PAYMENT_PENDING
```

`CONFIRMED` passa a significar: *todas as confirmações necessárias foram
satisfeitas e o Order está elegível para criação de Payment* — é o único
estado pagável.

**Fundamentos:** hierarquia documental (PRD §8, passos 15 e 16, prevalece sobre
o diagrama da SPEC); aprovação humana só opera sobre intenção comercial
explícita; preserva `create_payment` exigindo `CONFIRMED` (§9) com um único
estado pagável; e o disparador de `DRAFT → REQUIRES_APPROVAL` é um comando que
já existe no conjunto de tools de SPEC-004 §7 (`confirm_order`) — na ordem
inversa, nenhuma tool disparava essa transição.

**Documentos corrigidos:** SPEC-003 §7, §8, §14; PRD §12.

---

## ✅ C-02 — Retentativa de pagamento

**Resolvido em 2026-09-07**, com dois casos explicitamente distintos (SPEC-003
§13.1 e §13.2, derivados de ADR-007):

**Retry técnico** (timeout ou resultado externo desconhecido): mesmo
`payment_id`, mesma idempotency key, nenhum Payment novo, consulta ao provider
antes de qualquer novo POST — nunca retry cego.

**Nova tentativa comercial** (Payment terminou em `REJECTED`, `EXPIRED`,
`CANCELLED` ou `FAILED`): o Order executa `PAYMENT_PENDING → CONFIRMED`
(transição acrescentada a §14) e, a partir dali, um Payment novo pode ser
criado com novo `payment_id` e nova key.

**Modelo:** apenas `Payment` — cada Payment **é** uma tentativa comercial
(§13). Não existe `PaymentAttempt`.

A opção escolhida preserva §9 literalmente (`create_payment` exige
`CONFIRMED`) e mantém o invariante "`PAYMENT_PENDING` ⟺ existe exatamente uma
tentativa ativa", protegido por índice único parcial.

---

## ✅ A-03 — Estados de Order sem transições declaradas

**Resolvido em 2026-09-07**, junto com C-01 e C-02. As três perguntas
originais foram respondidas na correção de SPEC-003 §14:

- **Pix expirado em `PAYMENT_PENDING`** ⇒ o Order volta a `CONFIRMED` (§13.2),
  habilitando nova tentativa. O Order não é encerrado por expiração de Payment.
- **Cancelamento pelo cliente** ⇒ permitido **somente em `DRAFT`**. Por
  ausência de contrato seguro, `REQUIRES_APPROVAL`, `CONFIRMED`,
  `PAYMENT_PENDING` e `PAID` não admitem cancelamento pelo cliente no MVP.
  `REQUIRES_APPROVAL → CANCELLED` ocorre exclusivamente por `Approval
  REJECTED`, com motivo registrado como decorrente da rejeição — nunca
  apresentado como pedido do cliente.
- **`FAILED`** ⇒ **removido do enum do Order**. Nenhuma SPEC lhe dava caminho
  de entrada: falha de pagamento devolve o Order a `CONFIRMED`, falha de
  entrega usa `FULFILLMENT_FAILED` (SPEC-005), e encerramento usa `CANCELLED`
  ou `EXPIRED`. Estado persistido sem caminho válido de entrada não é
  mantido. `Payment.FAILED` continua existindo e é coisa distinta.

O único item de A-03 que **permanece aberto** está agora sob A-07: o Order
`EXPIRED` só é alcançável a partir de `DRAFT` (§5.1), e a política temporal
pós-confirmação foi deliberadamente deixada sem TTL nesta versão — ver A-10.

---

## ✅ A-04 — Composição de viagem exclusivamente de metrô

**Resolvido em 2026-09-07**, na aprovação do plano da SPEC-001, pela
**interpretação conservadora**: dois ou mais segmentos exclusivamente de METRO
resultam em `UNSUPPORTED_TRIP_COMPOSITION` — o erro tipado que SPEC-001 §11
fornece exatamente para composição fora das três classes de §5.

Fundamento: rejeitar não inventa preço; classificar como `COMMON` inventaria
uma regra tarifária que nenhum documento define. O resultado é determinístico
(§13): a mesma composição sempre produz o mesmo erro.

Implementado em `TripClassifier` (SPEC-001), com testes unitários dedicados.
Se o produto um dia definir tarifa para metrô-só multi-segmento, a mudança
exige atualização da SPEC-001, não apenas de código.

Decisões estruturais aprovadas na mesma ocasião:

- segmento METRO com `line_code` → `INVALID_SEGMENT_STRUCTURE` (METRO não
  possui linha, §4);
- BUS sem `line_code` (ou em branco) → `BUS_LINE_REQUIRED`;
- `FARE_LINE_NOT_FOUND` é específico de BUS (linha jamais tarifada); METRO sem
  tarifa vigente é sempre `FARE_NOT_AVAILABLE`.

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

**Estado em 2026-09-07:** a **modelagem de domínio** da aprovação foi resolvida
com C-01 (SPEC-003 §7, §14): estados, transições, efeitos no Order e campos de
auditoria estão definidos, e os serviços de aplicação de aprovação e rejeição
existem. O que permanece aberto é exclusivamente a **superfície** por onde um
humano decide — sem ela, um Order em `REQUIRES_APPROVAL` só avança por chamada
direta ao serviço (o que os testes fazem).

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

## ✅ A-09 — Colisão do nome `APPROVED` em três enums

**Resolvido em 2026-09-07 por eliminação**, não por renomeação:
`Order.APPROVED` foi **removido** do enum (SPEC-003 §6, PRD §12). Com C-01
resolvido, a aprovação humana leva o Order direto a `CONFIRMED`, e o estado
administrativo não precisa ser duplicado no Order.

Restam dois `APPROVED`, semanticamente distintos e em enums separados:

- `Approval.status = APPROVED` — decisão humana registrada;
- `Payment.status = APPROVED` — pagamento confirmado pelo provider.

Em log e em trace, o status permanece sempre qualificado
(`approval.status=APPROVED`, `payment.status=APPROVED`), conforme
`.claude/rules/backend/orders-payments.md`.

---

## ✅ A-10 — TTL de Order, com escopo explícito de MVP `RECHARGE`

**Resolvido em 2026-09-07** (SPEC-003 §5.1):

- Order em `DRAFT` possui TTL configurável, **default 10 minutos**;
- a expiração se aplica **somente enquanto `DRAFT`**: expirado ⇒ `EXPIRED`, e
  não pode ser confirmado (`ORDER_EXPIRED`);
- **após a confirmação explícita não há TTL automático** nesta versão: os
  valores estão congelados, `REQUIRES_APPROVAL` pode aguardar decisão humana e
  `CONFIRMED` pode aguardar a criação do Payment pelo tempo necessário.

Quote mantém TTL próprio, também com default de 10 minutos e validade derivada
de `expires_at` (sem coluna de status).

**Limitação registrada:** esta política vale para `RECHARGE` no MVP. Quando
`TICKET_PURCHASE` for implementado (após A-05), a política temporal deve ser
revisitada, porque preço e produto podem exigir validade diferente.

---

## ✅ A-11 — `FARE_PROFILE_CHANGED`: resultado semântico, com escopo dividido

**Resolvido em 2026-09-07**, na aprovação do plano da SPEC-002, com separação
explícita de responsabilidades:

**SPEC-002 (implementado):** `FARE_PROFILE_CHANGED` é um **sinal semântico de
resultado, não exceção**. `CardService.resolve_official_fare_profile` devolve
`ProfileResolutionResult {official_profile, source=CARD, verified=true,
declared_profile, signal}` — quando o perfil declarado difere do oficial, o
campo `signal` carrega `FARE_PROFILE_CHANGED`. Nada falha: a divergência é um
fato que obriga recálculo, e o perfil declarado nunca substitui o do cartão.

**SPEC-003/004 (pendente):** o recálculo, a invalidação de Quote e o fluxo da
jornada diante do sinal são definidos pelas SPECs transacionais — não pela
SPEC-002. O contrato exato da tool (como o sinal chega ao agente) pertence à
SPEC-004.

---

## ✅ A-12 — Seed fictício × testes obrigatórios

**Resolvido em 2026-09-07**, na implementação da SPEC-002: identidades e
cartões **não têm seed em migration** (decisão aprovada — diferentes das
tarifas, não são dados de referência obrigatórios). O dataset nominal de §13
(Mariana `****4821`/MEIA/21.50, Lucas, Camila BLOCKED, Cliente 4 com dois
cartões) vive como **fixture de teste**, acrescido do cartão `EXPIRED` e do
cenário cross-user que os testes de §14 exigem e o seed sugerido não cobria.

Um seed demonstrativo oficial reproduzível poderá ser criado quando existir a
jornada E2E real (SPEC-004) — decisão adiada, não esquecida.

---

## 🟡 A-14 — Três erros necessários não listados em SPEC-003 §16

**Aberto — descoberto em 2026-09-07, na implementação da SPEC-003.**

A implementação precisou de três recusas determinísticas para as quais a
§16 não nomeia código. Nenhum código novo foi inventado por conta própria: dois
casos **reutilizam** um código já documentado, e apenas um introduz nome novo,
por não haver reuso honesto possível.

| Situação | Tratamento adotado | Código |
|---|---|---|
| `operation_type = TICKET_PURCHASE` (fora do escopo do MVP, §1.1) | recusa explícita; comportamento fictício para produto sem SPEC seria pior | `UNSUPPORTED_OPERATION_TYPE` (**novo**) |
| Valor de recarga inválido — não positivo, mais de duas casas, ou além de `Numeric(12,2)` | validação determinística; nunca arredonda em silêncio | `INVALID_RECHARGE_AMOUNT` (**novo**) |
| Segunda tentativa de Order sobre a mesma Quote (§4) | reuso de código documentado | `INVALID_ORDER_STATE` |

Os dois códigos novos são de **validação de entrada**, não de estado
financeiro, e nenhum deles altera a máquina de estados. A pendência é
documental: a §16 deve ratificá-los ou indicar o código preferido.

**Impacto se não resolvido:** nenhum comportamento fica bloqueado; o risco é o
contrato HTTP expor um `error.code` que a SPEC não declara.

**Quem decide:** produto, ao revisar SPEC-003 §16.

---

## 🟡 A-15 — Idempotência do webhook: mecanismo divergente da §11

**Aberto — descoberto em 2026-09-07, na implementação da SPEC-003.**

A §11 lista `process_payment_webhook` entre as operações que exigem
idempotência, o que sugere um `IdempotencyRecord` como as demais. A
implementação **não** cria esse registro: a idempotência do webhook é a
unicidade `(provider, provider_event_id)` de `payment_events`, garantida por
constraint de banco com `ON CONFLICT DO NOTHING`.

Razão: o webhook não tem key escolhida pelo cliente. Seu identificador natural
é o do próprio evento, e manter dois mecanismos de deduplicação para o mesmo
fato criaria duas verdades a sincronizar — a coerência entre elas passaria a
ser mais um invariante a defender, sem ganho.

O efeito exigido pela SPEC é entregue: **webhook duplicado nunca produz efeito
duplicado**, com teste unit e de integração. A pendência é de redação: a §11
deve reconhecer o mecanismo, ou exigir explicitamente o registro adicional.

**Impacto se não resolvido:** nenhum, funcionalmente. É divergência entre o
texto da SPEC e o mecanismo implementado, e por isso está registrada em vez de
silenciada.

**Quem decide:** produto/arquitetura, ao revisar SPEC-003 §11.

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

**Resolvido documentalmente em 2026-08-29** pela aceitação do ADR-012 e
**validado empiricamente em 2026-09-06** pela persistence foundation:

- SQLAlchemy 2.0.52 (asyncio), psycopg 3.3.5, Alembic 1.19.2 e greenlet 3.5.5
  resolvidos pelo `uv` em Python 3.13.7 e registrados no `uv.lock`;
- conexão assíncrona real contra PostgreSQL 17 coberta por teste de
  integração, incluindo retorno de `Decimal` para `NUMERIC`.

**Permanece não validado:** `langgraph` e SDK do Mercado Pago. A validação é
pré-requisito das SPEC-003 e SPEC-004. Incompatibilidade exige novo ADR, não
alteração silenciosa do ADR-013.

### 🟠 H-11 — Persistência das tabelas internas do LangGraph

ADR-002 prefere checkpoints duráveis em PostgreSQL. O checkpointer oficial do
LangGraph cria e gerencia **as próprias tabelas**, tipicamente por um `setup()`
executado em runtime, fora do controle de migrations versionadas.

Isso colide com a exigência de CLAUDE.md e ADR-004 de que **toda mudança de
schema tenha migration versionada**.

O ADR-012 declara explicitamente que governa **apenas as tabelas pertencentes à
aplicação e ao domínio UrbanoPay**, e deixa esta questão fora do seu escopo.

**O que precisa ser decidido:** como as tabelas internas do LangGraph são
criadas e versionadas — schema separado, adoção pelo Alembic, ou outra
estratégia.

**Ação obrigatória até lá:** nenhum `setup()` automático de schema do LangGraph
pode ser introduzido.

**Encaminhamento:** exige ADR próprio, **antes** da implementação da SPEC-004.

### ✅ A-13 — Ciclo de vida de `IdempotencyRecord` em `IN_PROGRESS`

**Resolvido em 2026-09-07** (SPEC-003 §11.1–§11.3). A chave da solução é que
`IN_PROGRESS` observável existe **apenas** para operações com efeito externo:

- **Operações locais** (`create_order`, `confirm_order`, `approve_order`,
  `reject_order`, processamento local de `PaymentEvent`) usam **uma única
  transação**: reivindicar a key, aplicar o efeito e marcar `COMPLETED` comitam
  juntos. Se a transação falha, registro e efeito falham juntos — **não existe
  `IN_PROGRESS` órfão observável**.
- **`create_payment`** usa **duas fases**, porque nenhuma transação de banco
  pode permanecer aberta durante a chamada HTTP ao provider. Um crash entre as
  fases deixa `Payment CREATED` + `Idempotency IN_PROGRESS` — estado
  **recuperável**, não órfão: a idempotency key é determinística e a
  reconciliação consulta o provider por ela.

Semântica dos status:

- `IN_PROGRESS` — key reivindicada, operação não concluída;
- `COMPLETED` — operação executada e **resultado conhecido**, inclusive quando
  o Payment resultante terminou em estado não aprovado;
- `FAILED` — falha **determinística da própria operação**, reproduzida em
  replay. `Payment.REJECTED` **não** é `Idempotency.FAILED`.

**Sem apropriação automática por tempo.** Encontrar a mesma key em
`IN_PROGRESS` não emite novo POST: retorna `PAYMENT_STATUS_UNKNOWN` e aciona
reconciliação. Um `stale_after` configurável pode existir apenas como gatilho
para **consultar** o provider — o tempo autoriza reconciliação, nunca cobrança.

Escopo `(operation, key)`; payload divergente ⇒ `IDEMPOTENCY_CONFLICT`.
Retenção: registros concluídos **não são removidos** no MVP — são trilha de
auditoria, não cache.

### 🟡 H-07 — Tolerância ao código de saída 5 do pytest

O pytest retorna **código 5** quando nenhum teste é coletado, o que reprovaria
os alvos de teste e o job de CI de uma camada ainda vazia.

**Integration: ✅ resolvida em 2026-09-06.** A persistence foundation trouxe os
primeiros testes reais de integração, e a tolerância foi removida do
`Makefile`, do `scripts/dev.ps1` e do job da CI. Zero testes coletados na
camada `integration` agora **reprova** — que é a proteção que este item pedia.

**Permanece para `e2e` e `evals`**, que seguem sem testes:

- `e2e` — remover ao implementar a primeira jornada completa;
- `eval` — remover ao criar o dataset de SPEC-004 §16.

Pontos a alterar quando chegar a hora: a macro `run_optional_layer` no
`Makefile` e o switch `-AllowNoTests` em `scripts/dev.ps1`.

**Risco enquanto durar:** se a coleta por marcador quebrar nessas duas
camadas, os testes desaparecem silenciosamente e a tolerância mascara o
problema.

Nota registrada na resolução da integration: o PostgreSQL da CI (service
container) **não executa** `infra/postgres/init/01-extensions.sql` — as
extensões `vector`, `pgcrypto` e `btree_gist` não existem lá. Nada as usa
hoje; a migration da primeira SPEC que precisar delas deve criá-las
(`CREATE EXTENSION IF NOT EXISTS ...`).

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

### 🟡 H-12 — Exposição do OTP simulado na jornada demonstrativa

**Afeta:** SPEC-004 (demo E2E)
**Origem:** decisão registrada na implementação da SPEC-002

O OTP simulado é gerado com aleatoriedade criptográfica (`secrets`) e nunca
aparece em resultado de serviço, log ou trace. **Não existe OTP fixo por
configuração** — isso criaria um caminho permanente de autenticação conhecido
(decisão aprovada). Testes usam um `FakeOtpGenerator` determinístico injetado.

Consequência: hoje não há canal pelo qual o usuário da demonstração conheça o
código. **É decisão pendente da demo, não falha da SPEC-002**: quando a
SPEC-004 implementar a superfície de interação, deverá definir a exposição
controlada do OTP simulado (ex.: painel de dev fora do contexto do LLM).
O valor nunca pode chegar ao contexto do agente.

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
