"""Fronteiras de negócio da UrbanoPay (ADR-001, ADR-017).

As sete fronteiras de ADR-001 com implementação: `fare`, `identity`, `cards`,
`orders`, `payments`, `approvals` e `fulfillment`. Cada uma com `domain/`,
`application/` e `infrastructure/`.

Um módulo não acessa internals nem tabelas de outro: a comunicação usa a
interface pública do módulo de destino. Dependência circular entre módulos é
defeito, e **nenhum deles conhece o agente**.
"""
