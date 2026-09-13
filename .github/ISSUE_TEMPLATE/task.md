---
name: Tarefa de desenvolvimento
about: Tarefa vinculada a uma SPEC aceita
title: "[<dominio>] "
labels: task
---

## Objetivo

<!-- O que precisa existir ao final, em uma frase. -->

## Documento de origem

<!--
Toda tarefa de desenvolvimento nasce de um documento aceito.

- SPEC:
- Seção:
- ADRs aplicáveis:

Se não há SPEC, esta issue não é tarefa de desenvolvimento: é solicitação de
decisão de produto ou de arquitetura. Use o template correspondente ou abra a
discussão antes.
-->

## Domínio afetado

<!-- Ex.: fare, identity, cards, orders, payments, approvals, fulfillment -->

## Critério de aceite

<!-- Copiado ou derivado da seção de aceite da SPEC. -->

- [ ]
- [ ]

## Testes esperados

- unit:
- integration:
- e2e:
- eval:

## Pendências que podem bloquear

<!--
Consulte docs/OPEN-QUESTIONS.md. Bloqueios conhecidos hoje:

- A-05 — módulo catalog sem SPEC (bloqueia TICKET_PURCHASE)
- A-06 — calculate_usage_cost sem especificação
- A-07 — interface de aprovação humana sem especificação
- A-08 — stack do frontend sem ADR (ADR-011 Proposta)
- H-05 — compatibilidade de langgraph com Python 3.13 não validada; verificar
  antes de instalar a dependência (Etapa 2 da SPEC-004)

Resolvida em 2026-09-08: H-11, pelo ADR-014 (persistência do estado
conversacional pertence à aplicação; sem checkpointer nativo do LangGraph).
A Etapa 2 fica arquiteturalmente desbloqueada — H-05 continua valendo.
-->

## Fora de escopo

<!-- O que esta tarefa deliberadamente não faz. -->
