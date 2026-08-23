# Hooks do Agent Harness

Materialização de `docs/agent-harness/AGENT-HARNESS.md` §10.

Enforcement técnico do harness (§11) vem de três fontes independentes:
`permissions` no `settings.json`, estes hooks e a CI. As regras em
`.claude/rules/` e o `CLAUDE.md` são orientação comportamental.

## Hooks registrados

| Arquivo | Evento | Função | Bloqueia? |
|---|---|---|---|
| `session_context.py` | `SessionStart` | Injeta branch, estado da árvore, último commit e a hierarquia documental | Não |
| `protect_operations.py` | `PreToolUse` | Nega secrets, edição em `main`, Git e infraestrutura destrutivos | Sim |
| `verify_before_stop.py` | `Stop` | Roda checks rápidos quando há `.py` alterado | Não (advisório) |

## Contrato comum: falha aberto

Todos os hooks capturam exceções e saem com código 0. Um hook com defeito
**nunca** deve travar a sessão.

Isso é deliberado: os hooks são defesa em profundidade, e não a única barreira.
As `permissions` do `settings.json` continuam valendo de forma independente, e
a CI valida o resultado final.

## O que `protect_operations.py` nega

**Secrets** — leitura ou escrita de `.env`, `.env.*` (exceto `.env.example`),
`*.pem`, `*.key`, `*.p12`, `*.pfx`, `credentials.*`, `secrets.*`, `id_rsa*`,
`id_ed25519*`, `.npmrc`, `.pypirc`.

**Edição em branch protegida** — qualquer escrita de arquivo quando a branch
atual é `main` ou `master`.

**Git destrutivo** — `push --force`, `push --force-with-lease`, `push -f`,
`reset --hard`, `clean -fd`, push direto para `main`.

**Infraestrutura destrutiva** — `rm -rf`, `Remove-Item -Recurse -Force`,
`docker compose down -v`, `docker volume rm|prune`, `DROP DATABASE`,
`DROP SCHEMA`, `TRUNCATE TABLE`.

## O que `protect_operations.py` pede confirmação (`ask`)

**Documentos de autoridade** — alteração de arquivo **já existente** em
`docs/prd/`, `docs/specs/` ou `docs/adr/`. Criar documento novo é permitido;
alterar um existente exige decisão humana, porque CLAUDE.md determina que PRD,
SPEC e ADR não sejam alterados silenciosamente.

**Instalação de dependência fora do processo** — `pip install` (ADR-013
determina `uv`) e `npm|pnpm|yarn install|add` (ADR-011 está com status
`Proposta`, logo nenhuma dependência de frontend deve ser instalada).

## Portabilidade

Os hooks usam **apenas a biblioteca padrão** do Python e são invocados como
`python .claude/hooks/<arquivo>.py`, com o diretório do projeto como diretório
de trabalho.

Pontos conhecidos, registrados em `docs/OPEN-QUESTIONS.md` (H-02):

- em Linux e macOS, o executável pode se chamar `python3`. Se os hooks não
  dispararem nesses ambientes, ajuste o comando em `.claude/settings.json`;
- o comportamento dos hooks em CI Linux ainda não foi validado.

## Testar manualmente

```powershell
# SessionStart
'{}' | python .claude/hooks/session_context.py

# PreToolUse — deve negar
'{"tool_name":"Read","tool_input":{"file_path":".env"}}' | python .claude/hooks/protect_operations.py

# PreToolUse — deve negar
'{"tool_name":"Bash","tool_input":{"command":"git push --force"}}' | python .claude/hooks/protect_operations.py

# PreToolUse — deve permitir (sem saída)
'{"tool_name":"Bash","tool_input":{"command":"git status"}}' | python .claude/hooks/protect_operations.py

# Stop
'{}' | python .claude/hooks/verify_before_stop.py
```

## Ao alterar um hook

1. Mantenha o contrato de falha aberto.
2. Nunca faça o hook ler conteúdo de secret, nem para "validar".
3. Nunca adicione acesso à rede.
4. Mantenha a execução rápida: estes hooks estão no caminho crítico da sessão.
5. Teste manualmente os casos de negar, de confirmar e de permitir.
6. Atualize esta documentação na mesma mudança.
