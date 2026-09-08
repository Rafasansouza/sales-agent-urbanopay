"""Infraestrutura do Sales Agent (SPEC-004).

Único ponto do módulo que conhece persistência: aqui os serviços de aplicação
dos módulos de negócio são montados sobre uma fábrica de sessões (ADR-006,
ADR-012).

Não existe repositório, model ORM nem migration própria do agente: o estado
conversacional é efêmero nesta etapa, e sua persistência depende do ADR-014
(H-11).
"""
