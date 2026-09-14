"""Testes de arquitetura: fronteiras verificadas, não apenas escritas.

Fontes: ADR-001 (fronteiras de módulo, sem dependência circular), ADR-012 ("o
domínio não importa SQLAlchemy") e SPEC-004 §7.1 (o agente não alcança
persistência, e nenhum módulo de negócio conhece o agente).

Cobre cinco alvos:

1. `modules/*/domain/**` — nenhum arquivo pode importar `sqlalchemy`,
   `psycopg` ou `alembic`. Hoje existem seis domínios implementados (`fare`,
   `identity`, `cards`, `orders`, `approvals`, `payments`), então a asserção
   não é mais vácua.
2. `core/persistence.py` — o port do Unit of Work é a fronteira declarada e
   também não pode importar persistência.
3. `core/idempotency.py` — o contrato transversal de idempotência segue a
   mesma regra: os contratos ficam em `core`, a implementação SQLAlchemy em
   `db/idempotency.py`.
4. `modules/agent/{domain,application}` — a camada conversacional não toca
   `AsyncSession`, model ORM nem `infrastructure` de outro módulo. Somente
   `modules/agent/infrastructure/` conhece persistência.
5. **nenhum módulo de negócio importa `agent`** — o grafo de dependências
   permanece acíclico, e um domínio nunca depende da conversa.

O detector é testado contra arquivos sintéticos para provar que **falha de
verdade** quando o vazamento existir.
"""

from __future__ import annotations

import ast
import io
import tokenize
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "apps" / "backend" / "src" / "urbanopay"
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
def test_dominio_implementado_nao_e_vacuo() -> None:
    """Garante que o teste acima realmente varre arquivos.

    Sem esta verificação, apagar `modules/*/domain/` faria o teste de fronteira
    passar por vacuidade em vez de por conformidade.
    """
    dominios = {path.parents[1].name for path in _domain_files()}

    assert {"fare", "identity", "cards", "orders", "approvals", "payments"} <= dominios
    assert len(_domain_files()) > 20


@pytest.mark.unit
@pytest.mark.parametrize("modulo", ["persistence.py", "idempotency.py"])
def test_contrato_transversal_nao_importa_sqlalchemy(modulo: str) -> None:
    """Contratos de `core` não podem conhecer a implementação (ADR-012)."""
    port = SRC_ROOT / "core" / modulo
    assert port.is_file(), f"core/{modulo} deveria existir (ADR-012)"

    found = find_forbidden_imports(port.read_text(encoding="utf-8"), FORBIDDEN_IN_DOMAIN)
    assert not found, f"core/{modulo} importa infraestrutura proibida: {found}"


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


# --- SPEC-004 §7.1: o agente não alcança persistência ------------------------

AGENT_ROOT = MODULES_ROOT / "agent"

FORBIDDEN_IN_AGENT = FORBIDDEN_IN_DOMAIN

# Imports de outro módulo que a camada conversacional não pode fazer: ela
# consome `application` e `domain`, jamais `infrastructure` alheia.
_FOREIGN_INFRASTRUCTURE = "urbanopay.modules."


def _agent_files(*layers: str) -> list[Path]:
    return sorted(path for layer in layers for path in (AGENT_ROOT / layer).glob("**/*.py"))


def _foreign_infrastructure_imports(source: str) -> list[str]:
    """Imports de `modules/<outro>/infrastructure/...` feitos pelo agente."""
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules = [node.module]
        violations.extend(
            module
            for module in modules
            if module.startswith(_FOREIGN_INFRASTRUCTURE)
            and ".infrastructure" in module
            and not module.startswith("urbanopay.modules.agent.")
        )
    return violations


@pytest.mark.unit
def test_agente_nao_importa_persistencia() -> None:
    """`domain` e `application` do agente não conhecem SQLAlchemy nem psycopg.

    O agente nunca executa SQL (ADR-001) e nunca vê uma `AsyncSession`: se
    precisasse, a fronteira que separa conversa de banco não existiria.
    """
    offenders: dict[str, list[str]] = {}
    for path in _agent_files("domain", "application"):
        found = find_forbidden_imports(path.read_text(encoding="utf-8"), FORBIDDEN_IN_AGENT)
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, f"Camada conversacional importando persistência: {offenders}"


