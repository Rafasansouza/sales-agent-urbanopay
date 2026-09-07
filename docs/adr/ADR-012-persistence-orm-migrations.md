# ADR-012 — Persistência, ORM e Migrations

**Status:** Aceito
**Data da proposta:** 2026-08-23
**Data da aceitação:** 2026-08-29

## Contexto

ADR-004 estabelece PostgreSQL como source of truth e restringe pgvector à
recuperação semântica. CLAUDE.md e ADR-004 exigem migrations versionadas e
constraints de banco para invariantes críticas. Nenhum documento aceito, porém,
nomeava o driver, a camada de acesso a dados ou a ferramenta de migrations.

Essa é uma decisão estrutural: define como todos os módulos de domínio
persistem estado e como as invariantes financeiras são garantidas no banco. Por
isso não podia ser tomada implicitamente durante a implementação da SPEC-001.

## Requisitos que a decisão precisa atender

| # | Requisito | Fonte |
|---|---|---|
| R1 | PostgreSQL autoritativo para todo estado transacional | ADR-004 |
| R2 | `Decimal` em Python, `NUMERIC` no PostgreSQL, 2 casas, `ROUND_HALF_UP`, nunca float | CLAUDE.md, SPEC-001 §7 |
| R3 | Ledger, saldo e status na mesma transação | SPEC-005 §7 |
| R4 | Concorrência em saldo com lock ou controle equivalente | SPEC-005 §7 |
| R5 | No máximo um `Payment APPROVED` por `Order` | SPEC-003 §13, ADR-007 |
| R6 | Idempotência financeira no PostgreSQL, nunca no Redis | ADR-009 |
| R7 | Um Order de recarga produz no máximo um efeito financeiro | SPEC-005 §19.3 |
| R8 | Constraints de banco para invariantes críticas | ADR-004 |
| R9 | Migration versionada obrigatória; destrutiva exige revisão humana | CLAUDE.md |
| R10 | `domain` não importa `application` nem `infrastructure` | ADR-001 |
| R11 | Nenhuma regra de negócio no ORM | CLAUDE.md |
| R12 | Schemas HTTP não precisam ser objetos de domínio ou de ORM | ADR-006 |
| R13 | `async` somente onde houver I/O | ADR-006 |
| R14 | Vigência nunca sobrescreve histórico | SPEC-001 §8 |

## Decisão

- **SQLAlchemy 2.x** como camada de persistência.
- **ORM declarativo tipado** como modelo de persistência.
- **Queries explícitas com a API 2.0**: `select`, `insert`, `update`. Nenhum uso
  do estilo legado `session.query()`.
- **Modelos ORM confinados à camada `infrastructure`.**
- **Entidades de domínio puras**, sem qualquer dependência de SQLAlchemy.
- **psycopg 3** como driver PostgreSQL.
- **Runtime de persistência assíncrono**, com `AsyncSession` e
  `async_sessionmaker`.
- **`expire_on_commit=False`.**
- **Alembic** para migrations.
- **Repository Pattern.**
- **Unit of Work explícito e fino**, como port da camada de aplicação.
- **`READ COMMITTED`** como nível de isolamento.
- **`SELECT ... FOR UPDATE`, constraints e índices únicos** como mecanismos
  principais de concorrência.
- **Repositories nunca executam commit.**
- **A camada de aplicação controla a fronteira transacional.**
- **Uma sessão por unidade de trabalho.**
- **Uma `AsyncSession` nunca é compartilhada entre tasks concorrentes.**
- **Um único schema lógico** para as tabelas da aplicação no MVP.

## Modelo de I/O

O runtime da aplicação é assíncrono de ponta a ponta:

| Camada | Modelo |
|---|---|
| FastAPI | async |
| LangGraph | async |
| Repositories | async |
| Unit of Work | async |
| Runtime da aplicação | async |
| Alembic | pode usar engine e conexão síncronos |

