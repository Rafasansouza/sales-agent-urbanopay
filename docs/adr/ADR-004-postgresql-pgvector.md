# ADR-004 — PostgreSQL como Source of Truth e pgvector restrito à busca semântica

**Status:** Aceito  
**Data:** 2026-08-23

## Decisão
PostgreSQL é a fonte autoritativa para Customer, Card, saldo, Fare, FareRule, Product, Quote, Order, Approval, Payment, Fulfillment, Ledger, Ticket e auditoria. pgvector é usado somente para recuperação semântica de FAQ, descrições e conteúdos textuais.

## Regra
Se existe chave, estado, preço, validade, relacionamento ou regra objetiva, usar consulta relacional. Busca vetorial pode encontrar qual entidade/conteúdo parece relevante, mas dados atuais devem ser revalidados no serviço oficial.

## Segurança
Sales Agent não possui SQL genérico. Embeddings não devem conter PII sensível.

## Infra
Uma instância PostgreSQL compartilhada no MVP; schemas lógicos por domínio quando apropriado; migrations versionadas; constraints para invariantes; seeds somente fictícios.

## Alternativas rejeitadas
Banco vetorial dedicado, NoSQL principal, Redis como estado principal, RAG como fonte de preços.

## Princípio final
Similaridade encontra contexto. O banco relacional determina fatos.
