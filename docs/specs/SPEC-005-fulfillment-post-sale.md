# SPEC-005 — Fulfillment & Post-Sale

**Projeto:** UrbanoPay Mobilidade  
**Dependências:** SPEC-001..004

## 1. Objetivo
Executar a entrega após pagamento aprovado: recarga, bilhete fictício, ledger, idempotência, reconciliação, comprovante e consultas de pós-venda.

## 2. Princípio
`PAYMENT APPROVED` e `FULFILLMENT COMPLETED` são eventos distintos. Falha de fulfillment nunca cria nova cobrança automaticamente.

## 3. Tipos
- `RECHARGE`;
- `TICKET_ISSUANCE`.

## 4. Entidades
- `Fulfillment`;
- `RechargeTransaction`;
- `CardLedgerEntry`;
- `Ticket`;
- `Receipt`;
- `FulfillmentAttempt`;
- `ReconciliationRecord`.

## 5. Estados do Fulfillment
- `PENDING`;
- `PROCESSING`;
- `COMPLETED`;
- `FAILED`;
- `RECONCILIATION_REQUIRED`.

Pré-condição: `Order PAID` e Payment aprovado.

## 6. Recarga
Fluxo: Order PAID -> validar cartão -> RechargeTransaction -> ledger -> atualizar saldo -> COMPLETED.

`RechargeTransaction`: IDs, amount, balance_before, balance_after, status, idempotency_key, timestamps.

## 7. Ledger
Toda alteração de saldo gera `CardLedgerEntry`. MVP usa `RECHARGE_CREDIT`. Atualização do ledger, saldo e status deve ocorrer na mesma transação de banco.

Concorrência deve utilizar lock/transação apropriados. Dinheiro usa Decimal/NUMERIC.

## 8. Idempotência
Chave conceitual `recharge:{order_id}`. Reprocessar mesmo Order retorna resultado existente; nunca duplica crédito.

## 9. Ticket
Campos: `ticket_id`, `order_id`, `customer_id`, `product_id`, `status`, `issued_at`, `valid_from`, `valid_until`, `qr_token`.

Status: `ACTIVE`, `USED`, `EXPIRED`, `CANCELLED`. QR é fictício e deve conter token opaco, nunca PII.

Emissão também é idempotente, respeitando `quantity` do OrderItem.

## 10. Independência do agente
Fulfillment é iniciado pelo backend após pagamento; continua mesmo se usuário fechar o navegador ou LLM ficar indisponível.

## 11. Falhas
- falha conhecida antes de efeito => `FAILED`;
- falha na transação local => rollback;
- resultado externo desconhecido => `RECONCILIATION_REQUIRED`;
- nunca retry cego em outcome desconhecido.

Classificar erros: `RETRYABLE`, `NON_RETRYABLE`, `UNKNOWN_OUTCOME`.

Sugestão inicial: máximo 3 retries automáticos para erros comprovadamente retryable; depois revisão manual.

## 12. Reconciliação
`ReconciliationRecord`: id, fulfillment, reason, status, attempts, last_checked_at, resolved_at, resolution.

Status: `PENDING`, `RESOLVED`, `MANUAL_REVIEW`, `FAILED`.

No MVP local, job pode procurar `Order PAID` sem fulfillment conhecido e comparar RechargeTransaction/Ledger.

## 13. Comprovante
Gerar somente após `COMPLETED`, com indicação clara de documento simulado/sem validade fiscal ou como bilhete real.

## 14. Pós-venda
Permitir, autenticado e autorizado:
- saldo;
- pedido;
- payment status;
- fulfillment status;
- ticket;
- receipt.

## 15. Tools permitidas ao Sales Agent
- `get_fulfillment_status`;
- `get_ticket`;
- `get_receipt`;
- `get_card_balance`.

## 16. Tools proibidas
- `apply_recharge`;
- `issue_ticket`;
- `retry_fulfillment`;
- `reconcile_fulfillment`;
- `set_ticket_status`;
- `set_balance`.

## 17. Observabilidade
Correlacionar `conversation_id`, `trace_id`, customer/card/order/payment/fulfillment/recharge/ticket/receipt IDs. Não registrar CPF completo, cartão completo, OTP ou QR token sensível.

## 18. Métricas
- fulfillments started/completed/failed;
- recharges completed;
- tickets issued;
- retry count;
- reconciliation count/success;
- fulfillment latency;
- `duplicate_fulfillment_effects = 0`;
- `paid_orders_without_known_fulfillment_state = 0`.

## 19. Invariantes
1. nenhum fulfillment sem Order PAID;
2. nenhuma recarga sem Payment APPROVED;
3. um Order de recarga produz no máximo um efeito financeiro;
4. saldo corresponde ao ledger;
5. ticket não excede quantidade comprada;
6. failure não gera nova cobrança;
7. comprovante de sucesso somente após COMPLETED;
8. LLM nunca altera saldo.

## 20. Recuperação
Estados críticos ficam persistidos. Após restart, localizar `PAID`, `FULFILLING` e `RECONCILIATION_REQUIRED`. Job conceitual `find_stale_fulfillments` pode recuperar operações paradas.

## 21. Testes obrigatórios
Cobrir recarga normal, sem pagamento, cartão bloqueado, duplicidade, concorrência, rollback, failure depois de payment, retry seguro, unknown outcome, ticket, ticket duplicado, cross-user, consulta saldo, prompt injection, valor adulterado, receipt, reconciliação positiva/negativa e restart.

## 22. Aceite
Somente Orders pagos são entregues, saldo/ledger são atômicos e idempotentes, tickets não duplicam, falhas são conhecidas/reconciliáveis e pós-venda usa fontes oficiais.