Background jobs futuros — reconciliação, `find_stale_fulfillments` — **podem
usar a mesma infraestrutura assíncrona** quando for apropriado. Este ADR não os
obriga a serem síncronos.

A escolha por async decorre de ADR-002: LangGraph é o principal consumidor dos
serviços de domínio e é assíncrono. Um núcleo síncrono forçaria envelopar cada
tool do agente em execução em thread, criando uma mistura acidental de modelos.

psycopg 3 fornece as APIs síncrona e assíncrona na mesma biblioteca, com os
mesmos codecs de tipo. É isso que torna a exceção do Alembic segura: não há dois
comportamentos de conversão no caminho do dinheiro.

### Windows e o event loop

**psycopg em modo assíncrono não é compatível com o `ProactorEventLoop`, que é
o event loop padrão do Python em Windows.**

O ambiente principal de desenvolvimento deste projeto inclui Windows. A
implementação da persistência deverá, portanto, configurar uma política de
event loop compatível — `SelectorEventLoop` ou mecanismo equivalente suportado —
e validar esse comportamento.

Isto é **critério de teste da implementação da persistência**, não uma nota
informativa. Uma suíte que passa em Linux e falha em Windows por essa causa é
defeito.

## Camada de persistência

Desde a versão 2.0 o SQLAlchemy unificou a API: `select`, `insert` e `update`
são os mesmos em Core e ORM. A decisão aqui, portanto, não é sobre estilo de
query, e sim sobre onde o mapeamento vive e o que atravessa a fronteira.

- Modelos declarativos tipados (`Mapped[...]`, `mapped_column`) definem o
  schema, alimentam o Alembic e dão verificação de tipos pelo mypy.
- Modelos ORM vivem **exclusivamente** em `modules/<dominio>/infrastructure/`.
- **Nenhum modelo ORM atravessa a fronteira do repositório.** Repositories
  recebem e devolvem entidades de domínio.
- **Sem lazy loading.** Onde houver relacionamento, configurar carregamento
  explícito ou `lazy="raise_on_sql"`, de modo que carregamento implícito falhe
  em teste em vez de disparar query fora da transação.
- `expire_on_commit=False`, para que objetos não disparem query após o commit.
- Nenhuma regra de negócio em modelo ORM: sem validação de domínio, sem cálculo,
  sem transição de estado (R11).

## Organização

Estrutura conceitual aprovada. **Estes arquivos não são criados por este ADR** —
a árvore documenta a direção arquitetural, e a implementação nasce em tarefa
posterior.

```text
apps/api/src/urbanopay/
├── core/
│   └── persistence.py            # Protocol do UnitOfWork, sem SQLAlchemy
├── db/
│   ├── base.py                   # DeclarativeBase, MetaData, naming_convention
│   ├── engine.py                 # engine assíncrono; engine síncrono p/ Alembic
│   ├── session.py                # async_sessionmaker e dependência do FastAPI
│   ├── unit_of_work.py           # implementação SQLAlchemy do UnitOfWork
│   ├── registry.py               # importa os models para popular o MetaData
│   └── migrations/               # ambiente do Alembic
└── modules/<dominio>/
    ├── domain/
    │   ├── entities.py           # entidades puras, sem SQLAlchemy
    │   ├── errors.py             # erros tipados da SPEC
    │   └── ports.py              # Protocol dos repositories
    ├── application/
    │   └── services.py           # usa ports e UnitOfWork abstrato
    └── infrastructure/
        ├── models.py             # SQLAlchemy declarativo — somente aqui
        └── repositories.py       # implementa ports e mapeia model ↔ entidade
```

### Direção de dependências

```text
api/  ──────►  application/  ──────►  domain/
                    │                    ▲
                    │  depende de ports  │  implementa ports
                    ▼                    │
              infrastructure/  ──────────┘
```

`db/registry.py` é o único ponto que conhece todos os módulos, e existe
exclusivamente porque o Alembic precisa de um único `MetaData` contendo todas as
tabelas. Ele não é ponto de acoplamento entre domínios.

