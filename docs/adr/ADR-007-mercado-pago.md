# ADR-007 — Mercado Pago Sandbox, Pix e Idempotência de Pagamentos

**Status:** Aceito  
**Data:** 2026-08-23

## Decisão
Mercado Pago Checkout Transparente/Orders API, Pix, somente credenciais de teste. Provider encapsulado por `PaymentProvider`/`MercadoPagoPaymentProvider`.

## Regras
- amount vem de `order.total`;
- usar `X-Idempotency-Key`;
- retries da mesma tentativa reutilizam a key;
- nova tentativa após rejeição cria novo payment/key;
- webhook é assíncrono e deduplicado;
- validar origem/assinatura quando aplicável;
- webhook pode disparar consulta/validação de estado oficial;
- Order pode ter N Payments, mas no máximo um APPROVED;
- proteger também com transação/constraint;
- timeout de criação é estado desconhecido, não falha definitiva;
- reconciliation job corrige divergências;
- nunca polling agressivo pelo agente;
- Access Token somente backend;
- FakePaymentProvider para testes locais/CI.

## Métricas críticas
`duplicate_charges=0`, `orders_with_more_than_one_approved_payment=0`.

## Princípio final
Uma solicitação pode ser repetida. Seu efeito financeiro não.
