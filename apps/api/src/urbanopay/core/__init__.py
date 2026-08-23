"""Infraestrutura transversal da aplicação.

Este pacote concentra o que atravessa todos os módulos de domínio:
configuração, envelope de erro, logging estruturado e telemetria.

Restrição: `core` não contém regra de negócio. Regras vivem nos módulos de
domínio, sob `urbanopay.modules`.
"""
