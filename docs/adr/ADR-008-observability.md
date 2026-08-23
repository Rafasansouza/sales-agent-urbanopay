# ADR-008 — Langfuse e OpenTelemetry para Observabilidade End-to-End

**Status:** Aceito  
**Data:** 2026-08-23

## Decisão
OpenTelemetry é o padrão transversal de tracing/metrics/context propagation. Langfuse é especializado em LLM/agent observability, tokens, custo, prompts, scores e evals.

## Correlação
Usar `trace_id`, `conversation_id`, `session_id` e IDs de Quote/Order/Payment/Fulfillment quando existirem. Conversation pode conter múltiplos traces.

## Regras
- instrumentar FastAPI, services, external calls e agent nodes relevantes;
- não criar span para cada função trivial;
- LLM generations registram provider/model/tokens/cost/latency;
- tool calls registram nome/duração/resultado sem PII;
- OTP nunca é registrado;
- CPF/cartão/secrets são redacted/masked;
- logs JSON estruturados correlacionados por trace_id;
- traces não são fonte de verdade financeira;
- outage de observabilidade não derruba business flow;
- se sanitização falhar, preferir não exportar.

## KPIs
A observabilidade deve permitir medir qualidade, custo, latência, tool success e conversão.

## Princípio final
Toda ação crítica deve ser explicável sem transformar observabilidade em source of truth ou risco de vazamento.
