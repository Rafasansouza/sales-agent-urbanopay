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

Vazio. Depende de:

- a camada de persistência decidida em **ADR-012** (Aceito) ainda não foi
  implementada — sem ela não há o que integrar;
- **SPEC-001 a SPEC-005** — não implementadas.

`make test-integration` coletando zero testes é o resultado esperado nesta
fase.
