# `urbanopay-domains` — fronteiras de negócio

As sete fronteiras de ADR-001 com implementação. Cada uma se estratifica em
`domain/` (entidades, value objects, erros tipados, regras puras),
`application/` (use cases e serviços) e `infrastructure/` (repositórios e
modelos ORM).

| Módulo | SPEC | Responsabilidade |
|---|---|---|
| `fare` | SPEC-001 | Tarifa oficial, classificação de viagem, vigência |
| `identity` | SPEC-002 | Cliente, sessão, OTP simulado |
| `cards` | SPEC-002 | Cartão, titularidade, perfil tarifário oficial, saldo |
| `orders` | SPEC-003 | Quote, Order e sua máquina de estados |
| `approvals` | SPEC-003 | Aprovação humana de recarga de alto valor |
| `payments` | SPEC-003 | Payment, webhook, reconciliação |
| `fulfillment` | SPEC-005 | Recarga, ledger, comprovante |

## Direção de dependência (ADR-017)

```text
database ◀── domains ◀── agent ◀── backend
```

Este pacote depende **somente** de `urbanopay-database`. Ele não conhece o
agente, não conhece a camada HTTP e não conhece a configuração da aplicação —
um domínio existe sem a conversa, e precisa continuar existindo.

## Regras que valem aqui

- `domain/` **não** importa `application` nem `infrastructure`, e nunca importa
  SQLAlchemy. Verificado por `tests/unit/test_architecture_boundaries.py`.
- Modelos ORM vivem **apenas** em `infrastructure/` e nunca atravessam a
  fronteira do repositório (ADR-012).
- Repositories **nunca** comitam. A camada de aplicação controla a transação.
- Dinheiro é `Decimal` em Python e `NUMERIC` no PostgreSQL. Nunca `float`, em
  nenhum ponto do caminho.
- Um módulo não acessa internals nem tabelas de outro: a comunicação usa a
  interface pública do módulo de destino.

## O que não está aqui

O `registry` de modelos e as migrations do Alembic vivem em `apps/backend`.
O motivo é de direção, não de gosto: o registry precisa enumerar **todos** os
modelos, inclusive os do agente, e só o topo da direção enxerga todos sem
inverter a seta.
