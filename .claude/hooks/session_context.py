#!/usr/bin/env python3
"""Hook SessionStart — injeta contexto leve no início da sessão.

Conforme AGENT-HARNESS §10, este hook adiciona apenas contexto leve: branch
atual, estado da árvore de trabalho, commit recente e um lembrete da hierarquia
documental. Ele **não** despeja documentos no contexto.

Contrato: falha aberto. Qualquer erro inesperado resulta em saída 0 sem
contexto adicional, para nunca impedir o início de uma sessão.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys

# Limites conservadores: contexto de sessão precisa ser curto.
GIT_TIMEOUT_SECONDS = 5
MAX_DIRTY_FILES_LISTED = 10

PROTECTED_BRANCHES = ("main", "master")


def run_git(*args: str) -> str | None:
    """Executa um comando git e devolve stdout, ou None em qualquer falha."""
    try:
        result = subprocess.run(
            ("git", *args),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None
    return result.stdout.strip()


def build_context() -> str:
    lines: list[str] = ["## Contexto da sessão — UrbanoPay Mobilidade", ""]

    branch = run_git("rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        lines.append(f"- Branch: `{branch}`")
        if branch in PROTECTED_BRANCHES:
            lines.append(
                f"- ⛔ **`{branch}` é branch protegida.** Nunca implemente aqui. "
                "Crie uma branch dedicada antes de qualquer alteração."
            )

    status = run_git("status", "--porcelain")
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

    last_commit = run_git("log", "-1", "--pretty=%h %s")
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
            "- SPEC-001 a SPEC-005 **não** estão implementadas.",
            "- ADR-011 (frontend) está como **Proposta**: nada pode se apoiar nele.",
            "- ADR-012 (persistência) está **Aceito** — SQLAlchemy 2.x, psycopg 3, "
            "Alembic, Repository, Unit of Work —, mas a implementação ainda não "
            "existe: dependências não instaladas, migrations não materializadas.",
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
            "additionalContext": build_context(),
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
