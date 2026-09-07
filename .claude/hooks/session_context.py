#!/usr/bin/env python3
"""Hook SessionStart — injeta contexto leve no início da sessão.

Conforme AGENT-HARNESS §10, este hook adiciona apenas contexto leve: branch
atual, estado da árvore de trabalho, commit recente e um lembrete da hierarquia
documental. Ele **não** despeja documentos no contexto.

Contrato: falha aberto. Qualquer erro inesperado resulta em saída 0 sem
contexto adicional, para nunca impedir o início de uma sessão.

## Origem determinística

Toda consulta git é feita com `-C <raiz>`, onde a raiz vem de
`CLAUDE_PROJECT_DIR` e, na sua ausência, da localização deste arquivo. Sem
isso, o contexto descreveria o repositório que por acaso contém o diretório de
trabalho — e uma sessão iniciada em outro repositório apresentaria branch e
estado da árvore errados, com aparência de corretos.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

# Limites conservadores: contexto de sessão precisa ser curto.
GIT_TIMEOUT_SECONDS = 5
MAX_DIRTY_FILES_LISTED = 10

PROTECTED_BRANCHES = ("main", "master")

# Este arquivo vive em `<raiz>/.claude/hooks/`, logo a raiz é o segundo pai.
_ROOT_DEPTH_FROM_THIS_FILE = 2


def project_root() -> Path:
    """Raiz canônica do projeto, resolvida sem consultar o cwd."""
    raw = os.environ.get("CLAUDE_PROJECT_DIR")
    if raw:
        candidate = Path(raw)
        if candidate.is_dir():
            return candidate.resolve()

    return Path(__file__).resolve().parents[_ROOT_DEPTH_FROM_THIS_FILE]


def run_git(root: Path, *args: str) -> str | None:
    """Executa um comando git no repositório do projeto, ou None em falha."""
    try:
        result = subprocess.run(
            ("git", "-C", str(root), *args),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            cwd=root,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None
    return result.stdout.strip()


def build_context(root: Path) -> str:
    lines: list[str] = ["## Contexto da sessão — UrbanoPay Mobilidade", ""]

    branch = run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        lines.append(f"- Branch: `{branch}`")
        if branch in PROTECTED_BRANCHES:
            lines.append(
                f"- ⛔ **`{branch}` é branch protegida.** Nunca implemente aqui. "
                "Crie uma branch dedicada antes de qualquer alteração."
            )

    status = run_git(root, "status", "--porcelain")
    if status is None:
        lines.append("- Estado da árvore: indisponível")
    elif status == "":
        lines.append("- Estado da árvore: limpa")
    else:
        entries = status.splitlines()
        lines.append(f"- Estado da árvore: {len(entries)} arquivo(s) alterado(s)")
        for entry in entries[:MAX_DIRTY_FILES_LISTED]:
            lines.append(f"  - `{entry.strip()}`")
        if len(entries) > MAX_DIRTY_FILES_LISTED:
            restantes = len(entries) - MAX_DIRTY_FILES_LISTED
            lines.append(f"  - ... e {restantes} arquivo(s) a mais")

    last_commit = run_git(root, "log", "-1", "--pretty=%h %s")
    if last_commit:
        lines.append(f"- Último commit: `{last_commit}`")

    lines.extend(
        [
            "",
            "### Hierarquia documental",
            "",
            "`PRD → SPEC → ADR → Agent Harness → Implementação`",
            "",
            "Leia a documentação relevante antes de implementar. Não carregue todas "
            "as SPECs: carregue apenas a do domínio da tarefa.",
            "",
            "- `docs/prd/PRD.md` — escopo e objetivos",
            "- `docs/specs/` — comportamento funcional",
            "- `docs/adr/` — decisões arquiteturais aceitas",
            "- `docs/OPEN-QUESTIONS.md` — conflitos e lacunas conhecidos",
            "",
            "### Lembretes desta fase",
            "",
            "- Implementadas: **SPEC-001** (fare), **SPEC-002** (identity, cards) e "
            "**SPEC-003** (orders, approvals, payments), esta última restrita a "
            "`RECHARGE`.",
            "- Não implementadas: **SPEC-004** (agente) e **SPEC-005** (fulfillment).",
            "- Persistência (ADR-012) está implementada: SQLAlchemy 2.x, psycopg 3, "
            "Alembic, Repository e Unit of Work, com a cadeia de migrations "
            "`fare0001 → fare0002 → idc0001 → ord0001 → pay0001`.",
            "- ADR-011 (frontend) está como **Proposta**: nada pode se apoiar nele.",
            "- Bloqueios conhecidos: **A-05** (catálogo sem SPEC), **A-06** "
            "(`calculate_usage_cost`), **A-07** (superfície de aprovação humana), "
            "**H-11** (persistência do LangGraph exige ADR próprio).",
            "- Não invente regra de negócio para preencher lacuna documental. Reporte a lacuna.",
            "- Divergência entre código, PRD, SPEC e ADR deve ser reportada, "
            "não resolvida silenciosamente.",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    # A entrada é lida e descartada: este hook não depende do payload, mas o
    # stdin precisa ser consumido para não bloquear o processo chamador.
    with contextlib.suppress(OSError, ValueError):
        sys.stdin.read()

    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": build_context(project_root()),
        }
    }
    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Falha aberto por contrato: nunca impedir o início da sessão por causa
        # deste hook.
        sys.exit(0)
