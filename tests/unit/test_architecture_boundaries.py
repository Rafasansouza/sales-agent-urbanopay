"""Teste de arquitetura: o domínio não importa infraestrutura de persistência.

Fonte: ADR-012 — "o domínio não importa SQLAlchemy", verificado por teste, não
apenas por regra escrita.

Cobre dois alvos:

1. `modules/*/domain/**` — nenhum arquivo pode importar `sqlalchemy`,
   `psycopg` ou `alembic`. Hoje nenhum módulo possui `domain/`; o teste passa
   em vácuo e passa a valer automaticamente quando o primeiro nascer.
2. `core/persistence.py` — o port do Unit of Work é a fronteira declarada e
   também não pode importar persistência. Esta é a asserção não-vácua atual.

O detector é testado contra arquivos sintéticos para provar que **falha de
verdade** quando o vazamento existir.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "apps" / "api" / "src" / "urbanopay"
MODULES_ROOT = SRC_ROOT / "modules"

FORBIDDEN_IN_DOMAIN = frozenset({"sqlalchemy", "psycopg", "alembic"})


def find_forbidden_imports(source: str, forbidden: frozenset[str]) -> list[str]:
    """Devolve os imports proibidos encontrados no código-fonte.

    Considera `import x`, `import x.y`, `from x import ...` e
    `from x.y import ...`: a comparação é sempre pelo pacote raiz.
    """
    tree = ast.parse(source)
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden:
                    violations.append(alias.name)
        # `from . import x` tem module=None e nunca é import externo.
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            root = node.module.split(".")[0]
            if root in forbidden:
                violations.append(node.module)

    return violations


def _domain_files() -> list[Path]:
    return sorted(MODULES_ROOT.glob("*/domain/**/*.py"))


@pytest.mark.unit
def test_dominio_nao_importa_persistencia() -> None:
    """Nenhum arquivo em modules/*/domain/ importa SQLAlchemy, psycopg ou Alembic."""
    offenders: dict[str, list[str]] = {}

    for path in _domain_files():
        found = find_forbidden_imports(path.read_text(encoding="utf-8"), FORBIDDEN_IN_DOMAIN)
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, (
        "Camada de domínio importando infraestrutura de persistência "
        f"(proibido por ADR-012): {offenders}"
    )


@pytest.mark.unit
def test_port_de_persistencia_nao_importa_sqlalchemy() -> None:
    """`core/persistence.py` define o port e não pode conhecer a implementação."""
    port = SRC_ROOT / "core" / "persistence.py"
    assert port.is_file(), "core/persistence.py deveria existir (ADR-012)"

    found = find_forbidden_imports(port.read_text(encoding="utf-8"), FORBIDDEN_IN_DOMAIN)
    assert not found, f"core/persistence.py importa infraestrutura proibida: {found}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "snippet",
    [
        "import sqlalchemy",
        "import sqlalchemy.orm",
        "from sqlalchemy import select",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "import psycopg",
        "from psycopg import AsyncConnection",
        "import alembic",
        "from alembic import op",
    ],
)
def test_detector_flagra_vazamento(snippet: str) -> None:
    """Prova que o detector reprova de verdade cada forma de import proibido."""
    assert find_forbidden_imports(snippet, FORBIDDEN_IN_DOMAIN), (
        f"O detector deixou passar: {snippet!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "snippet",
    [
        "from decimal import Decimal",
        "from urbanopay.core.persistence import UnitOfWork",
        "from . import errors",
        "import dataclasses",
        # Nome parecido não é o pacote proibido: a comparação é pela raiz exata.
        "import sqlalchemy_utils_fake",
    ],
)
def test_detector_nao_gera_falso_positivo(snippet: str) -> None:
    """Imports legítimos do domínio não são flagrados."""
    assert not find_forbidden_imports(snippet, FORBIDDEN_IN_DOMAIN)


@pytest.mark.unit
def test_detector_funciona_em_arquivo_real(tmp_path: Path) -> None:
    """Simula o vazamento em um domain/ sintético e prova a detecção fim a fim."""
    fake_domain = tmp_path / "modules" / "fare" / "domain"
    fake_domain.mkdir(parents=True)
    offender = fake_domain / "entities.py"
    offender.write_text(
        "from sqlalchemy.orm import Mapped\n\nclass Fare:\n    pass\n",
        encoding="utf-8",
    )

    found = find_forbidden_imports(offender.read_text(encoding="utf-8"), FORBIDDEN_IN_DOMAIN)
    assert found == ["sqlalchemy.orm"]
