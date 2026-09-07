# Payments — pagamento Pix e webhook

**Fronteira de domínio:** ADR-001
**Documentos obrigatórios:** SPEC-003 §9, §11, §12, §13
**ADRs aplicáveis:** ADR-005, ADR-007, ADR-012
**Estado:** implementado (SPEC-003, provider `FAKE`)

## Responsabilidade

Criação de cobrança Pix, idempotência de duas fases, processamento de webhook e
reconciliação. **Somente o provider ou o backend estabelece `APPROVED`.**

## Entidades

- `Payment` — cada Payment **é** uma tentativa comercial; não existe entidade
  separada de tentativa
- `PaymentEvent` — evento de provider, por webhook ou consulta ativa
- `ProviderCharge` — resultado transitório de criação/consulta, não persistido

## Tools permitidas ao Sales Agent

- `create_payment(order_id)`
- `get_payment_status(order_id)`

## Tools proibidas

- `set_payment_status`
- `approve_payment`
- `mark_payment_as_paid`

Nenhuma delas pode ser criada sob nome equivalente ou disfarçada como tool
genérica. `create_payment` **não aceita** `amount`, `currency` nem `status` —
há teste de assinatura provando isso, porque um parâmetro de valor aqui
permitiria que a superfície de chamada escolhesse quanto se cobra.

## Invariantes

- `payment.amount` vem de `order.total`, sempre derivado server-side.
- Um Order pode ter `1..N` Payments, no máximo **um `APPROVED`** e no máximo
  **um ativo** (`CREATED`/`PENDING`) — índices únicos parciais, além da
  verificação em código.
- Uma idempotency key produz um único Payment
  (`uq_payments_idempotency_key`): é o que materializa o retry técnico.
- Webhook duplicado nunca produz efeito duplicado
  (`UNIQUE (provider, provider_event_id)` + `ON CONFLICT DO NOTHING`).
- Estados terminais **não regridem** e não são substituídos por outro terminal.
- Timeout de criação é **estado desconhecido**, nunca falha definitiva:
  `Payment CREATED` + `Order PAYMENT_PENDING` + `Idempotency IN_PROGRESS` +
  `PAYMENT_STATUS_UNKNOWN`. Não existe estado `UNKNOWN`.
- Nenhuma transação de banco fica aberta durante a chamada ao provider.
- Nenhuma apropriação de key por tempo: o tempo autoriza reconciliação, nunca
  cobrança.
- O webhook entra direto no `PaymentService`, nunca no grafo do agente e nunca
  no LLM. Texto do usuário não é evento de domínio.

## Minimização de dados

- O payload de provider é **redigido por allowlist** antes de qualquer
  persistência. Nunca token, secret, credencial ou PII.
- O código copia-e-cola do Pix **não é persistido**: é devolvido de forma
  transitória e pode ser reconsultado.
- `external_reference` leva o UUID opaco do Order — nunca CPF, nome ou e-mail.

## Ponto único de convergência

Webhook e consulta ativa passam pelo **mesmo** aplicador de estado, sob lock do
Payment, com regras monotônicas. É isso que garante que os dois caminhos não
divirjam. Quando o provider reporta `APPROVED` sobre um terminal não aprovado,
o aplicador **não** aplica: sinaliza `requires_reconciliation`, porque ali pode
existir dinheiro recebido que o nosso estado não reflete — e aprovar por causa
de um evento fora de ordem é justamente o que produziria efeito indevido.

## Providers

- `FakePaymentProvider` (`providers/payments/fake.py`) — dev e toda a CI.
  Nenhuma chamada de rede, nenhuma credencial.
- `MercadoPagoPaymentProvider` — **não implementado**. Quando nascer: somente
  sandbox, credenciais por variável de ambiente, nenhum secret versionado.
  A tradução do vocabulário do provider para `PaymentStatus` acontece no
  adaptador, nunca no domínio.

## Estrutura

```text
payments/
├── domain/          Payment, PaymentEvent, enums, erros, aplicador monotônico, ports
├── application/     PaymentService (criação em duas fases, webhook, reconciliação)
└── infrastructure/  models ORM, repositories, Unit of Work
```

Direção de dependência: `domain` não importa `application` nem
`infrastructure`. Ver `.claude/rules/architecture.md`.

`payments` depende da interface pública de `orders` (o desfecho de um Payment
transiciona o Order na mesma transação); `orders` **nunca** importa `payments`.

## Ordem global de lock

`Order → Approval → Payment → Card → Fulfillment` (ADR-012). Deste módulo
participam os três primeiros elos, e a ordem vale inclusive no caminho do
webhook, onde é tentador travar primeiro o Payment que o evento identificou.

`Card` e `Fulfillment` entram com a SPEC-005 e vêm **depois** do Payment.
