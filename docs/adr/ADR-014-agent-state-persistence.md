# ADR-014 — Persistência do Estado Conversacional do Sales Agent

**Status:** Aceito
**Data da proposta:** 2026-09-08
**Data da aceitação:** 2026-09-08
**Resolve:** H-11
**Desbloqueia:** Etapa 2 da SPEC-004 (§22) — **arquiteturalmente**. A
introdução do LangGraph continua dependendo da validação de compatibilidade com
Python 3.13 registrada em **H-05**, que permanece aberta.

## Contexto

A Etapa 1 da SPEC-004 está implementada: catálogo fechado de 16 tools,
visibilidade, autorização, envelopes, guardas de contexto, vínculo de
confirmação, política de idempotency keys e composition root — tudo
determinístico. O `ConversationState` que a acompanha é **efêmero**: não existe
tabela, migration, repositório, checkpointer, LangGraph ou dependência nova.

A Etapa 2 introduz o grafo, e não pode começar sem que a persistência do estado
conversacional esteja decidida, porque a decisão define **quem é dono do schema
do banco**.

Os documentos aceitos deixavam isso explicitamente em aberto: ADR-002 exige
"checkpoints duráveis, preferência por PostgreSQL" sem nomear quem cria as
tabelas; ADR-004 e CLAUDE.md exigem migration versionada para **toda** mudança
de schema; ADR-012 governa "apenas as tabelas da aplicação e do domínio
UrbanoPay" e remete esta decisão a ADR separado; e H-11 registra a colisão,
proibindo qualquer `setup()` automático de schema até que a decisão exista.

## Problema

A pergunta de H-11 — *"como as tabelas internas do LangGraph são criadas e
versionadas?"* — carrega uma premissa que não se sustenta: a de que adotar
LangGraph implica adotar um checkpointer gerenciado pelo framework.

Não implica. Um grafo compilado **sem** checkpointer é operação suportada e
completa: o estado entra como argumento da invocação e sai como retorno. O
checkpointer só é necessário para `interrupt`/`resume`, replay de super-steps e
memória entre invocações gerenciada pelo framework — nenhum é requisito do MVP,
e o terceiro é exatamente o que a aplicação precisa fazer sozinha para
respeitar SPEC-004 §3.1.

A pergunta correta é: **precisamos de tabelas do LangGraph?** Quatro conflitos
tornam a resposta consequente.

**P1 — Migration versionada é regra absoluta.** O checkpointer PostgreSQL
oficial do LangGraph cria e gerencia as próprias tabelas por um `setup()` de
runtime, com cadeia de migrations interna versionada pela biblioteca. A
exigência da CLAUDE.md não é escopada; adotá-lo exigiria **exceção formal a uma
regra absoluta**, que não pode ser aberta por omissão.

**P2 — `alembic check` quebra (conflito mecânico, verificado).**
`db/migrations/env.py` usa `target_metadata` de `db/registry.py`, com
`include_schemas=False` e **sem** `include_object`/`include_name`; e
`test_alembic_check_sem_divergencia` roda `alembic check` como gate (ADR-012
regra 4). Tabelas de framework no schema default seriam lidas como tabelas a
remover: o gate passa a falhar, e um autogenerate futuro produziria
`drop_table` sobre elas — **migration destrutiva por acidente**. Conviver
exigiria afrouxar o `env.py`, enfraquecendo a rede que ADR-012 R9 instalou.

**P3 — Checkpoint de framework serializa o `State` inteiro.** O padrão
idiomático do LangGraph acumula mensagens no `State`, e o checkpointer grava o
que estiver lá — inclusive a mensagem em que o cliente digitou CPF ou OTP. A
defesa de SPEC-004 §13.1 é de **fluxo**, aplicada no transporte antes do
modelo; ela não protege um mecanismo que serializa o estado por conta própria.

