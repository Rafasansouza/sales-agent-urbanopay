"""Domínio de identidade (SPEC-002): Customer, Session e OTPChallenge.

Camada pura — sem SQLAlchemy, psycopg, Alembic ou FastAPI (verificado por
teste de arquitetura). A cadeia de autoridade que este módulo materializa:

    sessão anônima → identificação → OTP → sessão autenticada → customer_id

O LLM nunca decide autenticação; tudo aqui é código determinístico.
"""