## Repository e Unit of Work

### Repository

O port é um `Protocol` em `modules/<dominio>/domain/ports.py`; a implementação
fica em `modules/<dominio>/infrastructure/repositories.py`.

Tipagem estrutural via `Protocol` evita que o domínio precise ser herdado pela
infraestrutura, preservando a direção de dependência e mantendo-a verificável
pelo mypy.

**Repositories nunca executam commit nem rollback.**

### Unit of Work

A `Session` do SQLAlchemy **já é** uma implementação de Unit of Work. A
abstração `UnitOfWork` deste projeto não existe para suprir uma ausência do
SQLAlchemy; ela existe por quatro razões próprias:

1. **impedir que `AsyncSession` vaze para `application` e `domain`** — sem ela,
   a camada de aplicação importaria SQLAlchemy, violando R10;
2. **coordenar vários repositories na mesma transação** — R3 exige que ledger,
   saldo e status mudem juntos, o que atravessa três repositories;
3. **tornar commit e rollback explícitos** no ponto onde a decisão de negócio
   acontece;
4. **facilitar testes** com implementações falsas, permitindo testar a camada de
   aplicação sem banco.

A implementação SQLAlchemy fica atrás desse port, em `db/unit_of_work.py`. O
`Protocol` fica em `core/persistence.py`, por ser transversal aos módulos.

```python
async with uow:  # BEGIN
    card = await uow.cards.get_for_update(card_id)
    await uow.ledger.append(entry)
    await uow.cards.update_balance(card_id, new_balance)
    await uow.fulfillments.mark_completed(fulfillment_id)
    await uow.commit()  # COMMIT
```

## Sessão e transação

- `async_sessionmaker` com `expire_on_commit=False`.
- **Uma sessão por unidade de trabalho.** Em requisições HTTP, uma sessão por
  request, entregue ao Unit of Work — nunca ao router.
- **Uma `AsyncSession` nunca é compartilhada entre tasks concorrentes.**
- **A camada de aplicação controla a fronteira transacional.** Repositories
  participam da transação; não a abrem nem a encerram.
- Nível de isolamento: **`READ COMMITTED`**, o padrão do PostgreSQL.

`REPEATABLE READ` e `SERIALIZABLE` foram descartados como política geral: ambos
exigiriam laço de retry em falha de serialização em toda escrita, espalhando
complexidade por todo o código para resolver o que locks explícitos e
constraints já resolvem de forma mais direta e mais auditável.

**Princípio:** a correção vem de constraints de banco e de locks explícitos, não
do nível de isolamento.

## Concorrência e invariantes no banco

Mapeamento de cada invariante crítica para o mecanismo que a garante.

| Invariante | Fonte | Mecanismo |
|---|---|---|
| No máximo um `Payment APPROVED` por Order | R5 | Índice único **parcial** em `payments (order_id) WHERE status = 'APPROVED'` |
| Um efeito financeiro por Order de recarga | R7 | `UNIQUE (order_id)` em `recharge_transactions` |
| Idempotência de operação crítica | R6 | `UNIQUE (key)` em `idempotency_records` + `INSERT ... ON CONFLICT DO NOTHING` |
| Webhook duplicado sem efeito duplicado | SPEC-003 §12 | `UNIQUE (provider, provider_event_id)` em `payment_events` |
| Ledger, saldo e status atômicos | R3 | Uma transação, com `SELECT ... FOR UPDATE` no cartão |
| Concorrência em saldo | R4 | `SELECT ... FOR UPDATE` na linha do cartão |
| CPF normalizado único | SPEC-002 §2 | `UNIQUE` no CPF normalizado |
| `total >= 0` e `discount_amount <= subtotal` | SPEC-001 §13 | `CHECK` |

O índice único parcial é a garantia autoritativa de R5. A verificação em código
continua existindo como caminho feliz, mas o índice é a última linha de defesa,
conforme R8.

