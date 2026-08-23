# ADR-013 — Toolchain Python, Gerenciamento de Dependências e Qualidade

**Status:** Aceito
**Data:** 2026-08-23

## Contexto

ADR-006 define FastAPI + Pydantic como camada HTTP e CLAUDE.md exige lint,
type check e testes antes de considerar qualquer tarefa concluída. Nenhum
documento aceito até aqui definia versão de Python, gerenciador de
dependências ou ferramentas de qualidade.

Sem essa decisão o bootstrap não consegue produzir um `pyproject.toml`, um
lockfile determinístico nem uma CI capaz de validar formato, lint, tipos e
testes — que são invariantes do harness (AGENT-HARNESS §15 e §16).

## Decisão

- **Python 3.13** como runtime único do backend.
- **uv** como gerenciador de dependências, ambiente virtual e executor de
  comandos.
- **`pyproject.toml` em PEP 621** como metadados de projeto.
- **`uv.lock` versionado** no repositório, garantindo instalação
  determinística em máquina de desenvolvimento e em CI.
- **Ruff** como formatador e linter.
- **mypy** como verificador de tipos.
- **pytest** como test runner, com marcadores separando as camadas
  `unit`, `integration`, `e2e` e `eval`.

## Estrutura adotada

O repositório usa um **workspace uv com raiz virtual**:

- a raiz contém `[tool.uv.workspace]`, a configuração compartilhada de Ruff,
  mypy e pytest e o grupo de dependências de desenvolvimento;
- `apps/api/pyproject.toml` é o pacote real do backend (`urbanopay`);
- `uv.lock` e `.venv` ficam na raiz, porque um workspace uv possui um único
  lockfile e um único ambiente resolvido.

Essa estrutura permite que Ruff e mypy cubram, com uma única configuração,
`apps/api/`, `tests/` e `.claude/hooks/`, e que `uv run pytest` seja executado
a partir da raiz — onde a suíte de testes vive, conforme ADR-001.

## Regras

- Toda dependência nova é adicionada via `uv add` e o `uv.lock` resultante é
  commitado na mesma mudança.
- CI instala exclusivamente a partir do `uv.lock` (`uv sync --frozen`).
- Nenhuma dependência de runtime é adicionada sem que exista SPEC ou ADR que
  a justifique. Dependência estrutural continua exigindo ADR próprio, conforme
  CLAUDE.md.
- Ruff e mypy são executados sobre backend, testes e hooks do harness.
- Marcadores de teste são obrigatórios: teste sem marcador é falha de lint de
  testes, não teste "genérico".
- `mypy` roda em modo estrito nos módulos de domínio. Código de infraestrutura
  pode ter exceções pontuais, sempre justificadas em comentário.

## Alternativas rejeitadas

| Alternativa | Motivo da rejeição |
|---|---|
| Poetry | Resolução e instalação mais lentas; sem ganho funcional relevante para este projeto. |
| pip + `requirements.txt` | Sem lockfile determinístico, contrariando a exigência de builds reproduzíveis em CI. |
| Black + isort + Flake8 | Três ferramentas para o que Ruff resolve em uma, com desempenho pior. |
| Python 3.12 | Escolhido 3.13 para maximizar a vida útil do projeto; ver risco registrado abaixo. |

## Consequências

Positivas: instalação rápida, lockfile determinístico, uma única configuração
de qualidade cobrindo todo o código Python do monorepo, e CI simples.

Negativas: uv é ferramenta relativamente recente e sua superfície de CLI ainda
evolui; a raiz virtual do workspace adiciona um `pyproject.toml` que não é
pacote, o que pode confundir quem espera um projeto Python plano.

## Risco registrado

A compatibilidade com Python 3.13 de `langgraph`, do driver PostgreSQL e do
SDK do Mercado Pago **não foi validada** neste bootstrap, porque nenhuma dessas
dependências é instalada nesta fase. A validação é pré-requisito das tarefas de
ADR-012 e SPEC-004, e está registrada em `docs/OPEN-QUESTIONS.md`.

Se alguma dependência estrutural não suportar 3.13, este ADR deve ser revisado
por meio de um novo ADR, e não alterado silenciosamente.

## Regra para Claude Code

Executar comandos Python sempre via `uv run`. Nunca invocar `pip install`
diretamente, nunca editar `uv.lock` à mão e nunca desabilitar regra de lint ou
de tipos para fazer a verificação passar.