@pytest.mark.unit
def test_agente_nao_importa_infraestrutura_de_outro_modulo() -> None:
    """O agente consome `application`/`domain` — nunca repositório ou model ORM."""
    offenders: dict[str, list[str]] = {}
    for path in _agent_files("domain", "application"):
        found = _foreign_infrastructure_imports(path.read_text(encoding="utf-8"))
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, f"Agente importando infraestrutura alheia: {offenders}"


@pytest.mark.unit
def test_agente_nao_usa_async_session_fora_da_composicao() -> None:
    """`AsyncSession` só é referenciada no arquivo que compõe a infraestrutura.

    A varredura ignora comentários e docstrings — o que se proíbe é o **uso**,
    e a prosa que explica a proibição não é violação dela.
    """
    offenders: dict[str, list[str]] = {}
    for path in _agent_files("domain", "application"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "AsyncSession"
        ] + [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "AsyncSession"
        ]
        if names:
            offenders[str(path.relative_to(REPO_ROOT))] = names

    assert not offenders, f"AsyncSession fora da composição: {offenders}"


@pytest.mark.unit
def test_verificacao_do_agente_nao_e_vacua() -> None:
    """Garante que os testes acima realmente varrem a implementação."""
    files = _agent_files("domain", "application")
    assert len(files) > 10
    assert (AGENT_ROOT / "domain" / "catalog.py") in files
    assert (AGENT_ROOT / "application" / "executor.py") in files


@pytest.mark.unit
def test_nenhum_modulo_de_negocio_importa_o_agente() -> None:
    """ADR-001: dependência circular entre módulos é defeito.

    `fare`, `identity`, `cards`, `orders`, `approvals`, `payments` e
    `fulfillment` existem sem a conversa — e precisam continuar existindo, ou
    o webhook e o fulfillment passariam a depender de um agente que pode estar
    indisponível (SPEC-005 §10).
    """
    offenders: dict[str, list[str]] = {}
    for path in sorted(MODULES_ROOT.glob("*/**/*.py")):
        if path.is_relative_to(AGENT_ROOT):
            continue
        found = find_forbidden_imports(path.read_text(encoding="utf-8"), frozenset({"urbanopay"}))
        agent_imports = [name for name in found if name.startswith("urbanopay.modules.agent")]
        if agent_imports:
            offenders[str(path.relative_to(REPO_ROOT))] = agent_imports

    assert not offenders, f"Módulo de negócio importando o agente: {offenders}"


# Colunas que o ADR-014 autoriza em `agent_conversations`. A lista é fechada:
# acrescentar coluna sem revisar esta constante reprova o teste, que é
# exatamente a proteção pedida — sem coluna onde caibam, saldo, status, valor
# monetário e PII não têm caminho para o estado durável.
ALLOWED_CONVERSATION_COLUMNS = frozenset(
    {
        "id",
        "session_id",
        "phase",
        "selected_card_id",
        "current_quote_id",
        "current_order_id",
        "current_payment_id",
        "pending_confirmation_order_id",
        "pending_confirmation_presented_at",
        "version",
        "created_at",
        "updated_at",
        "expires_at",
    }
)

# Termos que nenhuma migration pode conter. `agent_conversations` saiu da lista
# ao ser decidido pelo ADR-014; checkpoint de framework permanece proibido,
# agora em caráter **permanente**.
FORBIDDEN_IN_MIGRATIONS = ("checkpoint", "langgraph", "create_all")


@pytest.mark.unit
def test_agente_persiste_apenas_a_conversa() -> None:
    """ADR-014: o estado conversacional é da aplicação, e só ele é persistido.

    Substitui a asserção de ausência que valia enquanto H-11 estava aberta. A
    proibição não sumiu — mudou de alvo: nenhuma tabela de framework, nenhum
    `create_all`, e a tabela da aplicação com **exatamente** o conjunto de
    colunas aprovado.
    """
    from urbanopay.modules.agent.infrastructure.models import AgentConversationModel

    columns = {column.name for column in AgentConversationModel.__table__.columns}
    assert columns == ALLOWED_CONVERSATION_COLUMNS, (
        "Colunas de agent_conversations divergem do ADR-014. "
        f"Sobrando: {columns - ALLOWED_CONVERSATION_COLUMNS}. "
        f"Faltando: {ALLOWED_CONVERSATION_COLUMNS - columns}."
    )

    # Nenhuma coluna monetária: a ausência é o controle que impede um valor de
    # apresentação virar, com o tempo, insumo de decisão (ADR-014).
    tipos = {str(column.type).upper() for column in AgentConversationModel.__table__.columns}
    assert not any("NUMERIC" in t or "DECIMAL" in t or "FLOAT" in t for t in tipos), (
        f"Coluna monetária em agent_conversations: {tipos}"
    )
    assert not any("JSON" in t for t in tipos), f"JSONB em agent_conversations: {tipos}"


