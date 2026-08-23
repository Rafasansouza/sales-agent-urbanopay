# Regra — Fluxo Git

Fonte: CLAUDE.md, AGENT-HARNESS §12, §13, §14, §15, §16.

## Nunca na main

Nunca implemente diretamente em `main`. Use uma branch dedicada por tarefa
coerente.

Convenção de nome: `<tipo>/<escopo-curto>`, por exemplo:

```text
feat/fare-engine
fix/payment-webhook-dedup
chore/bootstrap-project
docs/adr-catalog
```

## Conventional Commits

Prefixo e escopo em **inglês**; descrição em **português**.

```text
feat(fare): implementar classificacao de viagem por segmentos
fix(payments): deduplicar webhook aprovado reprocessado
test(orders): cobrir transicao invalida de estado
docs(adr): registrar decisao de toolchain Python
chore(ci): adicionar job de typecheck
```

Tipos aceitos: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`,
`build`, `ci`.

## Proibições

- Nunca `git push --force`.
- Nunca `git reset --hard` sem instrução explícita do desenvolvedor.
- Nunca `git clean -fd` sem instrução explícita.
- Nunca fazer merge em `main`.
- Nunca commitar ou fazer push sem solicitação explícita, ou sem que o fluxo
  em andamento claramente o exija.

## Antes de considerar uma tarefa concluída

1. Inspecionar o diff completo.
2. Rodar os testes relevantes.
3. Rodar lint e type check.
4. Verificar conformidade com a SPEC e os ADRs aplicáveis.
5. Reportar riscos e pontos não resolvidos.

## Pull Request

O PR precisa explicar:

- **What** — o que mudou;
- **Why** — por que mudou;
- **SPEC** — qual especificação é atendida;
- **ADR** — quais decisões arquiteturais se aplicam;
- **Tests** — o que foi testado e em qual camada;
- **Risks** — o que pode dar errado e o que ficou fora.

Revisão por IA não substitui revisão humana.

## Branch protection esperada em main

PR obrigatório, status checks obrigatórios, sem push direto e sem force push.

## Não delegado ao agente

Fonte: AGENT-HARNESS §12.

Merge em `main`; force push; qualquer ação em produção; uso de credencial real;
pagamento real; alteração de política de segurança; remoção de teste para
passar a CI; mudança arquitetural silenciosa; mudança de regra de negócio sem
documento; migration destrutiva; desativação de autorização ou idempotência.
