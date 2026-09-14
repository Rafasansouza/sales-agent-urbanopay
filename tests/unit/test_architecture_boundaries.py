"""Testes de arquitetura: fronteiras verificadas, não apenas escritas.

Fontes: ADR-001 (fronteiras de módulo, sem dependência circular), ADR-012
(o domínio não importa SQLAlchemy), ADR-014 (persistência conversacional é da
aplicação), ADR-015 (a SDK do provider não vaza) e ADR-017 (direção entre
pacotes).

A invariante central, e a que este arquivo existe para defender:

```text
database ◀── domains ◀── agent ◀── backend
```

Uma seta na direção errada não é questão de estilo: é o que transformaria um
monólito modular em dependência circular, e o que faria o custo de extrair um
serviço deixar de ser calculável.

Os detectores são testados contra código sintético, para provar que **reprovam
de verdade** quando o vazamento existe — um teste de fronteira que passa por
vacuidade é pior que nenhum.
"""

from __future__ import annotations

import ast
import io
import tokenize
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS = REPO_ROOT / "apps"

DATABASE = APPS / "database" / "src" / "urbanopay_database"
DOMAINS = APPS / "domains" / "src" / "urbanopay_domains"
AGENT = APPS / "agent" / "src" / "urbanopay_agent"
BACKEND = APPS / "backend" / "src" / "urbanopay"

# Cada pacote e **tudo** o que ele pode importar dos outros (ADR-017).
DIRECAO: dict[str, tuple[Path, frozenset[str]]] = {
    "urbanopay_database": (DATABASE, frozenset()),
    "urbanopay_domains": (DOMAINS, frozenset({"urbanopay_database"})),
    "urbanopay_agent": (AGENT, frozenset({"urbanopay_database", "urbanopay_domains"})),
    "urbanopay": (
        BACKEND,
        frozenset({"urbanopay_database", "urbanopay_domains", "urbanopay_agent"}),
    ),
}

INTERNOS = frozenset(DIRECAO)
PERSISTENCIA = frozenset({"sqlalchemy", "psycopg", "alembic"})
FRAMEWORKS_DO_AGENTE = frozenset({"langgraph", "langchain", "openai"})


def imported_roots(source: str) -> list[str]:
    """Pacotes raiz importados por um arquivo.

    Considera `import x`, `import x.y`, `from x import ...` e
    `from x.y import ...`. Import relativo (`from . import x`) nunca é externo
    e é ignorado.
    """
    tree = ast.parse(source)
    raizes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            raizes.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            raizes.append(node.module.split(".")[0])
    return raizes


def find_forbidden_imports(source: str, forbidden: frozenset[str]) -> list[str]:
    """Imports proibidos encontrados, pela raiz exata do pacote."""
    return [raiz for raiz in imported_roots(source) if raiz in forbidden]


def strip_prose(source: str) -> str:
    """Código sem comentários nem literais de string.

    O que se proíbe é o **uso**; a prosa que explica a proibição não é violação
    dela. Sem esta separação, um docstring dizendo "nunca use `create_all()`"
    reprovaria justamente o arquivo que o cumpre.
    """
    pedacos: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        pedacos.append(token.string)
    return " ".join(pedacos)


def _arquivos(raiz: Path) -> list[Path]:
    return sorted(p for p in raiz.rglob("*.py") if "__pycache__" not in p.parts)


