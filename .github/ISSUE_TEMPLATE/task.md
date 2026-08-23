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

- C-01 — ordem entre confirmação do passageiro e aprovação humana
- C-02 — retentativa de pagamento sem transição definida
- A-04 — composição de viagem exclusivamente de metrô
- A-05 — módulo catalog sem SPEC
- A-06 — calculate_usage_cost sem especificação
- A-07 — interface de aprovação humana sem especificação
- A-08 — stack do frontend sem ADR (ADR-011 Proposta)
- ADR-012 (persistência) com status Proposta
-->

## Fora de escopo

<!-- O que esta tarefa deliberadamente não faz. -->
