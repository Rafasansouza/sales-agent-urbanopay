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

### Renomeação de 2026-09-14

`apps/api` passou a chamar-se **`apps/backend`** e `apps/web`, **`apps/frontend`**.

É mudança de **nome**, não de arquitetura: as fronteiras de módulo continuam
exatamente as declaradas acima, o monólito segue modular e nada foi extraído
para serviço separado.

Registrado aqui, e não espalhado por nota em cada documento, porque foi aqui
que a estrutura foi decidida.

Duas propostas foram avaliadas na mesma ocasião e **rejeitadas**, por
contrariarem decisões aceitas:

| Proposta | Por que não |
|---|---|
| `apps/agent` como aplicação separada | `agent` é **módulo** deste monólito, e o Sales Agent chama os serviços **em processo** (ADR-003). Separá-lo é extração de serviço, que este ADR admite "só por necessidade real, e sempre via ADR" — e traria rede, retries e observabilidade distribuída, exatamente o que a seção "Contexto" rejeitou |
| `apps/database` como aplicação | Não é aplicação: nada executa lá. O PostgreSQL roda em container, e a **camada** de persistência é decisão do ADR-012, que a coloca em `db/` com os models em `modules/<dominio>/infrastructure/`. Movê-los para fora inverteria a direção de dependência que o teste de arquitetura protege |

## Alternativas rejeitadas
Microservices prematuros; monólito tradicional sem fronteiras; multi-repo.

## Consequências
Positivas: simplicidade operacional, testes e contexto centralizados. Negativas: deploy conjunto e disciplina arquitetural obrigatória.

## Regra para Claude Code
Respeitar fronteiras, evitar dependências circulares, consultar SPEC/ADR antes de mudanças estruturais e nunca mover regra de negócio para prompt.
