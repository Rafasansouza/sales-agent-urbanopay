"""Camada de aplicação do Sales Agent (SPEC-004).

Adapta os serviços determinísticos existentes para contratos seguros ao LLM.
Não é uma camada de renomeação: é aqui que a sessão vira identidade, que passos
cross-module são compostos, que a idempotency key é derivada e que erro de
domínio vira envelope sanitizado.

Depende de `application` dos módulos de negócio e do próprio `domain`. Nunca de
`infrastructure` de outro módulo, de SQLAlchemy ou de `AsyncSession`.
"""
