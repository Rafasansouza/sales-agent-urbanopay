# tests/integration — Testes de integração

**Marcador:** `integration`
**Requer infraestrutura:** sim (`make up` / `.\scripts\dev.ps1 up`)

## Escopo

Fronteiras de banco e de provider. Valida o que só se prova com a
infraestrutura real no lugar.

O que pertence a esta camada:

- repositórios e mapeamento `NUMERIC` ↔ `Decimal`;
- migrations aplicadas e revertidas;
- **constraints de banco** que protegem invariantes, entre elas no máximo um
  `Payment APPROVED` por `Order`;
- transação atômica de ledger, saldo e status (SPEC-005 §7);
- lock e concorrência na atualização de saldo;
- idempotência: mesma chave não produz efeito duplicado;
- processamento de webhook, incluindo o duplicado;
- `FakePaymentProvider` e a fronteira do `PaymentProvider`.

## Regras

- Usa PostgreSQL e Redis reais do `docker-compose` local.
- **Nunca** chama provider externo de verdade. Mercado Pago e LLM entram
  exclusivamente por dublê.
- Cada teste isola seu estado; nenhum teste depende da ordem de execução.
- Dados exclusivamente fictícios.

## Estado atual

Contém os testes da **persistence foundation** (ADR-012):

- `test_persistence_foundation.py` — conexão assíncrona com PostgreSQL 17,
  `Decimal` para `NUMERIC`, sessão, commit, rollback, Unit of Work,
  `expire_on_commit=False` e naming convention aplicada no banco;
- `test_migrations.py` — `alembic upgrade head` e `alembic check`.

A tolerância a coleta vazia foi removida desta camada (H-07): **zero testes
coletados reprova**.

Os testes usam um schema descartável (`it_foundation`) com uma sonda genérica
que não representa entidade de domínio e é invisível ao `alembic check`
(`include_schemas=False` no env.py). Os testes das SPECs chegam com as SPECs.

Requisitos locais: `up` executado e variáveis `POSTGRES_*` no ambiente ou no
`.env`.
