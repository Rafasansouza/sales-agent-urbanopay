# =============================================================================
# Imagem da API — UrbanoPay Mobilidade
# =============================================================================
# Fonte: ADR-016 (empacotamento), ADR-013 (Python 3.13, uv como gerenciador).
#
# Regras que este arquivo materializa:
#
#   - dependências instaladas a partir do `uv.lock` versionado, com `--frozen`:
#     a mesma garantia de reprodutibilidade que a CI usa;
#   - **nenhum secret** entra aqui. Sem `ARG` de credencial, sem `COPY .env`,
#     sem chave em layer. A credencial chega por environment, em runtime;
#   - usuário não-root;
#   - nenhum volume com virtualenv do host: o ambiente vive na imagem.
#
# Build multi-stage: as camadas de dependência ficam separadas do código, de
# modo que alterar um arquivo `.py` não reinstale o mundo.
# =============================================================================

# --- Estágio 1: dependências -------------------------------------------------
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.29 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Primeiro só os manifestos: esta camada é reaproveitada enquanto as
# dependências não mudarem.
COPY pyproject.toml uv.lock ./
# O README acompanha o manifesto: `apps/api/pyproject.toml` o declara em
# `readme`, e o hatchling falha o build sem ele.
COPY apps/api/pyproject.toml apps/api/README.md apps/api/

# `--no-install-project` instala apenas as dependências; o pacote da aplicação
# entra no passo seguinte, junto com o código.
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/src apps/api/src
COPY alembic.ini ./

RUN uv sync --frozen --no-dev


# --- Estágio 2: runtime ------------------------------------------------------
FROM python:3.13-slim AS runtime

# `libpq5` é a única biblioteca de sistema necessária: psycopg 3 em modo
# binário já traz o resto.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system urbanopay \
    && useradd --system --gid urbanopay --create-home urbanopay

WORKDIR /app

COPY --from=builder --chown=urbanopay:urbanopay /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER urbanopay

EXPOSE 8000

# Liveness: prova que o processo responde. Deliberadamente sem dependência
# externa — banco fora do ar não pode ser lido como processo morto (ADR-016).
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD curl --fail --silent http://localhost:8000/health || exit 1

CMD ["uvicorn", "urbanopay.main:app", "--host", "0.0.0.0", "--port", "8000"]
