"""Módulos de domínio do monólito modular.

Fonte: ADR-001.

Fronteiras declaradas: `agent`, `catalog`, `fare`, `identity`, `cards`,
`orders`, `payments`, `approvals`, `fulfillment`, `tickets`, `postsale`,
`observability`.

Regras de fronteira:

- um módulo não acessa internals nem tabelas de outro módulo livremente;
- a comunicação usa a interface pública do módulo de destino;
- dependência circular entre módulos é defeito;
- o módulo `agent` nunca executa SQL direto.

Cada subdiretório possui um `README.md` com a SPEC aplicável, as tools
permitidas, as tools proibidas e os bloqueios conhecidos. Leia-o antes de
implementar.
"""