O lock explícito no cartão é preferido a um `UPDATE ... RETURNING` atômico
porque o ledger exige `balance_before` e porque o status do cartão precisa ser
validado sob o mesmo lock, evitando a corrida entre leitura e escrita.

**Ordem de lock consistente é obrigatória** para evitar deadlock: quando mais de
uma linha for travada na mesma transação, a ordem de aquisição deve ser sempre a
mesma em todo o código.

Advisory locks do PostgreSQL foram considerados e **não adotados** no MVP:
resolvem o que os row locks já resolvem, ao custo de estado de lock invisível no
schema.

### Invariante sem cobertura no banco

A invariante "ticket não excede a quantidade comprada" (SPEC-005 §19.5) **não é
expressável como constraint simples**. Ela exige `UNIQUE (order_id,
sequence_number)` somado a validação na camada de aplicação e teste dedicado.
É a única invariante crítica sem rede de proteção no banco, e precisa ser
tratada com atenção proporcional na implementação da SPEC-005.

## Retries

Três situações distintas que não podem ser tratadas como uma só:

| Situação | SQLSTATE | Tratamento |
|---|---|---|
| Violação de unicidade | `23505` | **Não é erro técnico, é informação de negócio**: significa que outro processo já realizou a operação. Traduzir para resultado de domínio, devolvendo o recurso existente. Nunca retry cego. |
| Deadlock | `40P01` | Retry limitado é aceitável, mas a causa raiz é ordem de lock inconsistente e deve ser corrigida. |
| Falha de conexão em escrita | — | **Estado desconhecido.** Vai para reconciliação, conforme SPEC-005 §11 e ADR-007. Nunca retry cego. |

Esta distinção é a diferença entre uma cobrança e duas.

## Dinheiro

| Uso | PostgreSQL | Python |
|---|---|---|
| Valor monetário | `NUMERIC(12, 2)` | `Decimal` |
| Percentual de desconto | `NUMERIC(5, 2)` | `Decimal` |

Nos modelos ORM, colunas monetárias usam `Numeric(12, 2, asdecimal=True)`.

**A aritmética monetária e o `ROUND_HALF_UP` pertencem ao domínio.** A camada de
persistência armazena valores já arredondados e **não arredonda silenciosamente**
valor monetário algum.

Fica **rejeitado** um `TypeDecorator` que execute `quantize()` automaticamente:
arredondamento é regra de cálculo, e regra de cálculo no tipo de coluna violaria
R11. Um tipo customizado futuro poderá **validar invariantes** — por exemplo,
rejeitar escala inesperada — mas nunca executar cálculo.

O arredondamento é materialmente relevante. Com números da própria SPEC-001, um
subtotal de 7,50 com desconto de integração de 15% resulta em 1,125, que precisa
virar 1,13 por `ROUND_HALF_UP`, e não 1,12 como faria o arredondamento bancário
padrão do Python.

Riscos de conversão a controlar na implementação:

- `Decimal` nunca é construído a partir de `float`;
- nenhuma coluna monetária pode ser declarada como `Float`;
- o contrato JSON transporta valor como **string decimal** (ADR-006), o que
  exige serialização explícita e teste de contrato;
- o driver precisa devolver `Decimal` para `NUMERIC`.

## Migrations

**Alembic**, com as regras abaixo. Elas não são o comportamento padrão da
ferramenta e por isso ficam registradas aqui.

### Regra permanente

```text
autogenerate → migration candidata → revisão humana obrigatória
```

O autogenerate produz um rascunho. Ele nunca é a migration final.

### Regras

1. **`naming_convention` obrigatória no `MetaData`.** Sem nomes determinísticos
   para índices, constraints e chaves, o Alembic não consegue alterar nem
   remover objetos criados anonimamente.
2. **Revisão manual de toda migration**, sem exceção.
3. **Índices parciais e invariantes específicas do PostgreSQL sob revisão
   explícita.** Constraints `CHECK` nomeadas podem ser detectadas pelas versões
   atuais do Alembic, mas a comparação tem limitações — em especial, mudança de
   expressão preservando o mesmo nome exige atenção humana.
