# SPEC-003 — Orders & Payments

**Projeto:** UrbanoPay Mobilidade  
**Dependências:** SPEC-001, SPEC-002

## 1. Objetivo
Transformar uma intenção validada em uma operação transacional controlada, auditável e idempotente. Abrange Quote, Order, aprovação e Payment. Fulfillment é responsabilidade da SPEC-005.

### 1.1 Escopo do MVP

O único `operation_type` implementável no MVP é **`RECHARGE`**. `TICKET_PURCHASE` depende de um catálogo de produtos que ainda não possui especificação (ver A-05 em `docs/OPEN-QUESTIONS.md`) e permanece fora do escopo.

Para `RECHARGE`:

- o valor é escolhido pelo cliente (produto "Recarga Livre");
- `subtotal == total` e `discount_amount == 0`;
- o Fare Engine **não** calcula o valor da recarga — ele serve para recomendar quanto carregar, o que depende de `calculate_usage_cost` (ver A-06);
- `fare_profile` é registrado como **snapshot de auditoria** (perfil oficial vigente), não como insumo de cálculo.

A política temporal e a composição de itens definidas nesta SPEC valem para `RECHARGE`. Quando `TICKET_PURCHASE` for especificado, ambas devem ser revisitadas, porque preço e produto podem exigir validade diferente.

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

Quote é snapshot e não reserva dinheiro. TTL configurável; **default 10 minutos**. Expirada => `QUOTE_EXPIRED`. De outro cliente => `QUOTE_NOT_ACCESSIBLE`.

A Quote **não possui coluna de status**: sua validade é derivada de `expires_at`, e seu consumo é o fato relacional de existir um Order que a referencia.

## 5. Order
Criado somente com sessão autenticada, Quote válida e titularidade/estado válidos.

Campos principais: `order_id`, `customer_id`, `card_id`, `quote_id`, `operation_type`, `status`, `subtotal`, `discount_amount`, `total`, `currency`, `requires_approval`, `expires_at`, timestamps.

O Order congela produto, quantidade, tarifa, perfil, desconto e total.

`requires_approval` é determinado na criação, pela `ApprovalPolicy`, e congelado junto com os valores.

### 5.1 Política temporal do Order

- Order em `DRAFT` possui TTL configurável; **default 10 minutos**.
- A expiração se aplica **somente enquanto `DRAFT`**: `DRAFT` expirado transiciona para `EXPIRED` e não pode ser confirmado (`ORDER_EXPIRED`).
- Após a confirmação explícita do cliente **não há TTL automático** nesta versão: os valores estão congelados, `REQUIRES_APPROVAL` pode aguardar decisão humana e `CONFIRMED` pode aguardar a criação do Payment pelo tempo necessário.

Esta política vale para `RECHARGE` no MVP e deve ser revisitada quando `TICKET_PURCHASE` for implementado (ver §1.1).

## 6. Estados do Order
- `DRAFT`;
- `REQUIRES_APPROVAL`;
- `CONFIRMED`;
- `PAYMENT_PENDING`;
- `PAID`;
- `FULFILLING`;
- `COMPLETED`;
- `FULFILLMENT_FAILED`;
- `CANCELLED`;
- `EXPIRED`.

`CONFIRMED` significa: **todas as confirmações necessárias foram satisfeitas e o Order está elegível para criação de Payment.** É o único estado pagável.

`FULFILLING`, `COMPLETED` e `FULFILLMENT_FAILED` são alcançados pela SPEC-005; esta SPEC termina em `PAID`.

Enums de Approval e Payment são separados e não colidem com os estados do Order:

- a aprovação administrativa é representada por `Approval.status = APPROVED` (§7) — **não existe `Order.APPROVED`**;
- o pagamento aprovado é representado por `Payment.status = APPROVED` (§9).

Nenhum estado do Order existe sem caminho válido de entrada. `APPROVED` e `FAILED` foram removidos deste enum por não possuírem transição de entrada em nenhuma SPEC: a aprovação vive em `Approval`, e o encerramento por falha é coberto por `CANCELLED`, `EXPIRED` (§14) e `FULFILLMENT_FAILED` (SPEC-005).

## 7. Aprovação humana
Regra inicial:

```text
RECHARGE com order.total > R$ 200,00
→ requires_approval = true
```

A comparação é **estritamente maior**: `R$ 200,00` exatos **não** exigem aprovação. O valor comparado é `order.total`.

A política deve estar encapsulada em `ApprovalPolicy`, não espalhada em `if` pela aplicação.

A aprovação acontece **após** a confirmação explícita do cliente (§8, §14): a confirmação do cliente leva o Order a `REQUIRES_APPROVAL` e cria a `Approval` em `PENDING`; a decisão humana então libera o Order para `CONFIRMED`.

`Approval.status`: `PENDING`, `APPROVED`, `REJECTED`.

Transições: `PENDING → APPROVED` ou `PENDING → REJECTED`. Estados terminais não retornam a `PENDING`. `Approval` não possui TTL no MVP e não possui estado `CANCELLED`.

Efeitos:

- `Approval → APPROVED` ⇒ `Order REQUIRES_APPROVAL → CONFIRMED`;
- `Approval → REJECTED` ⇒ `Order REQUIRES_APPROVAL → CANCELLED`, com motivo registrado como decorrente de rejeição de aprovação — nunca apresentado como cancelamento solicitado pelo cliente.

Toda decisão registra ator e instante para trilha de auditoria.

O Sales Agent pode consultar status, mas não aprovar/rejeitar.

## 8. Confirmação explícita
Antes do pagamento, apresentar operação, cartão mascarado, perfil, valor, desconto, total e meio de pagamento.

A confirmação explícita do cliente é o **primeiro** dos consentimentos necessários e ocorre sempre a partir de `DRAFT`. Seu destino depende de `requires_approval`:

- `requires_approval = false` ⇒ `DRAFT → CONFIRMED` (elegível para Payment);
- `requires_approval = true` ⇒ `DRAFT → REQUIRES_APPROVAL` (aguardando decisão humana).

Mensagens claras produzem a confirmação; ambíguas => `AMBIGUOUS` e nova pergunta, sem transição de estado; negativas => `REJECTED`, sem transição de estado. Uma mensagem ambígua nunca inicia pagamento.

Após confirmação, valores ficam imutáveis. Alteração exige cancelamento/nova Quote/novo Order.

## 9. Payment
Campos: `payment_id`, `order_id`, `provider`, IDs externos, `method`, `amount`, `currency`, `status`, `idempotency_key`, timestamps.

MVP: `PIX`, ambiente test/sandbox.

Status:
- `CREATED` — existe tentativa local, mas ainda não existe confirmação suficiente do estado externo (inclui o caso de timeout na criação);
- `PENDING` — o provider confirmou a cobrança e aguarda pagamento;
- `APPROVED` — o provider confirmou o pagamento;
- `REJECTED`;
- `CANCELLED`;
- `EXPIRED`;
- `FAILED` — falha determinística de criação informada pelo provider.

Não existe estado `UNKNOWN`: o desconhecimento do estado externo é representado por `CREATED` somado ao erro `PAYMENT_STATUS_UNKNOWN` (§16).

Estados terminais (`APPROVED`, `REJECTED`, `CANCELLED`, `EXPIRED`, `FAILED`) **não regridem**. Somente estado confirmado pelo provider/backend produz `APPROVED` e, por consequência, `Order PAID`. Texto do usuário — por exemplo "eu paguei" — não é evento de domínio e não altera nenhum estado financeiro.

`Payment.FAILED` não se confunde com nenhum estado de encerramento do Order: um Payment `FAILED` devolve o Order a `CONFIRMED` (§13).

Criação somente com `Order CONFIRMED` e sem pagamento aprovado existente. Há no máximo uma tentativa ativa (`CREATED` ou `PENDING`) por Order.

### 9.1 Estado externo desconhecido

Quando a criação no provider sofre timeout ou resposta inconclusiva:

- `Payment` permanece `CREATED`;
- `Order` permanece `PAYMENT_PENDING`;
- o `IdempotencyRecord` permanece `IN_PROGRESS` (§11);
- a operação retorna `PAYMENT_STATUS_UNKNOWN`.

Nenhuma nova tentativa comercial é permitida enquanto esse estado não for reconciliado, e nenhum novo POST é emitido: a resolução acontece por consulta ao provider usando a mesma idempotency key. Timeout é estado desconhecido, nunca falha definitiva.

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

A unicidade é por escopo `(operation, key)`. Mesma key com payload diferente => `IDEMPOTENCY_CONFLICT`.

### 11.1 Status do IdempotencyRecord

- `IN_PROGRESS` — a key foi reivindicada e a operação ainda não concluiu;
- `COMPLETED` — a operação **executou e o resultado é conhecido**, inclusive quando o Payment resultante terminou em estado não aprovado;
- `FAILED` — falha **determinística da própria operação**, que deve ser reproduzida em replay.

`Payment.REJECTED` não se confunde com `Idempotency.FAILED`: o primeiro é resultado conhecido de uma operação concluída (`COMPLETED`); o segundo é falha da operação em si.

### 11.2 Fronteira transacional da idempotência

Operações **exclusivamente locais** — `create_order`, `confirm_order`, `approve_order`, `reject_order` e o processamento local de `PaymentEvent` — usam uma única transação:

```text
reivindicar key → aplicar efeito → COMPLETED → commit
```

Se a transação falhar, registro e efeito falham juntos; não existe `IN_PROGRESS` órfão observável nesses casos.

`create_payment` possui efeito externo e usa duas fases:

```text
TX1: reivindica key; cria Payment CREATED; associa ao Order; Order → PAYMENT_PENDING; commit
     chamada ao provider (fora de transação)
TX2: aplica resposta externa; persiste referência/status; atualiza Order quando aplicável;
     Idempotency → COMPLETED; commit
```

Nenhuma transação de banco permanece aberta durante a chamada ao provider.

### 11.3 Registro em `IN_PROGRESS`

Não existe apropriação automática baseada apenas em tempo. Quando uma chamada encontra a mesma key em `IN_PROGRESS`:

- nenhum novo POST é emitido;
- a operação retorna estado desconhecido/em processamento (`PAYMENT_STATUS_UNKNOWN`);
- a reconciliação é solicitada ou agendada.

Um parâmetro de obsolescência (`stale_after`) pode existir **somente** como gatilho para consultar o provider. Ele nunca autoriza nova cobrança: o tempo autoriza reconciliação, não cobrança.

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
Um Order pode possuir `1..N Payments`, mas no máximo um `APPROVED`. Cada `Payment` **é** uma tentativa comercial; não existe entidade separada de tentativa.

São dois casos distintos:

### 13.1 Retry técnico da mesma tentativa

Aplicável a timeout ou resultado externo desconhecido:

- mesmo `payment_id`;
- mesma idempotency key;
- nenhum Payment novo;
- consulta/reconciliação **antes** de qualquer novo POST;
- nunca retry cego.

### 13.2 Nova tentativa comercial

Quando o Payment termina definitivamente em `REJECTED`, `EXPIRED`, `CANCELLED` ou `FAILED`, o Order executa:

```text
PAYMENT_PENDING → CONFIRMED
```

Se o cliente quiser tentar novamente a partir daí, cria-se um Payment novo, com novo `payment_id` e nova idempotency key.

## 14. Máquina de estados principal

A confirmação explícita do cliente precede a aprovação humana. `CONFIRMED` é o único estado pagável.

```text
DRAFT
 ├─> CANCELLED                      (cancelamento pelo cliente — somente em DRAFT)
 ├─> EXPIRED                        (TTL de DRAFT — §5.1)
 ├─> CONFIRMED                      (confirmação do cliente; requires_approval = false)
 └─> REQUIRES_APPROVAL              (confirmação do cliente; requires_approval = true)
        ├─> CANCELLED               (Approval REJECTED)
        └─> CONFIRMED               (Approval APPROVED)

CONFIRMED
 └─> PAYMENT_PENDING                (criação de Payment)

PAYMENT_PENDING
 ├─> PAID                           (Payment APPROVED — provider/backend)
 └─> CONFIRMED                       (Payment REJECTED/EXPIRED/CANCELLED/FAILED — §13)

PAID
 └─> FULFILLING                     (SPEC-005)
       ├─> COMPLETED
       └─> FULFILLMENT_FAILED
              └─> FULFILLING        (reentrada por comando explícito — SPEC-005 §5.1)
```

`FULFILLMENT_FAILED → FULFILLING` foi acrescentada em 2026-09-07, na implementação da SPEC-005: com o mapeamento normativo de SPEC-005 §5.2, um fulfillment em `FAILED` ou `RECONCILIATION_REQUIRED` deixa o Order em `FULFILLMENT_FAILED`, e a reentrada prevista em SPEC-005 §5.1 não teria caminho sem essa aresta. A reentrada é **sempre por comando explícito**, nunca automática, e não gera nova cobrança. Sem ela, um Order pago cujo cartão foi reativado permaneceria permanentemente sem entrega.

Transições inválidas => `INVALID_ORDER_STATE_TRANSITION`.

Regras complementares:

- o cliente pode cancelar **somente** em `DRAFT`. `REQUIRES_APPROVAL`, `CONFIRMED`, `PAYMENT_PENDING` e `PAID` não admitem cancelamento pelo cliente no MVP;
- `PAID` é terminal nesta SPEC e não admite reversão: reembolso está fora do escopo do MVP;
- `PAYMENT_PENDING → CONFIRMED` é a transição que habilita nova tentativa comercial de pagamento (§13);
- somente `Payment APPROVED`, estabelecido pelo provider/backend, produz `PAID`.

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

Cobrir também, decorrente das definições desta SPEC:

- limiar de aprovação em `199,99`, `200,00` (ambos sem aprovação) e `200,01` (com aprovação);
- `DRAFT → REQUIRES_APPROVAL` pela confirmação do cliente, e `REQUIRES_APPROVAL → CONFIRMED` somente após `Approval APPROVED`;
- `Approval REJECTED` ⇒ `Order CANCELLED`;
- retorno `PAYMENT_PENDING → CONFIRMED` para cada terminal não aprovado, seguido de nova tentativa com novo `payment_id` e nova key;
- timeout do provider deixando `Payment CREATED`, `Order PAYMENT_PENDING`, `Idempotency IN_PROGRESS`, sem segundo POST automático;
- replay da mesma key em `IN_PROGRESS` sem nova cobrança;
- dois `create_payment` concorrentes resultando em no máximo uma tentativa ativa;
- webhook e polling concorrentes com resultado único e monotônico;
- `DRAFT` expirado não confirmável.

## 18. Segurança
- nenhuma tool `set_order_status`;
- nenhuma tool `set_payment_status`;
- nenhuma tool `mark_order_as_paid`;
- nenhuma tool `apply_discount`;
- backend deriva valores críticos.

## 19. Aceite
Quotes/Orders preservam snapshots, state machine é respeitada, >200 exige aprovação, payment é idempotente, webhook é deduplicado, user message não muda pagamento, e nenhum cenário crítico permite cobrança duplicada.
