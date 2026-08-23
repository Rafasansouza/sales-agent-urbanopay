# Agent Harness — Claude Code

**Projeto:** UrbanoPay Mobilidade  
**Versão:** 1.0  
**Status:** Planejado / pré-implementação  
**Harness:** Claude Code

## 1. Objetivo
Governar o desenvolvimento assistido por IA com contexto versionado, regras, skills, subagents, hooks, permissions, testes e CI.

Hierarquia:

```text
PRD
↓
SPEC
↓
ADR
↓
Agent Harness
↓
Implementation
```

Código não contradiz documentos aceitos silenciosamente.

## 2. Source of Truth
O repositório é a fonte de verdade de engenharia. Decisões duráveis devem ser documentadas em PRD/SPEC/ADR/rules, não depender apenas de memória da sessão.

Sugestão inicial: `autoMemoryEnabled=false` no projeto.

## 3. Estrutura planejada

```text
CLAUDE.md
.claude/
├── settings.json
├── rules/
│   ├── architecture.md
│   ├── security.md
│   ├── testing.md
│   ├── database.md
│   ├── git-workflow.md
│   ├── backend/
│   │   ├── fare.md
│   │   ├── identity-cards.md
│   │   ├── orders-payments.md
│   │   ├── agent-runtime.md
│   │   └── fulfillment.md
│   └── frontend/web.md
├── agents/
│   ├── spec-guardian.md
│   ├── architecture-reviewer.md
│   ├── security-reviewer.md
│   └── test-reviewer.md
├── skills/
│   ├── prepare-task/SKILL.md
│   ├── implement-spec/SKILL.md
│   ├── review-change/SKILL.md
│   ├── new-adr/SKILL.md
│   └── verify/SKILL.md
└── hooks/
    ├── session_context.py
    ├── protect_operations.py
    └── verify_before_stop.py
```

## 4. CLAUDE.md
Deve ser conciso e conter objetivo do produto, hierarquia documental, stack, invariantes críticas, segurança, testes, Git workflow e regra para mudanças arquiteturais. Não importar todas as SPECs automaticamente; carregar apenas as relevantes para a tarefa.

## 5. Regras globais
### architecture.md
Monólito modular, dependências corretas, Agent != Domain, routers finos, services/use-cases, repositories/persistence.

### security.md
Sem secrets, PII, OTP tracing, cartão completo, SQL/HTTP arbitrário, bypass de authorization ou idempotência.

### testing.md
Mudança comportamental => teste; bug => regression test; domínio => unit; integração => integration; comportamento probabilístico => eval.

### database.md
PostgreSQL autoritativo, Decimal/NUMERIC, migration obrigatória, constraints, nenhuma mudança destrutiva sem review.

## 6. Rules path-specific
- Fare => SPEC-001 + ADR-004/005;
- Identity/Cards => SPEC-002 + ADR-004/005;
- Orders/Payments => SPEC-003 + ADR-005/007;
- Agent Runtime => SPEC-004 + ADR-002/003/005/010;
- Fulfillment => SPEC-005 + ADR-005/007.

## 7. Skills
### prepare-task
Ler requisito, identificar domínio, carregar documentos relevantes, analisar código/testes e produzir plano sem editar.

### implement-spec
Ler SPEC/ADRs, inspecionar implementação/testes, implementar mudança mínima, criar/atualizar testes e verificar.

### review-change
Rodar revisão por `spec-guardian`, `architecture-reviewer`, `security-reviewer`, `test-reviewer`.

### new-adr
Obrigatória antes de adicionar nova infraestrutura/provider/dependência estrutural, alterar state machine ou boundaries.

### verify
Executar format, lint, typecheck, unit, integration e evals relevantes.

## 8. Subagents
Preferencialmente reviewers read-only. Agente principal implementa; reviewers avaliam especificação, arquitetura, segurança e testes. Evitar swarm editando o mesmo código.

## 9. Permissions
`.claude/settings.json` versionado; `.claude/settings.local.json` gitignored.

Negar acesso automático a `.env`, private keys, credentials e secrets. Evitar `Bash(*)` global.

Bloquear/exigir humano para:
- `git push --force`;
- `git reset --hard`;
- `git clean -fd`;
- `rm -rf`;
- `docker compose down -v`;
- `DROP DATABASE`.

## 10. Hooks
### SessionStart
Adicionar contexto leve: branch, dirty status, commit recente e lembrar PRD->SPEC->ADR->implementation. Não despejar todos os docs.

### PreToolUse
`protect_operations.py` bloqueia edição na `main`, secrets, Git destrutivo e infraestrutura destrutiva.

### Stop
`verify_before_stop.py` roda checks rápidos quando houver alterações. Full suite continua em `/verify` e CI.

## 11. Enforcement
- CLAUDE.md/rules = orientação comportamental;
- permissions/hooks/CI = enforcement técnico.

## 12. Não delegado ao Claude
- merge em main;
- force push;
- produção;
- credenciais reais;
- pagamento real;
- mudar política de segurança;
- remover testes para passar CI;
- mudança arquitetural silenciosa;
- mudança de regra sem documento;
- migration destrutiva;
- desativar authorization/idempotency.

## 13. Fluxo de desenvolvimento

```text
Issue/Task
→ Feature Branch
→ /prepare-task
→ Read PRD/SPEC/ADR
→ Plan
→ Implementation
→ Tests
→ /review-change
→ /verify
→ Human Diff Review
→ Commit
→ Pull Request
→ CI
→ Human Merge
```

Nunca desenvolver diretamente em `main`.

## 14. Git
Conventional Commits. PR explica What, Why, SPEC, ADR, Tests e Risks. AI review não substitui human review.

## 15. CI
GitHub Actions deve validar format, lint, typecheck, tests e security checks. Branch protection em main: PR obrigatório, status checks, sem force/direct push.

## 16. Invariantes do Harness
- nenhum código funcional na main;
- nenhum secret lido/commitado;
- nenhuma mudança arquitetural silenciosa;
- regra de negócio exige requisito correspondente;
- behavioral change exige teste;
- schema change exige migration;
- CI não é contornado removendo checks;
- código gerado por IA passa por review.

## 17. Resultado esperado

```text
Developer
→ Claude Code
→ CLAUDE.md / rules / skills
→ SPEC / ADR
→ Code
→ Tests
→ Review Agents
→ Hooks
→ Git
→ CI
→ Human Review
→ Merge
```

Claude Code executa. A documentação direciona. Hooks e CI limitam. O humano mantém a responsabilidade final.