# --- ADR-017: a direção entre pacotes ----------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("pacote", sorted(DIRECAO))
def test_pacote_respeita_a_direcao_de_dependencia(pacote: str) -> None:
    """Nenhum import aponta contra `database ← domains ← agent ← backend`."""
    raiz, permitidos = DIRECAO[pacote]
    proibidos = INTERNOS - permitidos - {pacote}

    offenders: dict[str, list[str]] = {}
    for path in _arquivos(raiz):
        found = find_forbidden_imports(path.read_text(encoding="utf-8"), proibidos)
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, (
        f"`{pacote}` importa contra a direção do ADR-017. "
        f"Pode importar {sorted(permitidos) or 'nada'}; encontrou: {offenders}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("pacote", sorted(DIRECAO))
def test_verificacao_de_pacote_nao_e_vacua(pacote: str) -> None:
    """Cada pacote tem código de verdade a varrer.

    Sem isto, apagar um pacote faria o teste acima passar por vacuidade em vez
    de por conformidade.
    """
    raiz, _ = DIRECAO[pacote]
    assert raiz.is_dir(), f"{raiz} deveria existir (ADR-017)"
    assert len(_arquivos(raiz)) >= 3


@pytest.mark.unit
def test_manifestos_declaram_a_mesma_direcao() -> None:
    """O que o código faz e o que o manifesto promete não podem divergir.

    É o manifesto que faz o `uv` recusar um ciclo. Se ele declarar menos do que
    o código importa, a instalação quebra; se declarar mais, a direção deixa de
    ser garantida pelo resolvedor.
    """
    for pacote, (_, permitidos) in DIRECAO.items():
        pasta = {"urbanopay": "backend"}.get(pacote, pacote.removeprefix("urbanopay_"))
        manifesto = tomllib.loads((APPS / pasta / "pyproject.toml").read_text(encoding="utf-8"))
        declaradas = {
            dep.split(">")[0].split("=")[0].split("[")[0].strip().replace("-", "_")
            for dep in manifesto["project"]["dependencies"]
        }
        internas = declaradas & INTERNOS
        assert internas <= permitidos, (
            f"`{pacote}` declara dependência interna fora da direção: "
            f"{sorted(internas - permitidos)}"
        )


# --- ADR-012: o domínio não conhece persistência -----------------------------


def _domain_files() -> list[Path]:
    return sorted(p for p in DOMAINS.glob("*/domain/**/*.py") if "__pycache__" not in p.parts)


@pytest.mark.unit
def test_dominio_nao_importa_persistencia() -> None:
    """Nenhum arquivo em `*/domain/` importa SQLAlchemy, psycopg ou Alembic."""
    offenders: dict[str, list[str]] = {}
    for path in _domain_files():
        found = find_forbidden_imports(path.read_text(encoding="utf-8"), PERSISTENCIA)
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, (
        f"Camada de domínio importando persistência (proibido por ADR-012): {offenders}"
    )


@pytest.mark.unit
def test_dominio_implementado_nao_e_vacuo() -> None:
    """Garante que a varredura acima realmente encontra arquivos."""
    dominios = {path.parents[1].name for path in _domain_files()}

    assert {"fare", "identity", "cards", "orders", "approvals", "payments"} <= dominios
    assert len(_domain_files()) > 20


@pytest.mark.unit
@pytest.mark.parametrize("modulo", ["persistence.py", "idempotency.py"])
def test_contrato_transversal_nao_importa_sqlalchemy(modulo: str) -> None:
    """Os contratos transversais não conhecem a implementação (ADR-012).

    Eles vivem em `urbanopay_database` — a camada mais baixa — porque domínios e
    agente precisam deles, e nenhum dos dois pode depender de quem está acima
    (ADR-017).
    """
    port = DATABASE / modulo
    assert port.is_file(), f"urbanopay_database/{modulo} deveria existir (ADR-012, ADR-017)"

    found = find_forbidden_imports(port.read_text(encoding="utf-8"), PERSISTENCIA)
    assert not found, f"{modulo} importa infraestrutura proibida: {found}"


# --- SPEC-004 §7.1: o agente não alcança persistência ------------------------


def _agent_files(*camadas: str) -> list[Path]:
    return sorted(
        p
        for camada in camadas
        for p in (AGENT / camada).rglob("*.py")
        if "__pycache__" not in p.parts
    )


@pytest.mark.unit
def test_agente_nao_importa_persistencia() -> None:
    """`domain` e `application` do agente não conhecem SQLAlchemy nem psycopg.

    O agente nunca executa SQL (ADR-001) e nunca vê uma `AsyncSession`: se
    precisasse, a fronteira que separa conversa de banco não existiria.
    """
    offenders: dict[str, list[str]] = {}
    for path in _agent_files("domain", "application"):
        found = find_forbidden_imports(path.read_text(encoding="utf-8"), PERSISTENCIA)
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, f"Camada conversacional importando persistência: {offenders}"


@pytest.mark.unit
def test_agente_nao_importa_infraestrutura_de_dominio() -> None:
    """O agente consome `application`/`domain` — nunca repositório ou model ORM."""
    offenders: dict[str, list[str]] = {}
    for path in _agent_files("domain", "application"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        alheios = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("urbanopay_domains.")
            and ".infrastructure" in node.module
        ]
        if alheios:
            offenders[str(path.relative_to(REPO_ROOT))] = alheios

    assert not offenders, f"Agente importando infraestrutura de domínio: {offenders}"


@pytest.mark.unit
def test_agente_nao_usa_async_session_fora_da_infraestrutura() -> None:
    """`AsyncSession` só aparece na camada que compõe a infraestrutura.

    A varredura ignora comentários e docstrings: o que se proíbe é o **uso**, e
    a prosa que explica a proibição não é violação dela.
    """
    offenders: dict[str, list[str]] = {}
    for path in _agent_files("domain", "application"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nomes = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "AsyncSession"]
        nomes += [
            n.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr == "AsyncSession"
        ]
        if nomes:
            offenders[str(path.relative_to(REPO_ROOT))] = nomes

    assert not offenders, f"AsyncSession fora da infraestrutura do agente: {offenders}"


@pytest.mark.unit
def test_verificacao_do_agente_nao_e_vacua() -> None:
    """Garante que os testes acima realmente varrem a implementação."""
    arquivos = _agent_files("domain", "application")
    assert len(arquivos) > 10
    assert (AGENT / "domain" / "catalog.py") in arquivos
    assert (AGENT / "application" / "executor.py") in arquivos


@pytest.mark.unit
def test_nenhum_dominio_conhece_o_agente() -> None:
    """ADR-001: dependência circular entre módulos é defeito.

    Os domínios existem sem a conversa — e precisam continuar existindo, ou o
    webhook e o fulfillment passariam a depender de um agente que pode estar
    indisponível (SPEC-005 §10).

    Hoje isto também é garantido pelo manifesto, mas a asserção permanece:
    manifesto declara intenção, e o import é o fato.
    """
    offenders: dict[str, list[str]] = {}
    for path in _arquivos(DOMAINS):
        found = find_forbidden_imports(
            path.read_text(encoding="utf-8"), frozenset({"urbanopay_agent"})
        )
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, f"Domínio importando o agente: {offenders}"


# --- ADR-014 e ADR-015: persistência conversacional e SDK --------------------

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

FORBIDDEN_IN_MIGRATIONS = ("checkpoint", "langgraph", "create_all")


@pytest.mark.unit
def test_agente_persiste_apenas_a_conversa() -> None:
    """ADR-014: o estado conversacional é da aplicação, e só ele é persistido.

    A lista de colunas é **fechada**: acrescentar uma sem revisar esta constante
    reprova. É essa fechadura que impede saldo, status, valor monetário e PII de
    entrarem no estado durável — não existe coluna onde caibam.
    """
    from urbanopay_agent.infrastructure.models import AgentConversationModel

    colunas = {c.name for c in AgentConversationModel.__table__.columns}
    assert colunas == ALLOWED_CONVERSATION_COLUMNS, (
        f"Colunas divergem do ADR-014. Sobrando: {colunas - ALLOWED_CONVERSATION_COLUMNS}. "
        f"Faltando: {ALLOWED_CONVERSATION_COLUMNS - colunas}."
    )

    tipos = {str(c.type).upper() for c in AgentConversationModel.__table__.columns}
    assert not any("NUMERIC" in t or "DECIMAL" in t or "FLOAT" in t for t in tipos), (
        f"Coluna monetária em agent_conversations: {tipos}"
    )
    assert not any("JSON" in t for t in tipos), f"JSONB em agent_conversations: {tipos}"


@pytest.mark.unit
def test_nenhuma_migration_cria_schema_de_framework() -> None:
    """Regra permanente do ADR-014: schema nunca nasce de runtime ou framework."""
    migrations = BACKEND / "migrations" / "versions"
    offenders = {
        path.name: termo
        for path in sorted(migrations.glob("*.py"))
        for termo in FORBIDDEN_IN_MIGRATIONS
        if termo in strip_prose(path.read_text(encoding="utf-8")).lower()
    }
    assert not offenders, f"Migration criando schema de framework: {offenders}"


@pytest.mark.unit
def test_frameworks_confinados_ao_pacote_do_agente() -> None:
    """ADR-014/ADR-015: trocar de orquestrador ou de provider não migra dados.

    `langgraph`, `langchain` e `openai` só existem dentro de `urbanopay_agent`.
    Se um deles alcançasse domínio ou backend, o custo de troca deixaria de ser
    "reescrever um adaptador".
    """
    offenders: dict[str, list[str]] = {}
    for raiz in (DATABASE, DOMAINS, BACKEND):
        for path in _arquivos(raiz):
            found = find_forbidden_imports(path.read_text(encoding="utf-8"), FRAMEWORKS_DO_AGENTE)
            if found:
                offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, f"Framework do agente fora do pacote do agente: {offenders}"


@pytest.mark.unit
def test_checkpointer_nativo_nao_foi_adotado() -> None:
    """ADR-014 rejeita checkpointer durável nativo do LangGraph.

    Varre as dependências **declaradas**, não o texto do arquivo: o comentário
    que documenta a proibição não é violação dela.
    """
    manifesto = tomllib.loads((APPS / "agent" / "pyproject.toml").read_text(encoding="utf-8"))
    declaradas = manifesto["project"]["dependencies"]

    assert not [d for d in declaradas if "langgraph-checkpoint-postgres" in d], declaradas
    # A asserção não é vácua: `langgraph` em si **está** declarado.
    assert [d for d in declaradas if d.startswith("langgraph")]

    grafo = (AGENT / "infrastructure" / "graph" / "graph.py").read_text(encoding="utf-8")
    assert "checkpointer=" not in grafo, "Grafo compilado com checkpointer (ADR-014 proíbe)"
    assert "builder.compile()" in grafo


@pytest.mark.unit
def test_webhook_de_pagamento_nao_mora_no_pacote_do_agente() -> None:
    """ADR-002: o webhook financeiro nunca passa pelo grafo.

    Agora isso é visível também na estrutura: ele vive em `urbanopay`, e não em
    `urbanopay_agent` (ADR-017).
    """
    assert (BACKEND / "api" / "v1" / "payments.py").is_file()

    # O agente **tem** uma tool de pagamento — `create_payment` e
    # `get_payment_status` são dele por SPEC-004 §7. O que ele não pode ter é o
    # caminho de **entrada** do provider: nada no pacote do agente processa
    # webhook nem estabelece status.
    proibidos = {"webhook", "process_webhook", "reconcile_payment"}
    offenders: dict[str, list[str]] = {}
    for path in _arquivos(AGENT):
        codigo = strip_prose(path.read_text(encoding="utf-8")).lower()
        achados = [termo for termo in proibidos if termo in codigo]
        if achados:
            offenders[str(path.relative_to(REPO_ROOT))] = achados

    assert not offenders, f"Caminho de webhook dentro do pacote do agente: {offenders}"


# --- os detectores reprovam de verdade ---------------------------------------


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
    """Prova que o detector reprova cada forma de import proibido."""
    assert find_forbidden_imports(snippet, PERSISTENCIA), f"O detector deixou passar: {snippet!r}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "snippet",
    [
        "from decimal import Decimal",
        "from urbanopay_database.persistence import UnitOfWork",
        "from . import errors",
        "import dataclasses",
        # Nome parecido não é o pacote proibido: a comparação é pela raiz exata.
        "import sqlalchemy_utils_fake",
    ],
)
def test_detector_nao_gera_falso_positivo(snippet: str) -> None:
    """Imports legítimos não são flagrados."""
    assert not find_forbidden_imports(snippet, PERSISTENCIA)


@pytest.mark.unit
def test_detector_de_direcao_flagra_seta_invertida() -> None:
    """Prova que a varredura de direção reprova um import contra a seta."""
    assert find_forbidden_imports(
        "from urbanopay.api.container import AppContainer", frozenset({"urbanopay"})
    )
    assert find_forbidden_imports("import urbanopay_agent", frozenset({"urbanopay_agent"}))


@pytest.mark.unit
def test_strip_prose_separa_uso_de_documentacao() -> None:
    """Prova que a varredura de migrations distingue código de comentário."""
    documentado = '"""Nunca use create_all()."""\nx = 1  # nem em comentario: create_all\n'
    usado = "metadata.create_all(engine)\n"

    assert "create_all" not in strip_prose(documentado)
    assert "create_all" in strip_prose(usado)
