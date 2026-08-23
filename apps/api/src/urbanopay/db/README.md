# Persistência

**Documentos:** ADR-004 (Aceito), ADR-012 (**Proposta**)
**Estado:** vazio por decisão

## Por que este diretório está vazio

O ADR-012 define driver PostgreSQL, camada de acesso a dados e ferramenta de
migrations. Ele está com status **Proposta**.

Como essa é uma decisão estrutural — molda como todos os módulos de domínio
persistem estado e como as invariantes financeiras são garantidas no banco —
ela não pode ser tomada implicitamente durante a implementação de uma SPEC.

## Consequências atuais

- Nenhuma dependência de banco no `pyproject.toml`.
- Nenhum modelo, schema ou migration.
- `make migrate` / `.\scripts\dev.ps1 migrate` falham com mensagem explicativa.
- O job `test-integration` da CI sobe PostgreSQL e Redis, mas não coleta testes.
- `GET /api/v1/health` não verifica banco nem Redis.
- **SPEC-001 não pode ser implementada**, porque exige tarifas persistidas com
  vigência (SPEC-001 §2 e §8).

## Regras que valerão quando o ADR for aceito

Fonte: ADR-004, CLAUDE.md, SPEC-001 §7, SPEC-005 §7.

- PostgreSQL é autoritativo para todo estado transacional.
- pgvector apenas para recuperação semântica; nunca autoritativo para preço,
  saldo ou status de pagamento.
- Dinheiro em `NUMERIC`/`DECIMAL`, mapeado para `Decimal`, **sem** passar por
  float em nenhum ponto.
- Toda mudança de schema exige migration versionada.
- Migration destrutiva exige revisão humana explícita.
- Constraints de banco para invariantes críticas, entre elas:
  - no máximo um `Payment APPROVED` por `Order`;
  - unicidade de CPF normalizado;
  - unicidade de chave de idempotência.
- Ledger, saldo e status atualizados na mesma transação.
- Concorrência em saldo com lock ou controle equivalente.
- Separação lógica por domínio: um módulo não lê a tabela de outro livremente.
- Seeds exclusivamente fictícios.
