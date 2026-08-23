# tests/unit — Testes unitários

**Marcador:** `unit`
**Requer infraestrutura:** não

## Escopo

Regra de domínio pura, sem I/O externo. Executa rápido e roda em todo commit.

O que pertence a esta camada:

- cálculo tarifário e classificação de viagem (SPEC-001);
- arredondamento `ROUND_HALF_UP` e aritmética com `Decimal`;
- `ApprovalPolicy` (SPEC-003 §7);
- transições da máquina de estados de `Order` (SPEC-003 §14);
- masking de cartão e validação de documento (SPEC-002);
- construção de erros tipados.

## Regras

- Nenhum acesso a banco, a Redis, a rede ou a filesystem.
- Um teste marcado `unit` que faz I/O real está na camada errada.
- Os 16 casos obrigatórios de SPEC-001 §12 pertencem aqui e exigem **100% de
  acurácia**. Não os substitua por eval.

## Estado atual

Contém apenas `test_api_health.py`, um teste de fumaça do bootstrap. As regras
de domínio chegam com a implementação das SPECs.
