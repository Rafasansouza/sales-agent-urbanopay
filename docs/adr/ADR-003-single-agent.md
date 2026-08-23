# ADR-003 — Agente Único vs Arquitetura Multiagente

**Status:** Aceito  
**Data:** 2026-08-23

## Decisão
Um único Sales Agent conversacional em runtime, usando serviços determinísticos especializados como tools. Não criar Fare Agent, Card Agent, Payment Agent etc.

## Motivo
Fare, Cards, Orders, Payments e Fulfillment trabalham com regras estruturadas e não ganham valor com outra camada probabilística. Multiagente aumentaria tokens, latência, custo, tracing e superfície de prompt injection.

## Critério para novo agente
Somente quando existir objetivo independente, contexto próprio, tools próprias, políticas diferentes ou benefício mensurável.

## Distinção
Subagentes do Claude Code para desenvolvimento/review não fazem parte da arquitetura runtime.

## Princípio final
Use agentes onde existe incerteza e linguagem. Use código onde existe regra.
