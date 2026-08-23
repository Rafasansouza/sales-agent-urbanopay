# SPEC-003 — Orders & Payments

**Projeto:** UrbanoPay Mobilidade  
**Dependências:** SPEC-001, SPEC-002

## 1. Objetivo
Transformar uma intenção validada em uma operação transacional controlada, auditável e idempotente. Abrange Quote, Order, aprovação e Payment. Fulfillment é responsabilidade da SPEC-005.

## 2. Princípio
A conversa representa intenção; o backend representa estado. Dizer “paguei” nunca altera o status financeiro.

## 3. Entidades
- `Quote`;
- `Order`;
- `OrderItem`;
- `Approval`;
- `Payment`;
- `PaymentEvent`;
- `IdempotencyRecord`.

## 4. Quote
Campos: `quote_id`, `customer_id`, `card_id`, `operation_type`, `fare_profile`, `items`, `subtotal`, `discount_amount`, `total`, `currency`, `expires_at`, `created_at`.

Tipos de operação:
- `RECHARGE`;
- `TICKET_PURCHASE`.

Quote é snapshot e não reserva dinheiro. TTL configurável; sugestão inicial 10 minutos. Expirada => `QUOTE_EXPIRED`.

## 5. Order
Criado somente com sessão autenticada, Quote válida e titularidade/estado válidos.

Campos principais: `order_id`, `customer_id`, `card_id`, `quote_id`, `operation_type`, `status`, `subtotal`, `discount_amount`, `total`, `currency`, `requires_approval`, timestamps.

O Order congela produto, quantidade, tarifa, perfil, desconto e total.

## 6. Estados do Order
- `DRAFT`;
- `REQUIRES_APPROVAL`;
- `APPROVED` (aprovação administrativa);
- `CONFIRMED`;
- `PAYMENT_PENDING`;
- `PAID`;
- `FULFILLING`;
- `COMPLETED`;
- `FULFILLMENT_FAILED`;
- `FAILED`;
- `CANCELLED`;
- `EXPIRED`.

Enums de Approval e Payment devem ser separados para evitar ambiguidade.

## 7. Aprovação humana
Regra inicial:

```text
RECHARGE > R$ 200,00
→ REQUIRES_APPROVAL
```

A política deve estar encapsulada em `ApprovalPolicy`, não espalhada em `if` pela aplicação.

`Approval.status`: `PENDING`, `APPROVED`, `REJECTED`.

O Sales Agent pode consultar status, mas não aprovar/rejeitar.

## 8. Confirmação explícita
Antes do pagamento, apresentar operação, cartão mascarado, perfil, valor, desconto, total e meio de pagamento.

Mensagens claras podem resultar em `CONFIRMED`; ambíguas => `AMBIGUOUS` e nova pergunta; negativas => `REJECTED`.

Após confirmação, valores ficam imutáveis. Alteração exige cancelamento/nova Quote/novo Order.

## 9. Payment
Campos: `payment_id`, `order_id`, `provider`, IDs externos, `method`, `amount`, `currency`, `status`, `idempotency_key`, timestamps.

MVP: `PIX`, ambiente test/sandbox.

Status:
- `CREATED`;
- `PENDING`;
- `APPROVED`;
- `REJECTED`;
- `CANCELLED`;
- `EXPIRED`;
- `FAILED`.

Criação somente com `Order CONFIRMED` e sem pagamento aprovado existente.

## 10. Valor
`payment.amount == order.total`. A tool ideal é `create_payment(order_id)`; o backend deriva valor e moeda.

## 11. Idempotência
Obrigatória em:
- `create_order`;
- `confirm_order`;
- `approve_order`;
- `create_payment`;
- `process_payment_webhook`.

`IdempotencyRecord`: key, operation, resource_id, request_hash, status, response_reference, timestamps.

## 12. Webhook
Fluxo:
1. validar origem/assinatura quando aplicável;
2. identificar recurso;
3. persistir evento;
4. deduplicar;
5. consultar/validar estado oficial quando necessário;
6. atualizar Payment;
7. atualizar Order.

Webhook duplicado nunca produz efeito duplicado.

## 13. Múltiplas tentativas
Um Order pode possuir `1..N Payments`, mas no máximo um `APPROVED`.

Retry da mesma tentativa reutiliza a mesma idempotency key. Nova tentativa após rejeição usa novo `payment_id` e nova key.

## 14. Máquina de estados principal

```text
DRAFT
 ├─> CANCELLED
 ├─> EXPIRED
 ├─> CONFIRMED
 └─> REQUIRES_APPROVAL
        ├─> CANCELLED
        └─> APPROVED
             └─> CONFIRMED
                   └─> PAYMENT_PENDING
                         └─> PAID
                               └─> FULFILLING
                                     ├─> COMPLETED
                                     └─> FULFILLMENT_FAILED
```

Transições inválidas => `INVALID_ORDER_STATE_TRANSITION`.

## 15. Falha após pagamento
`Payment APPROVED + Fulfillment failure` nunca gera novo Payment. O problema passa a ser de entrega/reconciliação.

## 16. Erros tipados
- `QUOTE_NOT_FOUND`;
- `QUOTE_EXPIRED`;
- `QUOTE_NOT_ACCESSIBLE`;
- `ORDER_NOT_FOUND`;
- `ORDER_NOT_ACCESSIBLE`;
- `ORDER_ALREADY_PAID`;
- `ORDER_EXPIRED`;
- `ORDER_REQUIRES_APPROVAL`;
- `APPROVAL_PENDING`;
- `APPROVAL_REJECTED`;
- `INVALID_ORDER_STATE`;
- `INVALID_ORDER_STATE_TRANSITION`;
- `PAYMENT_NOT_FOUND`;
- `PAYMENT_ALREADY_APPROVED`;
- `PAYMENT_PROVIDER_ERROR`;
- `PAYMENT_CREATION_FAILED`;
- `PAYMENT_STATUS_UNKNOWN`;
- `IDEMPOTENCY_CONFLICT`.

## 17. Testes obrigatórios
Cobrir happy path, Quote expirada, cross-user, recarga 50, recarga 250 com aprovação, rejeição, create payment, mensagem “paguei”, webhook approved, webhook duplicado, concorrência, tentativa de mudar valor, prompt injection, rejeição/segunda tentativa, order já pago, transição inválida e payment approved + fulfillment fail.

## 18. Segurança
- nenhuma tool `set_order_status`;
- nenhuma tool `set_payment_status`;
- nenhuma tool `mark_order_as_paid`;
- nenhuma tool `apply_discount`;
- backend deriva valores críticos.

## 19. Aceite
Quotes/Orders preservam snapshots, state machine é respeitada, >200 exige aprovação, payment é idempotente, webhook é deduplicado, user message não muda pagamento, e nenhum cenário crítico permite cobrança duplicada.
