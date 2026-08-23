#!/usr/bin/env python3
"""Hook Stop — verificações rápidas ao encerrar um turno com alterações.

Conforme AGENT-HARNESS §10, roda checks rápidos quando houver alterações. A
suíte completa permanece em `/verify` e na CI.

Comportamento **advisório**: o hook reporta e nunca bloqueia o encerramento.
Um hook Stop bloqueante em falha de lint pode aprisionar a sessão — decisão
registrada em `docs/OPEN-QUESTIONS.md` (H-03).

Contrato: falha aberto. Qualquer erro inesperado resulta em saída 0 silenciosa.
"""

from __future__ import annotations

import json
import subprocess
import sys

GIT_TIMEOUT_SECONDS = 5
CHECK_TIMEOUT_SECONDS = 90

# Extensões que disparam verificação de qualidade.
PYTHON_SUFFIX = ".py"


def run(command: tuple[str, ...], timeout: int) -> tuple[int, str] | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def changed_files() -> list[str] | None:
    """Arquivos alterados na árvore de trabalho, rastreados ou não."""
    result = run(("git", "status", "--porcelain"), GIT_TIMEOUT_SECONDS)
    if result is None or result[0] != 0:
        return None

    files: list[str] = []
    for line in result[1].splitlines():
        # Formato: XY <caminho>, com possível " -> " em renomeações.
        entry = line[3:].strip() if len(line) > 3 else ""
        if not entry:
            continue
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        files.append(entry.strip('"'))
    return files


def summarize(output: str, max_lines: int = 12) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    restantes = len(lines) - max_lines
    return "\n".join([*lines[:max_lines], f"... (+{restantes} linha(s))"])


def main() -> int:
    try:
        raw = sys.stdin.read()
        json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    files = changed_files()
    if not files:
        # Sem alterações, ou git indisponível: nada a verificar.
        return 0

    python_files = [f for f in files if f.endswith(PYTHON_SUFFIX)]
    if not python_files:
        # Alterações apenas em documentação ou configuração.
        return 0

    problems: list[str] = []
    skipped: list[str] = []

    checks = (
        ("ruff format --check", ("uv", "run", "ruff", "format", "--check", ".")),
        ("ruff check", ("uv", "run", "ruff", "check", ".")),
    )

    for label, command in checks:
        result = run(command, CHECK_TIMEOUT_SECONDS)
        if result is None:
            skipped.append(label)
            continue
        code, output = result
        if code != 0:
            problems.append(f"[{label}]\n{summarize(output)}")

    if not problems and not skipped:
        return 0

    report: list[str] = ["", "── verify_before_stop (advisório) ──"]
    report.append(f"{len(python_files)} arquivo(s) Python alterado(s).")

    if problems:
        report.append("")
        report.append("Verificações rápidas com falha:")
        report.extend(problems)
        report.append("")
        report.append("Rode `.\\scripts\\dev.ps1 verify` para a suíte completa.")

    if skipped:
        report.append("")
        report.append("Não executado (ferramenta indisponível): " + ", ".join(skipped))

    sys.stdout.write("\n".join(report) + "\n")

    # Advisório por decisão: sempre 0, nunca bloqueia o encerramento.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Falha aberto por contrato: este hook nunca bloqueia o encerramento.
        sys.exit(0)
