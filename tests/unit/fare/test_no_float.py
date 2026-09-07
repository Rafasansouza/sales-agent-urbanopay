"""Prova por AST que o módulo fare não usa float (SPEC-001 §7, CLAUDE.md).

Varre todo o código-fonte de `modules/fare/**` e reprova:

- qualquer literal float (`0.15`, `6.0`, ...);
- qualquer chamada a `float(...)`;
- qualquer anotação `float`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FARE_ROOT = REPO_ROOT / "apps" / "api" / "src" / "urbanopay" / "modules" / "fare"


def find_float_usages(source: str) -> list[str]:
    """Devolve descrições de cada uso de float encontrado no código."""
    tree = ast.parse(source)
    usages: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and type(node.value) is float:
            usages.append(f"literal float {node.value!r} (linha {node.lineno})")
        elif isinstance(node, ast.Name) and node.id == "float":
            usages.append(f"referência a float (linha {node.lineno})")
    return usages


@pytest.mark.unit
def test_modulo_fare_nao_usa_float() -> None:
    offenders: dict[str, list[str]] = {}
    files = sorted(FARE_ROOT.rglob("*.py"))
    assert files, "módulo fare deveria existir"

    for path in files:
        found = find_float_usages(path.read_text(encoding="utf-8"))
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, f"float em caminho tarifário (proibido por SPEC-001 §7): {offenders}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "snippet",
    [
        "x = 0.15",
        "y = float('7.5')",
        "def f(v: float) -> None: ...",
        "z = 1e2",
    ],
)
def test_detector_flagra_float(snippet: str) -> None:
    """O detector reprova de verdade cada forma de uso de float."""
    assert find_float_usages(snippet)


@pytest.mark.unit
@pytest.mark.parametrize(
    "snippet",
    [
        "from decimal import Decimal\nx = Decimal('0.15')",
        "n = 15",
        "s = '7.50'",
    ],
)
def test_detector_nao_gera_falso_positivo(snippet: str) -> None:
    assert not find_float_usages(snippet)
