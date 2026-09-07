# Orders — Quote e Order

**Fronteira de domínio:** ADR-001
**Documentos obrigatórios:** SPEC-003
**ADRs aplicáveis:** ADR-005, ADR-007, ADR-012
**Estado:** implementado (SPEC-003, escopo `RECHARGE`)

## Responsabilidade

Transforma intenção validada em operação transacional controlada. Quote é
snapshot; Order congela produto, tarifa, perfil, desconto, total e
`requires_approval`.

Este módulo também hospeda os comandos de **decisão de aprovação**
(`approve_order`, `reject_order`), porque o efeito primário deles é uma
transição do Order — a SPEC-003 §11 nomeia a operação `approve_order`, não
`approve_approval`. O agregado `Approval` continua sendo do módulo
`approvals`, consumido aqui pela sua interface pública.

## Entidades

- `Quote` (**sem coluna de status**: validade derivada de `expires_at`)
- `Order`
- `LineItem` — materializado como `quote_items` / `order_items`

O `IdempotencyRecord` é **transversal** e vive em `core/idempotency.py`
(contrato) e `db/idempotency.py` (persistência), não neste módulo.

## Escopo do MVP

Somente `operation_type = RECHARGE`. `TICKET_PURCHASE` existe no enum porque a
SPEC o define, mas `OperationType.require_supported()` o **recusa
explicitamente**: catálogo de produtos não possui especificação (A-05), e
comportamento fictício para produto sem SPEC seria pior que uma recusa clara.

## Tools permitidas ao Sales Agent

- `create_quote`
- `create_order`
- `confirm_order`
- `get_order`

## Tools proibidas

- `set_order_status`
- `mark_order_as_paid`
- `apply_discount`
- `approve_order` / `reject_order` **pelo agente** — o comando existe, mas a
  superfície é administrativa, nunca conversacional

Nenhuma delas pode ser criada sob nome equivalente ou disfarçada como tool
genérica.

## Invariantes

- `CONFIRMED` é o **único** estado pagável e significa "todas as confirmações
  necessárias foram satisfeitas".
- **Não existe `Order.APPROVED` nem `Order.FAILED`** — removidos por não terem
  caminho de entrada. Teste de alcançabilidade do grafo garante que nenhum
  estado órfão volte ao enum.
- `requires_approval` é congelado na criação: recalculá-lo depois permitiria
  contornar a aprovação alterando o total.
- Cancelamento pelo cliente **somente** em `DRAFT`. `REQUIRES_APPROVAL →
  CANCELLED` ocorre apenas por rejeição, com motivo registrado como tal.
- TTL se aplica **somente enquanto `DRAFT`** (default 10 min). Após a
  confirmação não há TTL automático nesta versão.
- Uma Quote gera no máximo um Order (`uq_orders_quote_id`).
- `total = subtotal - discount_amount`, garantido por `CHECK`.

## Pendências que ainda afetam o módulo

- **A-07** — a superfície pela qual um humano decide a aprovação não está
  especificada. Os comandos determinísticos existem e são testados; o que
  falta é a interface que os chamará.
- **A-05** / **A-06** — catálogo e `calculate_usage_cost` sem especificação.

## Estrutura

```text
orders/
├── domain/          entidades, enums, erros, ApprovalPolicy, state machine, ports
├── application/     QuoteService, OrderService
└── infrastructure/  models ORM, repositories, Unit of Work
```

Direção de dependência: `domain` não importa `application` nem
`infrastructure`. Ver `.claude/rules/architecture.md`.

`orders` depende da interface pública de `approvals`; `approvals` **nunca**
importa `orders`. A dependência é unidirecional por decisão — dependência
circular entre módulos é defeito (ADR-001).
