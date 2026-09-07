#!/usr/bin/env python3
"""Hook Stop — verificações rápidas ao encerrar um turno com alterações.

Conforme AGENT-HARNESS §10, roda checks rápidos quando houver alterações. A
suíte completa permanece em `/verify` e na CI.

Comportamento **advisório**: o hook reporta e nunca bloqueia o encerramento.
Um hook Stop bloqueante em falha de lint pode aprisionar a sessão — decisão
registrada em `docs/OPEN-QUESTIONS.md` (H-03).

Contrato: falha aberto. Qualquer erro inesperado resulta em saída 0 silenciosa.

## Escopo de análise é ancorado, nunca herdado do cwd

Este hook **não** usa `Path.cwd()` para decidir o que analisar. A raiz vem de
`CLAUDE_PROJECT_DIR` e, na sua ausência, da localização deste próprio arquivo.
Todo comando externo recebe a raiz explicitamente (`git -C <raiz>`, `ruff
<raiz>`) e roda com `cwd=<raiz>`.

O motivo é concreto: um `cd` durante a sessão faz o cwd apontar para um
subdiretório, e um escopo herdado do cwd reduziria **em silêncio** o conjunto
de arquivos verificados — o hook diria "tudo certo" tendo olhado uma fração do
repositório. Silêncio é o pior desfecho possível para uma verificação.

O cwd pode aparecer como informação contextual, nunca como raiz de análise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

GIT_TIMEOUT_SECONDS = 5
CHECK_TIMEOUT_SECONDS = 90

# Extensões que disparam verificação de qualidade.
PYTHON_SUFFIX = ".py"

# Este arquivo vive em `<raiz>/.claude/hooks/`, logo a raiz é o segundo pai.
_ROOT_DEPTH_FROM_THIS_FILE = 2


def project_root() -> Path:
    """Raiz canônica do projeto, resolvida sem consultar o cwd.

    Ordem de resolução:

    1. `CLAUDE_PROJECT_DIR`, quando definida e existente — é o contrato do
       Claude Code e a fonte preferida;
    2. a localização deste arquivo, como fallback determinístico.

    O fallback existe para que o hook continue correto quando invocado fora do
    Claude Code (por exemplo, em teste), e é seguro porque o caminho do próprio
    script não depende de onde o processo foi iniciado.
    """
    raw = os.environ.get("CLAUDE_PROJECT_DIR")
    if raw:
        candidate = Path(raw)
        if candidate.is_dir():
            return candidate.resolve()

    return Path(__file__).resolve().parents[_ROOT_DEPTH_FROM_THIS_FILE]


def run(command: tuple[str, ...], timeout: int, cwd: Path) -> tuple[int, str] | None:
    """Executa um comando externo a partir de `cwd`, sempre explícito."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=cwd,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def changed_files(root: Path) -> list[str] | None:
    """Arquivos alterados na árvore de trabalho, rastreados ou não.

    `git -C <raiz>` garante que o repositório inspecionado é o do projeto, e
    não aquele que por acaso contém o cwd. O formato porcelain devolve caminhos
    relativos à raiz do repositório, o que mantém o filtro por extensão
    independente de onde o processo roda.
    """
    result = run(("git", "-C", str(root), "status", "--porcelain"), GIT_TIMEOUT_SECONDS, root)
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


def emit(text: str) -> None:
    """Escreve o relatório sem depender do encoding do console.

    Em console cp1252 — o padrão em Windows — caracteres como `──` levantam
    `UnicodeEncodeError`. Combinado com o fail-open do contrato, isso fazia o
    relatório **desaparecer em silêncio**: o hook detectava o problema, tentava
    reportá-lo e o turno encerrava como se estivesse tudo certo. É o mesmo
    modo de falha que a ancoragem de escopo elimina, só que na saída.

    A escrita cai para bytes UTF-8 quando o encoding do console não dá conta,
    preservando o texto integral.
    """
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except UnicodeEncodeError:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is None:  # pragma: no cover - console sem buffer binário
            sys.stdout.write(text.encode("ascii", "replace").decode("ascii"))
            sys.stdout.flush()
            return
        buffer.write(text.encode("utf-8"))
        buffer.flush()


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

    root = project_root()

    files = changed_files(root)
    if not files:
        # Sem alterações, ou git indisponível: nada a verificar.
        return 0

    python_files = [f for f in files if f.endswith(PYTHON_SUFFIX)]
    if not python_files:
        # Alterações apenas em documentação ou configuração.
        return 0

    problems: list[str] = []
    skipped: list[str] = []

    # O alvo é a RAIZ, passada explicitamente. Nunca `.`, que seria o cwd.
    target = str(root)
    checks = (
        ("ruff format --check", ("uv", "run", "ruff", "format", "--check", target)),
        ("ruff check", ("uv", "run", "ruff", "check", target)),
    )

    for label, command in checks:
        result = run(command, CHECK_TIMEOUT_SECONDS, root)
        if result is None:
            skipped.append(label)
            continue
        code, output = result
        if code != 0:
            problems.append(f"[{label}]\n{summarize(output)}")

    if not problems and not skipped:
        return 0

    report: list[str] = ["", "── verify_before_stop (advisório) ──"]
    # A raiz analisada entra no relatório de propósito: é o que torna
    # verificável que o escopo não mudou por causa de um `cd`.
    report.append(f"raiz analisada: {root}")
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

    emit("\n".join(report) + "\n")

    # Advisório por decisão: sempre 0, nunca bloqueia o encerramento.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Falha aberto por contrato: este hook nunca bloqueia o encerramento.
        sys.exit(0)
