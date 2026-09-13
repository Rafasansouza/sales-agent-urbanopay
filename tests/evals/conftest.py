"""Fixtures da camada de evals.

Reusa a aplicação completa da camada E2E: avaliar o agente exige o sistema
inteiro no ar, porque o que se mede é **efeito**, não texto. O provider é o
`FakeLLMProvider` — determinístico, o que torna a meta de zero ação crítica
não autorizada exigível em CI (SPEC-004 §16).
"""

from __future__ import annotations

from tests.e2e.conftest import demo_client, migrated_e2e

__all__ = ["demo_client", "migrated_e2e"]
