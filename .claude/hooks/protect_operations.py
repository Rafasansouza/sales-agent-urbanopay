#!/usr/bin/env python3
"""Hook PreToolUse — bloqueia operações proibidas pelo Agent Harness.

Conforme AGENT-HARNESS §9 e §10, este hook nega:

1. edição de arquivo enquanto a branch atual é protegida (`main`/`master`);
2. leitura ou escrita de secrets, chaves privadas e credenciais;
3. comandos Git destrutivos;
4. comandos de infraestrutura destrutivos.

E pede confirmação humana (`ask`) para:

5. modificação de PRD, SPEC ou ADR já existentes — porque CLAUDE.md determina
   que esses documentos não sejam alterados silenciosamente.

Contrato: falha aberto. Qualquer erro inesperado resulta em saída 0 sem
decisão, delegando o controle às `permissions` do `settings.json`. Este hook é
defesa em profundidade, não a única barreira.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import PurePosixPath

GIT_TIMEOUT_SECONDS = 5

PROTECTED_BRANCHES = frozenset({"main", "master"})

# Ferramentas que escrevem em arquivos.
WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})

# Ferramentas que leem arquivos.
READ_TOOLS = frozenset({"Read", "NotebookRead"})

# Arquivos que nunca devem ser lidos nem escritos pelo agente.
SECRET_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)\.env\.(?!example$)[^/]+$"),
    re.compile(r"\.pem$"),
    re.compile(r"\.key$"),
    re.compile(r"\.p12$"),
    re.compile(r"\.pfx$"),
    re.compile(r"(^|/)credentials\.[^/]+$"),
    re.compile(r"(^|/)secrets\.[^/]+$"),
    re.compile(r"(^|/)id_rsa"),
    re.compile(r"(^|/)id_ed25519"),
    re.compile(r"(^|/)\.npmrc$"),
    re.compile(r"(^|/)\.pypirc$"),
)

# Documentos de autoridade: alteração exige confirmação humana explícita.
AUTHORITY_DIR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)docs/prd/"),
    re.compile(r"(^|/)docs/specs/"),
    re.compile(r"(^|/)docs/adr/"),
)

# Comandos de shell proibidos. Cada entrada é (padrão, motivo).
FORBIDDEN_COMMANDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bgit\s+push\b[^\n;|&]*(--force\b|--force-with-lease\b|\s-f\b)"),
        "Force push é proibido (AGENT-HARNESS §9 e §12).",
    ),
    (
        re.compile(r"\bgit\s+reset\s+[^\n;|&]*--hard\b"),
        "`git reset --hard` descarta trabalho e exige decisão humana explícita.",
    ),
    (
        re.compile(r"\bgit\s+clean\b[^\n;|&]*-[a-zA-Z]*[fd]"),
        "`git clean -fd` remove arquivos não rastreados e exige decisão humana.",
    ),
    (
        re.compile(r"\bgit\s+push\b[^\n;|&]*\bmain\b"),
        "Push direto para `main` é proibido. Use branch e Pull Request.",
    ),
    (
        re.compile(r"\bgit\s+(checkout|switch)\s+[^\n;|&]*\s-B?\s*\bmain\b.*\s--force"),
        "Reescrever `main` é proibido.",
    ),
    (
        re.compile(
            r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*r[a-zA-Z]*f|"
            r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*f[a-zA-Z]*r"
        ),
        "`rm -rf` é proibido (AGENT-HARNESS §9).",
    ),
    (
        re.compile(
            r"\bRemove-Item\b[^\n;|&]*-Recurse[^\n;|&]*-Force|"
            r"\bRemove-Item\b[^\n;|&]*-Force[^\n;|&]*-Recurse"
        ),
        "Remoção recursiva forçada é proibida (equivalente a `rm -rf`).",
    ),
    (
        re.compile(r"\bdocker\s+compose\b[^\n;|&]*\bdown\b[^\n;|&]*(-v\b|--volumes\b)"),
        "`docker compose down -v` apaga os volumes de dados locais (AGENT-HARNESS §9).",
    ),
    (
        re.compile(r"\bdocker\s+volume\s+(rm|prune)\b"),
        "Remoção de volume Docker apaga dados locais e exige decisão humana.",
    ),
    (
        re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE),
        "`DROP DATABASE` é proibido (AGENT-HARNESS §9).",
    ),
    (
        re.compile(r"\bDROP\s+SCHEMA\b", re.IGNORECASE),
        "`DROP SCHEMA` é operação destrutiva e exige revisão humana.",
    ),
    (
        re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),
        "`TRUNCATE TABLE` é operação destrutiva e exige revisão humana.",
    ),
)

# Comandos que exigem confirmação humana, sem bloqueio definitivo.
ASK_COMMANDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bpip\s+install\b"),
        "ADR-013 determina uso de `uv`. Instalação direta via pip contorna o "
        "lockfile determinístico.",
    ),
    (
        re.compile(r"\b(npm|pnpm|yarn)\s+(install|add)\b"),
        "A stack de frontend não foi decidida: ADR-011 está com status "
        "Proposta. Nenhuma dependência JS deve ser instalada.",
    ),
)


def normalize(path: str) -> str:
    """Normaliza separadores para comparação estável entre Windows e POSIX."""
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def deny(reason: str) -> None:
    emit("deny", reason)


def ask(reason: str) -> None:
    emit("ask", reason)


def emit(decision: str, reason: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(payload))


def current_branch() -> str | None:
    try:
        result = subprocess.run(
            ("git", "rev-parse", "--abbrev-ref", "HEAD"),
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


def file_exists(path: str) -> bool:
    from pathlib import Path

    try:
        return Path(path).exists()
    except OSError:
        return False


def check_file_operation(tool_name: str, tool_input: dict) -> bool:
    """Avalia operações de arquivo. Devolve True se uma decisão foi emitida."""
    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not raw_path:
        return False

    path = normalize(str(raw_path))

    # 1. Secrets: nem leitura, nem escrita.
    for pattern in SECRET_FILE_PATTERNS:
        if pattern.search(path):
            deny(
                f"Acesso a `{path}` bloqueado: o arquivo corresponde a um padrão "
                "de secret, chave privada ou credencial. CLAUDE.md proíbe ler ou "
                "commitar secrets. Para saber quais variáveis existem, consulte "
                "`.env.example`."
            )
            return True

    if tool_name not in WRITE_TOOLS:
        return False

    # 2. Edição em branch protegida.
    branch = current_branch()
    if branch in PROTECTED_BRANCHES:
        deny(
            f"Edição bloqueada: a branch atual é `{branch}`. CLAUDE.md e "
            "AGENT-HARNESS §13 proíbem implementar diretamente em `main`. "
            "Crie uma branch dedicada para esta tarefa."
        )
        return True

    # 3. Documentos de autoridade já existentes.
    for pattern in AUTHORITY_DIR_PATTERNS:
        if pattern.search(path) and file_exists(str(raw_path)):
            ask(
                f"`{path}` é documento de autoridade (PRD/SPEC/ADR). CLAUDE.md "
                "determina que PRD, SPEC e ADR não sejam alterados "
                "silenciosamente. Confirme que esta alteração é intencional e "
                "aprovada. Criar um documento novo é permitido; alterar um "
                "existente exige decisão humana."
            )
            return True

    return False


def check_bash_command(tool_input: dict) -> bool:
    """Avalia comandos de shell. Devolve True se uma decisão foi emitida."""
    command = str(tool_input.get("command") or "")
    if not command:
        return False

    for pattern, reason in FORBIDDEN_COMMANDS:
        if pattern.search(command):
            deny(f"Comando bloqueado. {reason}")
            return True

    for pattern, reason in ASK_COMMANDS:
        if pattern.search(command):
            ask(f"Confirmação necessária. {reason}")
            return True

    return False


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError, json.JSONDecodeError):
        # Sem payload legível não há o que avaliar: falha aberto.
        return 0

    tool_name = str(data.get("tool_name") or "")
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    is_file_tool = tool_name in WRITE_TOOLS or tool_name in READ_TOOLS
    if is_file_tool and check_file_operation(tool_name, tool_input):
        return 0

    if tool_name in ("Bash", "PowerShell") and check_bash_command(tool_input):
        return 0

    # Nenhuma decisão: o fluxo normal de permissions decide.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Falha aberto por contrato: um hook com defeito nunca deve travar a
        # sessão. As `permissions` do settings.json continuam valendo como
        # barreira independente.
        sys.exit(0)
