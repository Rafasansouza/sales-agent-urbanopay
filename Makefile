# =============================================================================
# UrbanoPay Mobilidade — comandos de desenvolvimento
# =============================================================================
# Este Makefile é a definição canônica dos comandos e é usado pela CI.
# Em Windows, onde `make` normalmente não existe, use o wrapper equivalente:
#   .\scripts\dev.ps1 <alvo>
# =============================================================================

# O `compose.yaml` da raiz sobe o MVP inteiro — PostgreSQL, o job de migration
# e a API (ADR-016). O `.env` da raiz é a fonte canônica e é resolvido pelo
# próprio Compose, porque o arquivo agora vive ao lado dele.
COMPOSE := docker compose
UV      := uv

.DEFAULT_GOAL := help
.PHONY: help setup up down logs ps api fmt fmt-check lint typecheck \
        test test-unit test-integration test-e2e evals verify \
        migrate migration downgrade migration-check clean

help: ## Lista os alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- Ambiente ----------------------------------------------------------------

setup: ## Instala o ambiente Python a partir do uv.lock
	$(UV) sync

# --- Infraestrutura local ----------------------------------------------------

up: ## Sobe apenas o PostgreSQL (para rodar a suite a partir do host)
	$(COMPOSE) up -d --wait postgres

demo: ## Sobe o MVP inteiro em containers: banco, migration e API
	$(COMPOSE) up --build -d --wait
	@echo "chat  : http://localhost:8000/dev/chat"
	@echo "docs  : http://localhost:8000/docs"

build: ## Constroi a imagem da API
	$(COMPOSE) build

config: ## Valida o compose.yaml
	$(COMPOSE) config --quiet && echo "compose.yaml valido"

down: ## Derruba os containers preservando os volumes de dados
	$(COMPOSE) down

logs: ## Acompanha os logs da infraestrutura local
	$(COMPOSE) logs -f

ps: ## Mostra o estado dos containers
	$(COMPOSE) ps

# --- Aplicação ---------------------------------------------------------------

api: ## Executa a API em modo desenvolvimento
	$(UV) run uvicorn urbanopay.main:app --reload --host 127.0.0.1 --port 8000

# --- Qualidade ---------------------------------------------------------------

fmt: ## Formata o código
	$(UV) run ruff format .

fmt-check: ## Verifica a formatação sem alterar arquivos
	$(UV) run ruff format --check .

lint: ## Executa o linter
	$(UV) run ruff check .

typecheck: ## Executa a verificação de tipos
	$(UV) run mypy

# --- Testes ------------------------------------------------------------------
# As camadas seguem CLAUDE.md e AGENT-HARNESS §5.

test: test-unit ## Atalho para a suíte rápida (unit)

test-unit: ## Regras de domínio, sem I/O externo
	$(UV) run pytest -m unit

# H-07 fechada para todas as camadas: e2e e evals passaram a ter testes reais
# com a SPEC-004. A tolerância ao código 5 do pytest — que mascarava coleta
# vazia — foi removida. Zero testes coletados agora REPROVA em qualquer
# camada, que é exatamente a proteção que o item pedia.

test-integration: ## Fronteiras de banco e provider (requer `make up`)
	$(UV) run pytest -m integration

test-e2e: ## Jornada completa de compra (requer `make up`)
	$(UV) run pytest -m e2e

evals: ## Comportamento adversarial do agente (requer `make up`)
	$(UV) run pytest -m eval

# --- Verificação agregada ----------------------------------------------------

verify: fmt-check lint typecheck test-unit ## Suite rapida: formato, lint, tipos e unit

verify-all: verify test-integration test-e2e evals ## Suite completa (requer `make up`)
	@echo "verify-all: OK"
	@echo "verify: OK"

# --- Banco de dados ----------------------------------------------------------
# A URL vem das variáveis POSTGRES_* (ambiente ou .env local). Nenhum destes
# alvos conhece banco de produção — produção está fora do escopo do MVP.

migrate: ## Aplica migrations até head (requer `make up`)
	$(UV) run alembic upgrade head

migration: ## Gera migration candidata: make migration m="descricao"
	@test -n "$(m)" || { echo 'uso: make migration m="descricao da mudanca"'; exit 1; }
	$(UV) run alembic revision --autogenerate -m "$(m)"
	@echo "ATENCAO: autogenerate produz uma CANDIDATA. Revise antes de aceitar (ADR-012)."

downgrade: ## Reverte a última migration aplicada
	$(UV) run alembic downgrade -1

migration-check: ## Falha se os modelos divergirem das migrations
	$(UV) run alembic check

# --- Limpeza -----------------------------------------------------------------

clean: ## Remove caches de build e de ferramentas
	@rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	@find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
