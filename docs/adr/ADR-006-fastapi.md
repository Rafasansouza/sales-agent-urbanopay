# ADR-006 — FastAPI como Framework da API Backend

**Status:** Aceito  
**Data:** 2026-08-23

## Decisão
Adotar FastAPI + Pydantic + type hints + OpenAPI como camada HTTP.

## Regras
- routers finos;
- regras ficam em application/domain services;
- schemas HTTP não precisam ser os mesmos objetos do domínio/ORM;
- versionar `/api/v1`;
- async somente onde houver I/O;
- dependency injection explícita;
- authentication boundary na API e authorization também no domínio;
- webhook de pagamento entra direto no PaymentService, nunca no LLM;
- erros possuem `error.code` estável e `trace_id`;
- sem stack traces/secrets em respostas;
- valores monetários em string decimal;
- timestamps ISO 8601;
- IDs opacos.

## Alternativas
Flask, Django/DRF, NestJS e API somente no Next.js foram considerados.

## Princípio final
A API valida e transporta a intenção. O domínio decide o que significa e se pode ser executada.