def strip_prose(source: str) -> str:
    """Devolve o código sem comentários nem literais de string.

    O que se proíbe é o **uso**; a prosa que explica a proibição não é
    violação dela. Sem esta separação, um docstring dizendo "nenhum
    `create_all()`" reprovaria o arquivo que justamente o cumpre — mesma
    disciplina já adotada na varredura de `AsyncSession`.
    """
    pieces: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        pieces.append(token.string)
    return " ".join(pieces)


@pytest.mark.unit
def test_nenhuma_migration_cria_schema_de_framework() -> None:
    """Regra permanente do ADR-014: schema nunca nasce de runtime ou framework.

    A asserção é sobre o **código** das revisions, não sobre a lista delas: a
    cadeia cresce com as próximas SPECs, e a proibição não.
    """
    migrations = SRC_ROOT / "db" / "migrations" / "versions"
    offenders = {
        path.name: term
        for path in sorted(migrations.glob("*.py"))
        for term in FORBIDDEN_IN_MIGRATIONS
        if term in strip_prose(path.read_text(encoding="utf-8")).lower()
    }
    assert not offenders, f"Migration criando schema de framework: {offenders}"


@pytest.mark.unit
def test_strip_prose_separa_uso_de_documentacao() -> None:
    """Prova que a varredura acima distingue código de comentário.

    Sem este teste, `strip_prose` poderia remover tudo e o teste anterior
    passaria por vacuidade.
    """
    documentado = '"""Nunca use create_all()."""\nx = 1  # nem em comentario: create_all\n'
    usado = "metadata.create_all(engine)\n"

    assert "create_all" not in strip_prose(documentado)
    assert "create_all" in strip_prose(usado)


@pytest.mark.unit
def test_langgraph_confinado_ao_adaptador() -> None:
    """ADR-014: trocar de orquestrador não pode custar migração de dados.

    `langgraph`, `langchain` e `openai` são importáveis **apenas** nos
    adaptadores. Se um deles alcançasse `domain` ou `application`, a fronteira
    que torna o framework substituível deixaria de existir — e o custo de
    troca passaria de "reescrever um adaptador" para "migrar o produto".
    """
    frameworks = frozenset({"langgraph", "langchain", "openai"})
    permitidos = (
        SRC_ROOT / "modules" / "agent" / "infrastructure" / "graph",
        SRC_ROOT / "providers" / "llm",
    )

    offenders = {}
    for path in sorted(SRC_ROOT.glob("**/*.py")):
        if any(path.is_relative_to(allowed) for allowed in permitidos):
            continue
        found = find_forbidden_imports(path.read_text(encoding="utf-8"), frameworks)
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, f"Framework de orquestração ou SDK fora do adaptador: {offenders}"


@pytest.mark.unit
def test_checkpointer_nativo_nao_foi_adotado() -> None:
    """ADR-014 rejeita checkpointer durável nativo do LangGraph.

    Duas provas: a dependência não está declarada, e o grafo é compilado sem
    checkpointer. A segunda importa mais — instalar o pacote seria um acidente
    reversível; usá-lo transferiria o ownership do schema para o framework.
    """
    # Varre as dependências **declaradas**, não o texto do arquivo: o
    # comentário que documenta a proibição não é violação dela — mesma
    # disciplina de `strip_prose`.
    manifest = tomllib.loads(
        (REPO_ROOT / "apps" / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    )
    declaradas = [
        requisito
        for grupo in (
            manifest["project"].get("dependencies", []),
            *manifest["project"].get("optional-dependencies", {}).values(),
        )
        for requisito in grupo
    ]
    assert not [dep for dep in declaradas if "langgraph-checkpoint-postgres" in dep], declaradas
    # E a asserção não é vácua: `langgraph` em si **está** declarado.
    assert [dep for dep in declaradas if dep.startswith("langgraph")]

    grafo = (SRC_ROOT / "modules" / "agent" / "infrastructure" / "graph" / "graph.py").read_text(
        encoding="utf-8"
    )
    assert "checkpointer=" not in grafo, "Grafo compilado com checkpointer (ADR-014 proíbe)"
    assert "builder.compile()" in grafo


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