**P4 — `interrupt` aberto aguardando humano seria fila de trabalho durável.**
A-07 declara que a superfície administrativa de aprovação não existe, SPEC-003
não dá TTL ao `Approval` e A-10 permite que `REQUIRES_APPROVAL` aguarde decisão
humana indefinidamente. Um checkpoint suspenso por horas ou dias contraria a
própria cláusula seguinte do ADR-002 ("o estado do grafo não é source of
truth") e o que A-19 sujeita a ADR próprio ("qualquer mecanismo assíncrono
persistente").

## Decisão

Adotar **application-owned conversational state persistence**.

1. **A aplicação UrbanoPay é proprietária do estado conversacional durável.**
2. **A persistência futura usará a tabela `agent_conversations`, versionada
   exclusivamente por Alembic**, sob as mesmas regras de ADR-012.
3. **LangGraph é runtime de orquestração, não proprietário de persistência.** O
   grafo é compilado **sem checkpointer**.
4. **Não serão usados no MVP:** tabelas nativas de checkpoint do LangGraph;
   `.setup()` ou `create_all()` que altere schema; criação automática de schema
   por framework; `MemorySaver` como solução de produção; Redis como source of
   truth; JSONB genérico carregando graph state.
5. **`interrupt`/`resume` não são usados.** A confirmação do passageiro é
   fronteira de turno; a aprovação humana é assíncrona e ocorre fora do grafo.
6. **A proibição de H-11 vira regra permanente:** nenhum schema é criado por
   runtime ou por framework.

Este ADR **não implementa nada**. Tabela, migration, repositório e grafo
pertencem à Etapa 2.

## Alternativas consideradas

**A — Application-owned (adotada).** Tabela da aplicação, ORM em
`modules/agent/infrastructure/`, repositório, migration Alembic. LangGraph sem
checkpointer: a cada turno o runner carrega o estado, converte para o `State`
do grafo, invoca, converte de volta e persiste. Ownership integral do schema;
`alembic check` verde; PII controlada coluna a coluna; trocar de orquestrador
não move dado. Custo: escrever repositório, mapeamento e uma migration. Abre
mão de `interrupt`/`resume`, time-travel e replay por super-step.

**B — Checkpointer PostgreSQL oficial do LangGraph.** Rejeitada: concentra P1,
P2 e P3. Acrescenta ownership dividido — duas cadeias de migration no mesmo
banco, portanto duas respostas para "em que versão está este schema" — e um
bump de biblioteca pode aplicar migration interna em runtime, isto é, **mudança
de schema sem PR, sem revisão e sem downgrade**. A granularidade é por
super-step, não por turno: mais escritas, estado intermediário sem leitor, e a
tentação de retomar *dentro* de um turno, o que reexecutaria side effects.

> Os detalhes de nomes de tabela, obrigatoriedade de `setup()` e migrations
> internas refletem o comportamento conhecido do pacote e **não foram
> verificados contra versão fixada**, porque a dependência não está instalada.
> A decisão não depende deles: decorre de P1, P2 e P3, que valem para qualquer
> framework que crie schema por conta própria.

**C — Ambos.** Rejeitada: herda os custos de B e acrescenta **duas
representações do mesmo fato**. Qual é a verdade sobre "esta conversa tem
confirmação pendente" — a coluna ou o checkpoint? Se for a coluna, o checkpoint
é peso morto com aparência de autoridade; se for o checkpoint, viola-se a
decisão 1. O repositório já rejeitou esse padrão duas vezes pelo mesmo motivo:
**A-15** ("dois mecanismos de deduplicação para o mesmo fato criariam duas
verdades a sincronizar") e **A-21** ("um alias transformaria a divergência em
duas verdades permanentes"). O único benefício real seria habilitar
`interrupt`/`resume`, que P4 mostra não querermos.

**D — Somente memória.** Rejeitada como solução durável: a conversa não
sobrevive a restart, deploy ou segundo worker. Aceita como **artefato de
teste** — com o repositório atrás de um port, uma implementação em memória
permite rodar unit tests e evals sem banco, no padrão de `FakeLLMProvider` e
`FakePaymentProvider`.

## Rationale

1. **É a única alternativa que não exige exceção a uma regra absoluta.** B e C
   exigiriam exceção à CLAUDE.md e afrouxamento do `env.py`.
2. **Dissolve H-11 em vez de administrá-lo.** Sem tabela de framework, não há
   pergunta sobre como versioná-la.
3. **O que se abre mão, não se quer.** `interrupt`/`resume` seria errado para
   aprovação humana (P4) e é desnecessário para a confirmação, que já é
   fronteira de turno por construção da SPEC-004 §9.1.
4. **Implementa o princípio final do próprio ADR-002** — *"LangGraph sabe onde
   estamos; Domain Services sabem o que é permitido; PostgreSQL sabe o que
   aconteceu."* Uma tabela da aplicação guardando "onde estamos", sob as mesmas
   regras das demais verdades do projeto, é a leitura literal dessa frase.

## Relação com ADR-002

**ADR-002 não é reescrito por este ADR.** Sua história permanece intacta.

**ADR-002 continua válido**, sem alteração, para: LangGraph como **runtime de
orquestração**; Sales Agent **único** (com ADR-003); grafo, nodes e edges na
Etapa 2; "LangGraph orquestra e não implementa regra de negócio"; estado do
grafo não é source of truth; side effects idempotentes; webhook financeiro fora
do grafo; e o princípio final.

> **ADR-014 tem precedência sobre ADR-002 exclusivamente no tema
> "persistência / checkpoint durável do estado conversacional".** Em todos os
> demais aspectos do runtime de orquestração, ADR-002 continua sendo a
> autoridade.

ADR-014 substitui **qualquer interpretação de ADR-002 que exija**: (a)
checkpointer durável nativo do LangGraph; (b) schema de checkpoint controlado
pelo framework.

| Cláusula de ADR-002 | Leitura sob ADR-014 |
|---|---|
| *"checkpoints devem ser duráveis; preferência por PostgreSQL"* | A durabilidade é **da aplicação**: estado conversacional em tabela da aplicação, no PostgreSQL, versionada por Alembic. A cláusula é atendida; o que ela **não** autoriza é checkpointer gerenciado pelo framework ou schema criado por ele |
| *"confirmação do passageiro e aprovação humana **podem** usar interrupt/resume"* | **Não usados no MVP.** Confirmação é fronteira de turno, registrada em `pending_confirmation`; aprovação humana é assíncrona e fora do grafo (A-07). O verbo original é "podem": ADR-014 restringe sem contradizer |

## State ownership

> **O estado conversacional é cache de orquestração. Nunca autoridade
> financeira.**

Permanecem autoritativos, e são relidos do PostgreSQL antes de qualquer
operação crítica (SPEC-004 §3.1): `identity`, `cards`, `fare`, `orders`,
`approvals`, `payments`, `fulfillment`.

O estado guarda **referências de orquestração**. Nunca é autoridade para:
`balance`, `fare_profile`, `Card.status`, `Order.status`, `Order.total`,
`requires_approval`, `Payment.status`, `Approval.status`, `Fulfillment.status`,
valores financeiros, decisão de aprovação ou confirmação de pagamento.

`authenticated` e `customer_id` continuam **fora** do estado, como já decidido
em SPEC-004 §3.1: derivam da sessão de `identity` a cada operação protegida,
para que não exista segunda autoridade de identidade sobrevivendo à expiração
da sessão.

### Invariantes de projeto

> **Falha de persistência conversacional pode custar uma pergunta repetida.
> Nunca um efeito financeiro, nunca um efeito duplicado, nunca uma confirmação
> não pedida.**

Daí decorre a restrição que governa o schema:

> **Nada é persistido que não seja reconstruível a partir do backend, ou cuja
> perda exija mais do que repetir uma pergunta.**

É essa restrição — não uma preferência estética — que reprova histórico de
mensagens e valor monetário persistido. Teste de sanidade do desenho: **apagar
toda a tabela não pode fazer o sistema perder fato algum.**

## Lifecycle

### Snapshot por turno

O checkpoint semântico do MVP é o **snapshot durável ao final de cada turno
concluído**: uma leitura no início, uma escrita no fim, uma linha por conversa,
sobrescrita. **Não** se persiste por node, **não** existe event log e **não** se
depende de estrutura interna do LangGraph.

Rejeitado por node: multiplica escritas, guarda estado intermediário sem leitor
e cria a tentativa de retomar *dentro* de um turno, o que reexecutaria side
effects. Rejeitado event log: a trilha de auditoria já existe em `orders`,
`payments`, `payment_events`, `approvals`, ledger e `idempotency_records`; uma
segunda linha do tempo seria mais um invariante a conciliar, sem consumidor.
`version` é mecanismo de concorrência, **não** histórico de versões.

### Turno

```text
1. carregar ConversationState por conversation_id
2. avaliar expiração na leitura (ausente ou expirada ⇒ conversa nova)
3. reler o backend e reconciliar o contexto quando necessário
4. executar o grafo do turno
5. ações de negócio commitam nos seus próprios Unit of Work
6. reconstruir o state a partir dos resultados e do backend
7. optimistic update do ConversationState
8. fim do turno
```

### Crash, retry e restart

O último estado válido é **o do fim do turno anterior**: a escrita é atômica em
relação ao turno. Os efeitos de negócio do turno interrompido **permanecem**,
porque comitaram em transações próprias — e isso é seguro porque as idempotency
keys derivam de **evidência persistida no domínio**, nunca do estado
conversacional.

Turno perdido com quote e Order: a Quote fica sem referência e o Order fica
`DRAFT` até expirar; nenhum dinheiro se move. Turno perdido com confirmação e
pagamento: o estado anterior ainda contém `pending_confirmation` e
`current_order_id`, e um segundo "sim" reencontra as **mesmas** keys — replay,
ou `INVALID_ORDER_STATE_TRANSITION`. **Nenhuma cobrança dupla.**

A combinação perigosa — criar Order e criar Payment no mesmo turno — é
**estruturalmente impossível**: `create_payment` exige contexto comercial
confirmado, e `confirm_order` exige `pending_confirmation`, que só nasce no
turno em que o Order foi apresentado. A confirmação humana é fronteira de turno
obrigatória.

Retry da mesma request não é impedido por esta camada e não precisa ser, para
efeito financeiro. Processo reiniciado é indistinguível de turno novo: nada
vive em memória entre turnos — nem grafo suspenso, nem checkpoint, nem
histórico. **O restart não é caso especial**; é a propriedade que torna o
desenho testável.

### Expiração

A conversa tem `expires_at`, **avaliado na leitura** — mesmo padrão de
`Session.is_expired`. Conversa expirada é tratada como ausente. **A correção
nunca depende de o purge rodar.**

Conversa expirada **não** apaga estado financeiro, **não** cancela Order,
**não** altera Payment nem Card e **não** executa fulfillment. Purga física é
housekeeping futuro; **nenhum scheduler é implementado agora**, e sua
introdução exigiria ADR próprio (A-19).

### Múltiplas conversas

Um `session_id` pode ter **múltiplos** `conversation_id` — impor 1:1 fundiria
ciclos de vida distintos (sessão expira por inatividade; conversa tem retenção
própria). Não há unicidade sobre `session_id`.

**Uma pending confirmation pertence exclusivamente à conversa que a criou**, e
nenhuma conversa pode usar o próprio estado para confirmar Order de outra. A
proteção final continua no backend: ownership, estado do Order, TTL e
idempotência.

## Transaction boundary

**O `ConversationState` não participa da mesma transação de `Order`,
`Approval`, `Payment`, `Fulfillment` ou saldo de `Card`.**

1. **É estruturalmente incompatível com ADR-012 como implementado.** Cada
   serviço transacional recebe a própria instância de Unit of Work e abre a
   própria sessão. Fazer o agente comitar junto exigiria que toda assinatura de
   serviço aceitasse UoW externo — inversão da regra "agent não é domínio", em
   cinco módulos, por conveniência da camada conversacional.
2. **`create_payment` é bifásico** (SPEC-003 §11.2, A-13): nenhuma transação
   permanece aberta durante a chamada ao provider. Uma escrita acoplada ou
   manteria transação aberta durante I/O externo, ou se dividiria mesmo assim.
3. **Inverteria a direção da falha:** uma falha ao gravar a conversa desfaria um
   efeito financeiro válido — troca um problema recuperável por um
   irrecuperável.

**Regra de falha.** `business commit = sucesso` + `conversation save = falha` ⇒
**nenhuma compensação financeira**. No turno seguinte: carregar o
`ConversationState` disponível, reler o backend, reconstruir o contexto e
continuar de forma idempotente.

**Ordenação.** A escrita conversacional acontece **depois** do commit de
negócio — mesmo padrão da SPEC-005 §10.1. Nunca antes: gravar
`pending_confirmation` antes de o Order existir criaria referência para recurso
inexistente.

## Schema direction

Direção aprovada para a **futura** migration. Nenhuma tabela é criada por este
ADR.

```text
agent_conversations
  conversation_id                    UUID         PK
  session_id                         UUID         NOT NULL, FK → sessions.id
  phase                              texto        NOT NULL
  selected_card_id                   UUID         NULL
  current_quote_id                   UUID         NULL
  current_order_id                   UUID         NULL
  current_payment_id                 UUID         NULL
  pending_confirmation_order_id      UUID         NULL
  pending_confirmation_presented_at  TIMESTAMPTZ  NULL
  version                            inteiro      NOT NULL
  created_at                         TIMESTAMPTZ  NOT NULL
  updated_at                         TIMESTAMPTZ  NOT NULL
  expires_at                         TIMESTAMPTZ  NOT NULL
```

**Não entram, em nenhuma forma:** `display_total`, `balance`, `fare_profile`,
`Card.status`, `Order.status`, `Payment.status`, `Approval.status`,
`Fulfillment.status`, mensagens, CPF, OTP, hashes, segredos, payload de
provider.

**Colunas explícitas, sem JSONB.** Um blob "por flexibilidade" seria exatamente
onde saldo, perfil e status acabariam entrando, derrotando SPEC-004 §3.1 por
construção. **A ausência de coluna monetária é o controle**, não omissão:
impede que um valor de apresentação vire, com o tempo, insumo de decisão.

Tipos e convenções idênticos ao restante do repositório (UUID nativo,
TIMESTAMPTZ, enum textual com `CheckConstraint`, convenção de nomes de
`db/base.py`).

**Constraints planejadas:** coerência do par de confirmação (ambos nulos ou
ambos preenchidos); **vínculo da confirmação** — se
`pending_confirmation_order_id IS NOT NULL`, ele é coerente com
`current_order_id`, levando a regra anti-"sim errado" de SPEC-004 §9.1 para o
banco, onde ADR-004 R8 quer as invariantes críticas; `expires_at >
created_at`; `phase` restrita ao conjunto de `ConversationPhase`.

**Índices planejados:** `session_id` e `expires_at`. Nenhum índice parcial —
não há consulta que o justifique, e ADR-012 exige revisão explícita para eles.

### Foreign keys

**FK apenas para `sessions.id`.** Sem FK para `cards`, `quotes`, `orders` ou
`payments`.

`session_id` é **âncora de identidade e ownership**: dele se deriva
`customer_id` a cada operação protegida. Os demais são **referências de
navegação e cache**, revalidadas contra os respectivos módulos a cada uso. FK
sobre elas seria contraproducente: contradiz a natureza do dado (a referência
pode apontar para recurso expirado, consumido ou terminal); não protege nada
que importe (referência morta produz `ORDER_NOT_ACCESSIBLE` ou
`QUOTE_EXPIRED`, que é a resposta correta de qualquer forma); há precedente com
razão registrada em `idempotency_records.resource_id`; e prejudicaria a
**anti-enumeração**, porque com FK um identificador inexistente falharia na
escrita, tornando-se distinguível de um identificador válido de terceiro.

**Não usar cascade** que apague conversas automaticamente. Sessão expirada
**não** implica conversa apagada: são ciclos de vida distintos.

**Compatibilidade verificada em 2026-09-08:** `SessionRepository` expõe apenas
`add`, `get`, `get_for_update` e `update` — **não existe caminho de exclusão de
sessão no código**, nem purga. A FK com `RESTRICT` padrão é compatível com o
lifecycle existente. Se vier a existir purga de sessões, as conversas são
removidas antes ou a FK é revista; `ON DELETE CASCADE` não é a saída preferida
(ver D-8).

## Pending confirmation

Persistir `pending_confirmation_order_id` e
`pending_confirmation_presented_at`. **Não persistir valor monetário como
autoridade.**

O `display_total` que hoje existe em memória (SPEC-004 §3.1 o admite como não
autoritativo, para compor a frase já apresentada) **não é persistido**: criaria
uma segunda cópia de `order.total` no banco, mais velha e sem constraint que a
confira; seria valor monetário durável fora do domínio financeiro; e é
desnecessário, porque na retomada `get_order` devolve o total autoritativo. Ele
passa a ser **valor de turno**, e a releitura do Order antes de re-apresentar
torna-se obrigatória.

**Retomada:** conversa → `pending_confirmation_order_id` → reler Order →
validar ownership → validar estado (`DRAFT` é o único confirmável, SPEC-003
§14) → validar TTL → recompor o total → **somente então** aceitar a
confirmação.

> **O `ConversationState` nunca autoriza a confirmação por si só.** Ele diz
> qual Order foi apresentado; quem autoriza é o backend.

Se a limpeza da pendência se perder por crash, um segundo "sim" reencontra a
key `confirm_order:{order_id}` e resulta em replay idempotente ou
`INVALID_ORDER_STATE_TRANSITION`. **A guarda é o domínio, não a conversa** — é
essa propriedade que torna a fronteira transacional acima segura.

## Optimistic concurrency

```sql
-- carrega com version = N
UPDATE agent_conversations
   SET ..., version = N + 1
 WHERE conversation_id = ? AND version = N
```

Nenhuma linha atualizada ⇒ turno concorrente ⇒ **`CONVERSATION_CONFLICT`**.
**Nunca last-write-wins silencioso**: mesclar contextos conversacionais
divergentes é o que produziria a confirmação errada.

Rejeitados: `SELECT ... FOR UPDATE` durante o turno, que manteria lock aberto
durante chamadas de LLM — o anti-padrão que SPEC-003 §11.2 já proíbe para HTTP
ao provider; `FOR UPDATE` só na escrita, que serializa mas não impede lost
update; e **advisory lock como primeira solução**, que ADR-012 já considerou e
não adotou no MVP ("resolvem o que os row locks já resolvem, ao custo de estado
de lock invisível no schema"). **Nenhuma transação permanece aberta durante
chamada ao LLM.**

> **Concorrência conversacional nunca é a defesa financeira.** `version` não
> impede que dois turnos concorrentes alcancem `create_payment`; isso é
> protegido por key derivada de evidência persistida e por índice único
> parcial. O dinheiro continuaria protegido se esta tabela não existisse.

O comportamento de retry após conflito é especificado na Etapa 2/3, sempre
**relendo o backend antes de qualquer nova ação crítica**.

## PII e histórico

### Nenhum dado pessoal na tabela

Não por sanitização, mas por **composição**: todas as colunas são UUID opaco,
enum textual, inteiro ou timestamp. Não há texto livre, JSONB nem coluna
monetária. Proibidos, e sem lugar onde caberiam: CPF (cru, normalizado ou
hash), OTP (cru ou hash), mensagem contendo qualquer um dos dois, hashes,
segredos, payload de provider, número de cartão (derivável de `card_id`), nome,
e-mail, telefone e valor monetário.

Ausência de campo é propriedade; sanitização é processo.

### `phase` é boundary de segurança, não UX

`AWAITING_DOCUMENT` e `AWAITING_OTP` são o que informa ao transporte que a
próxima mensagem precisa passar pelo **handler determinístico de entrada
sensível** de SPEC-004 §13.1, **antes** de qualquer chamada ao provider.
Consequência direta: **depois de um restart, a fase precisa continuar
conhecida** — sem ela persistida, a mensagem seguinte, que contém CPF ou OTP,
seguiria o caminho normal até o modelo. É por isso que `phase` é campo
obrigatório do estado durável.

### Histórico de mensagens — não persistir no MVP

Nem histórico bruto, nem mensagens "sanitizadas", nem resumo gerado por LLM.

Razões: **minimização de PII**; **menor superfície de retenção**; **evita
prompt injection persistente** — este é o argumento decisivo, porque persistir
histórico converte uma injeção de **um turno** em injeção de **toda a
conversa**, reinjetada em todos os turnos seguintes e sobrevivendo a restarts;
e **reduz acoplamento** ao formato de `messages` do provider e do LangGraph.

O resumo por LLM é rejeitado por motivo próprio: é saída de modelo, e
persisti-lo cria contexto durável gerado pelo modelo com aparência de fato —
exatamente o que SPEC-004 §3.1 existe para impedir.

**O que se perde, explicitamente:** a descrição em linguagem natural do
trajeto, enquanto ainda não virou Quote. Um restart durante `DISCOVERY` ou
`CALCULATION` faz o cliente reafirmar o trajeto; a partir da Quote, o trajeto
está no backend e a perda desaparece. Persistir a **extração estruturada** foi
considerada e adiada com motivo: origem e destino de deslocamento são **dado de
localização**, categoria de PII que SPEC-002 §12 não enumerou por não haver
consumidor, e persisti-la exige análise de privacidade própria.

Se a Etapa 2 demonstrar necessidade de contexto durável adicional, a
preferência é **estado ou resumo estruturado não autoritativo**. **Persistência
de histórico textual exige nova decisão explícita** — não é permitida por
extensão desta.

## Stale state recovery

> **O `ConversationState` nunca vence o backend.**

Divergência **não é erro**: é o caso esperado, porque o webhook avança o Order
enquanto a conversa dorme. Resolve-se sempre a favor do domínio, e o estado
conversacional **nunca** move o domínio para trás.

Exemplo normativo: o estado diz `current_payment_id = X`, e o backend mostra
`Payment APPROVED` ⇒ `Order PAID` ⇒ `Fulfillment COMPLETED`. O runtime aceita o
backend como autoridade, atualiza o contexto, limpa a confirmação pendente e
conduz a conversa ao pós-venda — em vez de oferecer pagamento de algo já pago.
**A regra vale para todos os identificadores e status derivados.**

O ajuste é determinístico, ocorre **antes** de qualquer chamada ao LLM — para
que o modelo não veja contexto que já sabemos obsoleto — e **não escreve nada
no domínio**.

## Framework independence

`ConversationState` é **contrato da aplicação**. Na Etapa 2, **o LangGraph se
adapta a ele** — não o contrário.

Tipos do LangGraph **não podem vazar** para `domain`, para contratos de
`application` nem para o modelo de persistência. Regras que sustentam isso: o
`State` do grafo é tipo do adaptador, convertido de e para `ConversationState`
por funções puras; nenhum tipo do framework em coluna persistida, em
`ConversationState`, em `ToolResult` ou em assinatura de repositório;
`langgraph-checkpoint-postgres` não é dependência do projeto; nenhum `setup()`
de schema de framework; e `ConversationState` e seu repositório são testáveis
**sem** o LangGraph instalado. **Um teste arquitetural dedicado a essa fronteira
deve ser acrescentado na Etapa 2.**

Consequência exigida: **trocar de orquestrador no futuro não pode exigir
migration dos dados fundamentais de `agent_conversations`.** O custo de troca é
reescrever o adaptador, não mover dado.

Proporcionalidade: ADR-010 já estabelece a mesma postura para o provider de LLM
— *"o modelo é uma dependência substituível; os contratos e regras do produto
não são."* Este ADR estende o princípio do provider para o orquestrador.

## Alembic e ownership do schema

**Alembic é a autoridade do schema.** A tabela `agent_conversations` nasce por
migration versionada e revisada, como qualquer outra tabela da UrbanoPay
(ADR-012). **Nenhum schema é criado por runtime ou por framework** — nem
`setup()`, nem `create_all()`, sob nome algum.

A migration será planejada como **`agc0001`**, com `down_revision` **`ful0001`**
*se* ele continuar sendo o head quando a revision for criada. Ele era o head em
2026-09-08, mas **isto não é verdade eterna**: a implementação deve verificar o
head real antes de criar a revision.

**`alembic check` precisa ficar verde sem tocar em `env.py`** — é o teste de
que a alternativa correta foi escolhida. A migration não é destrutiva: cria uma
tabela, e o downgrade a remove com segurança justamente porque nenhum dado
autoritativo mora nela.

Dois testes de `tests/unit/test_architecture_boundaries.py` hoje afirmam a
**ausência** desta persistência e do LangGraph. Com este ADR aceito eles devem
ser **reescritos para asseverar o novo invariante**, nunca removidos nem
enfraquecidos (`.claude/rules/testing.md`).

## Consequências

**Positivas.** H-11 fecha por dissolução da premissa; toda mudança de schema
continua sob migration versionada, sem exceção aberta na CLAUDE.md;
`alembic check` continua verde sem afrouxar `env.py`; a superfície de PII do
estado durável é **zero por composição** e verificável por teste; injeção de
prompt não se torna persistente; uma dependência a menos a instalar e validar
(`langgraph-checkpoint-postgres` não entra), reduzindo o escopo de H-05; evals
e unit tests podem rodar sem banco e sem checkpointer; trocar de orquestrador
custa reescrever um adaptador, não migrar dados; e apagar a tabela inteira não
faz o sistema perder fato algum.

**Negativas.** É preciso escrever repositório, mapeamento e migration —
trabalho que o checkpointer pronto pouparia. Perde-se `interrupt`/`resume`,
time-travel e replay por super-step; se um requisito futuro exigi-los de
verdade, esta decisão precisa ser revisitada **por ADR**, não contornada.
Perde-se o contexto linguístico anterior à Quote em caso de restart. A
reconciliação de estado obsoleto passa a ser código nosso, com testes nossos.
E dois testes de arquitetura precisam ser reescritos com disciplina para não
virar enfraquecimento.

**Sobre o desbloqueio da Etapa 2.** Este ADR remove o bloqueio
**arquitetural** registrado em H-11. Ele **não** remove o bloqueio de
compatibilidade: **H-05 permanece aberta**, e a validação de `langgraph` em
Python 3.13 precede a instalação da dependência. Incompatibilidade exigiria
novo ADR, não alteração silenciosa do ADR-013.

## Riscos

| # | Risco | Mitigação |
|---|---|---|
| R1 | **H-05 aberta**: compatibilidade de `langgraph` com Python 3.13 não validada | Validar instalação, import e grafo mínimo **antes** de escrever a Etapa 2. Esta decisão reduz o escopo a uma única dependência |
| R2 | Perda de contexto linguístico em restart antes da Quote | Aceito no MVP. Persistir trajeto estruturado exige análise de privacidade de dado de localização |
| R3 | Escrita conversacional perdida após commit de negócio: o cliente percebe uma pergunta repetida | Direção de falha correta e deliberada; a reconciliação corrige no turno seguinte |
| R4 | Alguém acrescentar coluna com status, saldo ou valor num PR futuro | Ausência de JSONB e de coluna monetária, mais teste do conjunto de colunas, tornam a violação mecanicamente detectável |
| R5 | A Etapa 3 esquecer a idempotência de mensagem: retry de POST custa tokens e pode gerar respostas divergentes | Registrada como D-6 |
| R6 | Reescrita dos testes de ausência ser confundida com enfraquecimento de teste | Substituir asserção por asserção, nunca deletar; explicitar no PR citando este ADR |
| R7 | Necessidade futura real de `interrupt` (ex.: aprovação humana dentro do grafo) | Hoje A-07 põe a aprovação fora do grafo. Se isso mudar, é mudança de fronteira ⇒ ADR novo |
| R8 | `max_turns_per_session` (SPEC-004 §14) sem contador persistido no schema aprovado | Ver D-1: exige decisão antes de o limite ser implementável |

## Decisões adiadas

Nenhuma bloqueia este ADR; todas precisam de decisão antes da implementação
correspondente. **Nenhuma delas está decidida por omissão.**

| # | Item | Quando decide |
|---|---|---|
| D-1 | **Contador de turnos.** SPEC-004 §14 exige `max_turns_per_session` e o schema aprovado não tem contador. Há ambiguidade de escopo: o texto diz "por sessão", mas o portador natural é a conversa, e uma sessão pode ter várias | Etapa 2. Reinterpretação de escopo deve ser registrada em OPEN-QUESTIONS, no padrão de A-21 |
| D-2 | **Mutabilidade de `session_id`** — se uma conversa pode ser revinculada a nova sessão autenticada após expiração, e com qual higiene (a alternativa conservadora limpa `pending_confirmation` em toda troca) | Etapa 2/3, com o transporte |
| D-3 | **Valor do TTL da conversa.** `expires_at` é aprovado; o número não é fixado por documento algum. Deve ser configurável | Etapa 2 |
| D-4 | **Lugar de `CONVERSATION_CONFLICT`.** É de fronteira de turno, não de execução de tool, e portanto **não** pertence aos seis códigos de SPEC-004 §20 que A-20 fechou deliberadamente | Etapa 3, com registro em OPEN-QUESTIONS |
| D-5 | **Localização do adaptador do grafo** e forma do teste arquitetural de fronteira de framework | Etapa 2 |
| D-6 | **Idempotência de request/mensagem do transporte.** Preocupação distinta, e não confundível com as idempotências de negócio de `create_order`, `confirm_order` e `create_payment`. O dinheiro já está protegido; custo de LLM e coerência de resposta não. Nenhum `message_id` entra no schema por esta decisão, por não haver consumidor real (SPEC-004 §22). Restrições a preservar: identificador do transporte, nunca escolhido pelo modelo, e **fora** de `idempotency_records`, que é auditoria de comando de domínio (A-13) | Etapa 3 |
| D-7 | **Purga física de conversas expiradas.** Exige scheduler, e A-19 sujeita scheduler a ADR próprio | Quando houver necessidade operacional real |
| D-8 | **Revisão da FK para `sessions`** se e quando existir purga de sessões | Quando a purga for proposta |
