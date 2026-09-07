# =============================================================================
# UrbanoPay Mobilidade — comandos de desenvolvimento
# =============================================================================
# Este Makefile é a definição canônica dos comandos e é usado pela CI.
# Em Windows, onde `make` normalmente não existe, use o wrapper equivalente:
#   .\scripts\dev.ps1 <alvo>
# =============================================================================

# `--env-file` é obrigatório: o docker compose resolve o `.env` a partir do
# diretório do ARQUIVO compose (`infra/`), não da raiz do repositório. Sem ele,
# a interpolação de POSTGRES_PASSWORD falha e nenhum ambiente novo sobe, mesmo
# com o `.env` presente na raiz — que é a fonte canônica (ver `.env.example`).
COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
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

up: ## Sobe PostgreSQL, Redis e OTel Collector (aguarda healthchecks)
	$(COMPOSE) up -d --wait

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

# As camadas e2e e evals ainda não possuem testes, porque as SPECs
# correspondentes não foram implementadas. O pytest retorna 5 quando nada é
# coletado, o que reprovaria a CI. Toleramos SOMENTE o código 5, e de forma
# ruidosa: qualquer outro código de saída continua reprovando.
#
# ATENÇÃO: esta tolerância deve ser removida assim que a camada correspondente
# tiver testes — como já foi feito para a integration. Ver H-07 em
# docs/OPEN-QUESTIONS.md.
define run_optional_layer
	@$(UV) run pytest -m $(1) || { code=$$?; \
		if [ $$code -eq 5 ]; then \
			echo "AVISO: nenhum teste coletado na camada '$(1)'."; \
			echo "AVISO: esperado nesta fase do bootstrap. Ver docs/OPEN-QUESTIONS.md (H-07)."; \
		else exit $$code; fi; }
endef

test-integration: ## Fronteiras de banco e provider (requer `make up`)
	$(UV) run pytest -m integration

test-e2e: ## Jornadas completas de compra (requer `make up`)
	$(call run_optional_layer,e2e)

evals: ## Comportamento probabilístico do agente
	$(call run_optional_layer,eval)

# --- Verificação agregada ----------------------------------------------------

verify: fmt-check lint typecheck test-unit ## Suíte usada por /verify e pela CI
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
