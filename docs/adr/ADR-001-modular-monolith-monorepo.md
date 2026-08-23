# ADR-001 — Arquitetura Modular Monolítica em Monorepo

**Status:** Aceito  
**Data:** 2026-08-23

## Decisão
Adotar monorepo + monólito modular. Backend inicialmente é uma única aplicação, mas com fronteiras explícitas: agent, catalog, fare, identity, cards, orders, payments, approvals, fulfillment, tickets, postsale e observability.

## Contexto
Microservices adicionariam comunicação de rede, deploys independentes, retries e observabilidade distribuída sem necessidade atual. Um monólito sem modularização criaria acoplamento.

## Regras
- módulos não acessam internals/tabelas de outros domínios livremente;
- Agent nunca executa SQL direto;
- comunicação interna prioritariamente em processo;
- PostgreSQL é compartilhado fisicamente, com separação lógica;
- eventos internos podem existir sem Kafka/RabbitMQ;
- extração futura de serviços só por necessidade real.

## Estrutura inicial
`apps/api`, `apps/web`, `docs`, `infra`, `tests`, `scripts`, `.claude`, `.github`.

## Alternativas rejeitadas
Microservices prematuros; monólito tradicional sem fronteiras; multi-repo.

## Consequências
Positivas: simplicidade operacional, testes e contexto centralizados. Negativas: deploy conjunto e disciplina arquitetural obrigatória.

## Regra para Claude Code
Respeitar fronteiras, evitar dependências circulares, consultar SPEC/ADR antes de mudanças estruturais e nunca mover regra de negócio para prompt.
