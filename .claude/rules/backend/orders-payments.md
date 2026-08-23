---
description: Regras de Quote, Order, aprovação e Payment (SPEC-003). Idempotência financeira.
paths:
  - "apps/api/src/urbanopay/modules/orders/**"
  - "apps/api/src/urbanopay/modules/payments/**"
  - "apps/api/src/urbanopay/modules/approvals/**"
  - "apps/api/src/urbanopay/providers/payments/**"
  - "tests/**/orders/**"
  - "tests/**/payments/**"
  - "tests/**/approvals/**"
  - "tests/**/*payment*"
  - "tests/**/*order*"
---

# Regra — Orders, Approvals & Payments

**Documentos obrigatórios:** `docs/specs/SPEC-003-orders-payments.md`, ADR-005, ADR-007.

Leia a SPEC-003 antes de qualquer alteração nestes módulos.

## Princípio

A conversa representa **intenção**; o backend representa **estado**. Dizer
"paguei" nunca altera status financeiro.

## Invariantes financeiras

- Somente o provider ou o backend estabelece `PaymentStatus.APPROVED`.
- Somente `PaymentStatus.APPROVED` permite `Order PAID`.
- Um Order pode ter `1..N` Payments, mas **no máximo um `APPROVED`**. Proteja
  isso também com transação e constraint de banco, não apenas com código.
- `payment.amount == order.total`, sempre derivado server-side.
- Após confirmação, os valores do Order são **imutáveis**. Alteração exige
  cancelar e criar nova Quote e novo Order.
- Timeout na criação de pagamento é **estado desconhecido**, não falha
  definitiva. Nunca faça retry cego.
- Falha de fulfillment após pagamento aprovado **nunca** gera nova cobrança.

## Idempotência

Obrigatória em `create_order`, `confirm_order`, `approve_order`,
`create_payment` e `process_payment_webhook`.

- `IdempotencyRecord` guarda key, operation, resource_id, request_hash, status,
  response_reference e timestamps.
- Registros de idempotência financeira vivem no PostgreSQL, nunca no Redis.
- Retry da mesma tentativa reutiliza a mesma key.
- Nova tentativa após rejeição usa novo `payment_id` e nova key.
- Webhook duplicado nunca produz efeito duplicado.

## Aprovação humana

Regra vigente: `RECHARGE > R$ 200,00` exige aprovação.

A política fica encapsulada em `ApprovalPolicy`. **Nunca** espalhe o limite em
`if` pela aplicação, e nunca escreva o valor literal fora da policy.

`Approval.status`: `PENDING`, `APPROVED`, `REJECTED`. O Sales Agent pode
consultar o status, nunca aprovar ou rejeitar.

⚠️ A interface administrativa de aprovação não está especificada. Ver A-07 em
`docs/OPEN-QUESTIONS.md`.

## Confirmação explícita

Antes do pagamento, apresente operação, cartão mascarado, perfil, valor,
desconto, total e meio de pagamento.

`ConfirmationResult`: `CONFIRMED`, `REJECTED`, `AMBIGUOUS`.
**Mensagem ambígua nunca dispara pagamento.**

## Nomenclatura de enums

`APPROVED` existe em três enums distintos: `Order.status` (aprovação
administrativa), `Approval.status` e `Payment.status`.

Regras para evitar confusão:

- os três enums são tipos **separados**, nunca strings soltas;
- nunca compare status entre enums diferentes;
- em log e em trace, sempre qualifique: `order.status=APPROVED`,
  `payment.status=APPROVED`;
- ver A-09 em `docs/OPEN-QUESTIONS.md` para a discussão de renomeação.

## Máquina de estados

A referência é SPEC-003 §14. Transição inválida retorna
`INVALID_ORDER_STATE_TRANSITION`.

⚠️ Duas lacunas bloqueiam a implementação deste módulo:

- **C-01**: PRD §8 e SPEC-003 §14 discordam sobre a ordem entre confirmação do
  passageiro e aprovação humana.
- **C-02**: não existe transição definida que permita uma segunda tentativa de
  pagamento após rejeição.

Ambas estão em `docs/OPEN-QUESTIONS.md` e precisam de decisão documental antes
da implementação. Não escolha silenciosamente uma das interpretações.

## Provider de pagamento

Fonte: ADR-007.

- Encapsulado por `PaymentProvider` / `MercadoPagoPaymentProvider`.
- Somente credenciais de teste; access token só no backend.
- `X-Idempotency-Key` em toda criação.
- Webhook valida origem e assinatura quando aplicável, persiste o evento,
  deduplica e só então atualiza Payment e Order.
- Webhook entra direto no `PaymentService`, nunca no grafo do agente e nunca no
  LLM.
- `FakePaymentProvider` em testes locais e em CI.

## Tools proibidas

`set_order_status`, `set_payment_status`, `mark_order_as_paid`,
`apply_discount`, `approve_payment`, `mark_payment_as_paid`. Não crie nenhuma
delas, sob nenhum nome equivalente.