4. **`alembic check` na CI**, falhando quando os modelos divergirem das
   migrations. É, para o schema, o equivalente do que o `uv.lock` é para
   dependências.
5. **Migration destrutiva exige revisão humana explícita** (R9), sinalizada no
   Pull Request.
6. **Teste de `upgrade` e `downgrade` quando aplicável**, provando
   reversibilidade em banco descartável.

## Schema lógico

No MVP, **um único schema lógico/default** para as tabelas da aplicação. Não há
schemas separados por domínio.

ADR-004 permite schemas por domínio "quando apropriado". A avaliação é que, no
MVP, eles complicariam chaves estrangeiras entre módulos e a configuração do
Alembic sem benefício correspondente.

A propriedade de tabela por módulo continua valendo como regra arquitetural
(ADR-001) e é garantida por revisão, não por separação física.

## Testabilidade

**Unit** — o domínio é puro e testável sem banco. A camada de aplicação é
testável com repositories e Unit of Work falsos, o que é a segunda justificativa
para esses padrões.

**Integração** — PostgreSQL real, usando a infraestrutura que já existe:
`infra/docker-compose.yml` localmente e o service container do
`.github/workflows/ci.yml`. `testcontainers` não é adotado, por duplicar o que a
CI já provê.

**Isolamento entre testes** — duas estratégias, com critério de escolha:

- **Rollback por teste**, como padrão: conexão externa, transação aberta, sessão
  ligada a ela, rollback ao final.
- **Commit real com limpeza posterior**, obrigatório para **testes de
  concorrência**. Duas sessões disputando `SELECT ... FOR UPDATE` precisam de
  dados efetivamente comitados, porque uma conexão não enxerga a transação não
  comitada da outra. Os cenários de concorrência de SPEC-003 §17 e SPEC-005 §21
  caem nesta categoria.

Tentar testar concorrência com isolamento por rollback leva à conclusão errada
de que o lock funciona.

**Migrations na CI** — `alembic upgrade head` antes dos testes de integração, e
`alembic check` como gate.

## Escopo deste ADR

**ADR-012 governa apenas as tabelas pertencentes à aplicação e ao domínio da
UrbanoPay.**

A estratégia de persistência das tabelas internas do LangGraph — o checkpointer
de ADR-002 — **será decidida em ADR separado, antes da implementação da
SPEC-004**.

Enquanto essa decisão não existir, **nenhum `setup()` automático de schema do
LangGraph deve ser introduzido**, porque criaria tabelas fora do controle de
migrations versionadas, contrariando R9.

## Dependências previstas

Registradas como direção, **não instaladas por este ADR**.

**Runtime:**

- SQLAlchemy 2.x com suporte a asyncio;
- psycopg 3;
- Alembic.

**Testes:**

- pytest-asyncio.

`pgvector` permanece **adiado** até existir consumidor real. ADR-004 o aceita,
mas nada o consome ainda, e adicionar dependência sem consumidor contraria a
disciplina de ADR-013.

## Compatibilidade

Considerada resolvida documentalmente para efeito de aceitação deste ADR:

- SQLAlchemy 2.0 possui suporte a Python 3.13;
- greenlet possui suporte a Python 3.13;
- psycopg 3 suporta Python 3.13 e PostgreSQL 17.

A implementação ainda deverá validar, e isso **não bloqueia mais a aceitação**:

- resolução de dependências via `uv`;
- conexão real contra PostgreSQL 17;
- retorno de `Decimal` para colunas `NUMERIC`;
- testes de integração passando;
- política de event loop compatível em Windows.

## Alternativas rejeitadas

