# ADR-009 — Redis com Responsabilidade Restrita para Estado Efêmero

**Status:** Aceito  
**Data:** 2026-08-23

## Decisão
Redis é apenas store operacional efêmero: rate limiting, cache, contadores, cooldown e coordenação temporária. PostgreSQL continua autoritativo.

## Permitido
- rate limit de agent/auth/OTP/polling;
- cache reconstruível;
- locks temporários quando realmente necessários;
- contadores com TTL.

## Proibido como autoridade
- saldo;
- Order;
- Payment status;
- Fulfillment status;
- idempotência financeira exclusiva;
- ledger.

## Regras
- cache miss volta à source oficial;
- perda total de Redis não perde histórico;
- idempotency records financeiros ficam no PostgreSQL;
- lock Redis não substitui DB constraints;
- não usar Pub/Sub efêmero como único event bus financeiro;
- Sales Agent não recebe redis_get/set/delete;
- chaves temporárias usam TTL e IDs internos, não CPF.

## Princípio final
Se perdermos Redis, podemos perder velocidade ou estado temporário. Não podemos perder a verdade da operação.
