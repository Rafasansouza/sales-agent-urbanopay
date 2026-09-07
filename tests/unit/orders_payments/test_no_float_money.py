"""Prova por AST que os caminhos de dinheiro de SPEC-003 não usam float.

Fonte: CLAUDE.md, ADR-012, SPEC-003 §10. `Decimal` em Python, `NUMERIC` no
PostgreSQL — nunca `float`, em nenhum ponto do caminho.

O detector é o mesmo em espírito do de `tests/unit/fare/test_no_float.py`, mas
deliberadamente independente: cada guarda se sustenta sozinha, sem que um teste
importe outro. Ele é autotestado abaixo, para provar que **reprova de verdade**
quando o float existir.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "apps" / "api" / "src" / "urbanopay"

# Todo caminho por onde um valor monetário de SPEC-003 transita.
MONEY_PATHS = (
    SRC_ROOT / "modules" / "orders",
    SRC_ROOT / "modules" / "approvals",
    SRC_ROOT / "modules" / "payments",
    SRC_ROOT / "core" / "idempotency.py",
    SRC_ROOT / "db" / "idempotency.py",
    SRC_ROOT / "providers" / "payments",
)


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


def _python_files() -> list[Path]:
    files: list[Path] = []
    for target in MONEY_PATHS:
        if target.is_file():
            files.append(target)
        else:
            files.extend(sorted(target.rglob("*.py")))
    return files


@pytest.mark.unit
def test_caminhos_de_dinheiro_nao_usam_float() -> None:
    offenders: dict[str, list[str]] = {}
    files = _python_files()
    assert len(files) > 10, "os módulos de SPEC-003 deveriam existir"

    for path in files:
        found = find_float_usages(path.read_text(encoding="utf-8"))
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, f"float em caminho financeiro (proibido por CLAUDE.md): {offenders}"


@pytest.mark.unit
def test_migrations_de_spec003_nao_usam_float() -> None:
    """A escala do dinheiro no schema é `Numeric(12, 2)`, nunca ponto flutuante."""
    versions = SRC_ROOT / "db" / "migrations" / "versions"
    alvos = sorted(versions.glob("*ord0001*.py")) + sorted(versions.glob("*pay0001*.py"))
    assert len(alvos) == 2, "as migrations ord0001 e pay0001 deveriam existir"

    offenders: dict[str, list[str]] = {}
    for path in alvos:
        found = find_float_usages(path.read_text(encoding="utf-8"))
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, f"float em migration financeira: {offenders}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "snippet",
    [
        "amount = 50.0",
        "total = float(valor)",
        "def cobrar(v: float) -> None: ...",
        "limite = 2e2",
    ],
)
def test_detector_flagra_float(snippet: str) -> None:
    assert find_float_usages(snippet), f"O detector deixou passar: {snippet!r}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "snippet",
    [
        "from decimal import Decimal\namount = Decimal('50.00')",
        "casas = 2",
        "coluna = Numeric(12, 2)",
        "texto = '50.00'",
    ],
)
def test_detector_nao_gera_falso_positivo(snippet: str) -> None:
    assert not find_float_usages(snippet)
