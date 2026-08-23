# ADR-012 — Persistência, ORM e Ferramenta de Migrations

**Status:** Proposta
**Data:** 2026-08-23

> Este ADR **não está aceito**. Enquanto o status for `Proposta`, nenhuma
> dependência de banco de dados deve ser adicionada ao backend e nenhum
> esquema, modelo ou migration deve ser criado. O alvo `make migrate` falha
> deliberadamente. Ver `docs/OPEN-QUESTIONS.md`.

## Contexto

ADR-004 estabelece PostgreSQL como source of truth e pgvector restrito à busca
semântica. CLAUDE.md e ADR-004 exigem migrations versionadas e constraints de
banco para invariantes críticas. Nenhum documento aceito, porém, nomeia o
driver, a camada de acesso a dados ou a ferramenta de migrations.

Essa é uma decisão estrutural: define como todos os módulos de domínio
persistem estado e como as invariantes financeiras são garantidas no banco.
Por isso não pode ser tomada implicitamente durante a implementação da
SPEC-001.

## Requisitos que a escolha precisa atender

1. `NUMERIC/DECIMAL` mapeado para `Decimal` de Python **sem passar por float**
   em nenhum ponto do caminho (CLAUDE.md, SPEC-001 §7).
2. Migrations versionadas, revisáveis e reversíveis; nenhuma migration
   destrutiva sem revisão explícita (CLAUDE.md, ADR-004).
3. Suporte a constraints de banco como última linha de defesa: unicidade,
   `CHECK`, exclusão parcial. Necessário, por exemplo, para garantir no máximo
   um `Payment APPROVED` por Order (ADR-007, SPEC-003 §13).
4. Transação explícita abrangendo ledger, saldo e status na mesma unidade de
   trabalho (SPEC-005 §7).
5. Lock pessimista ou controle de concorrência equivalente para atualização de
   saldo (SPEC-005 §7).
6. Suporte a `pgvector` para recuperação semântica (ADR-004).
7. Persistência de checkpoints do LangGraph em PostgreSQL (ADR-002).
8. Separação lógica por domínio, sem que um módulo acesse livremente as
   tabelas de outro (ADR-001).
9. Compatibilidade com Python 3.13 (ADR-013).

## Alternativas em avaliação

### A. SQLAlchemy 2.x + Alembic
Padrão de fato no ecossistema. Cobre tipagem moderna, `Numeric` com
`asdecimal`, `with_for_update()`, transações explícitas, `pgvector` via pacote
oficial e checkpointer PostgreSQL do LangGraph. Custo: superfície grande;
exige disciplina para não deixar o ORM vazar para a camada de domínio.

### B. SQL puro com psycopg 3 + migrations versionadas em arquivos
Controle total sobre cada consulta, sem risco de comportamento implícito do
ORM. Custo: muito código de mapeamento manual; risco maior de erro em
conversão de `Decimal` e em transações compostas.

### C. SQLModel
Reduz duplicação entre modelo e schema. Custo: acopla modelo de domínio ao
modelo de persistência, o que contraria ADR-006 ("schemas HTTP não precisam ser
os mesmos objetos do domínio/ORM") e reduz o controle exigido pelas
invariantes financeiras.

## Decisão

**Pendente.** Requer escolha explícita entre A, B e C, e a definição da
ferramenta de migrations correspondente.

## Consequências

Enquanto este ADR não for aceito:

- `apps/api/src/urbanopay/db/` contém apenas documentação;
- nenhum módulo possui camada de persistência;
- `make migrate` / `.\scripts\dev.ps1 migrate` falham com mensagem explicativa;
- o job `test-integration` da CI sobe PostgreSQL e Redis, mas não coleta
  nenhum teste;
- SPEC-001 não pode ser implementada, pois exige tarifas persistidas com
  vigência (SPEC-001 §2 e §8).
