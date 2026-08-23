"""Camada HTTP.

Fonte: ADR-006.

Regras: routers finos, sem regra de negócio. A camada HTTP valida a entrada,
delega para `application` e formata a saída. Ela nunca depende diretamente de
`infrastructure`.
"""