| Alternativa | Motivo |
|---|---|
| **asyncpg** | Somente assíncrono, o que exigiria um segundo driver para o Alembic e, com ele, um segundo conjunto de codecs no caminho do dinheiro. O ganho de throughput é irrelevante: a latência dominante é a chamada de LLM, e o alvo de PRD §16 para operações determinísticas é P95 ≤ 500 ms. |
| **psycopg2** | Sem suporte assíncrono; manutenção conservadora. Não é escolha razoável para projeto novo. |
| **SQL direto com psycopg** | Perde composição de query, adaptação de tipos e autogenerate. Sem `MetaData`, nada detecta "mudei o schema e esqueci a migration", enfraquecendo R9. |
| **SQLAlchemy Core puro** | Elimina qualquer vazamento, mas exige mapeamento manual para cerca de dezoito entidades, e código de mapeamento manual é ele próprio superfície de defeito. O confinamento dos modelos à `infrastructure` atinge o mesmo objetivo com menos risco. |
| **SQLModel** | Acopla domínio, ORM e schema HTTP na mesma classe, contrariando R12 e R11. |
| **yoyo-migrations** | Faria sentido com SQL direto; perde autogenerate e a checagem de divergência. |
| **Sqitch, dbmate, Atlas** | Exigem toolchain fora do `uv`, contrariando a simplicidade operacional de ADR-013. |
| **Schemas PostgreSQL por domínio** | Complicam chaves estrangeiras entre módulos e a configuração do Alembic sem benefício no MVP. |
| **`SERIALIZABLE` como política geral** | Exigiria laço de retry em toda escrita para resolver o que constraints e locks explícitos já resolvem. |

## Consequências

**Positivas:** um único driver cobre aplicação, migrations e jobs; invariantes
financeiras ficam garantidas no banco e não apenas em código; o domínio
permanece puro e testável sem banco; `alembic check` impede divergência entre
modelo e schema; a fronteira transacional é explícita e revisável.

**Negativas:** o modelo assíncrono é mais difícil de depurar e exige disciplina
com sessões; Windows requer configuração explícita de event loop; o mapeamento
entre modelo ORM e entidade de domínio é código adicional; o autogenerate do
Alembic exige revisão humana disciplinada, que é processo e não ferramenta.

## Critérios de teste da implementação

A implementação da persistência só é considerada concluída com:

1. teste de integração provando `Decimal` de ponta a ponta, sem float em nenhum
   ponto do caminho;
2. teste de concorrência em saldo, com commit real, provando que
   `SELECT ... FOR UPDATE` serializa;
3. teste provando que o índice único parcial impede um segundo
   `Payment APPROVED` no mesmo Order;
4. teste provando que webhook duplicado não gera efeito duplicado;
5. teste provando que ledger, saldo e status são atômicos, com rollback
   verificado;
6. teste de arquitetura provando que `domain` não importa SQLAlchemy;
7. `alembic check` verde na CI;
8. **suíte passando em Windows com política de event loop compatível.**

## Questões que permanecem abertas

Nenhuma delas bloqueia este ADR; todas estão registradas em
`docs/OPEN-QUESTIONS.md`:

- estratégia de persistência do checkpointer do LangGraph, que exige ADR próprio
  antes da SPEC-004;
- ciclo de vida de `IdempotencyRecord` em estado `IN_PROGRESS` obsoleto, que
  pertence à definição de Orders e Payments e precisa ser resolvido antes da
  SPEC-003;
- `CHECK (balance >= 0)`: seguro no MVP, que apenas credita, mas o
  comportamento de débito não está especificado;
- TTL de Order, que afeta diretamente o schema;
- dimensionamento do pool de conexões, que depende de carga real ainda
  inexistente.

## Regra para Claude Code

Modelos ORM vivem apenas em `infrastructure` e nunca atravessam a fronteira do
repositório. O domínio não importa SQLAlchemy. Repositories não comitam. A
camada de aplicação abre e fecha a transação. Nenhum arredondamento monetário
acontece na persistência. Toda mudança de schema exige migration versionada e
revisada. Nenhuma tabela é criada fora do Alembic.
