"""Adaptadores de providers externos.

Fonte: ADR-007 (pagamento), ADR-010 (LLM).

Princípio comum: nenhum módulo de domínio conhece o SDK de um provider. O
domínio depende de uma porta tipada; este pacote implementa a porta.

Subpacotes:

- `llm` — abstração `LLMProvider` e Model Router (ADR-010);
- `payments` — abstração `PaymentProvider` (ADR-007).

Estado: não implementado. Ver o README de cada subdiretório.
"""
