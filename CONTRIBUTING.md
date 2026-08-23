# Contribuindo

Este repositório é governado por documentação versionada. Antes de escrever
código, leia `CLAUDE.md` e `docs/agent-harness/AGENT-HARNESS.md`.

## Hierarquia documental

```text
PRD → SPEC → ADR → Agent Harness → Implementação
```

Código não contradiz documento aceito. Em caso de divergência entre código,
PRD, SPEC e ADR, **reporte o conflito** antes de alterar comportamento.

Um ADR com status `Proposta` não autoriza implementação.

## Fluxo de desenvolvimento

```text
Issue/Task → Feature Branch → /prepare-task → Ler PRD/SPEC/ADR → Plano
→ Implementação → Testes → /review-change → /verify → Revisão humana do diff
→ Commit → Pull Request → CI → Merge humano
```

Nunca implemente diretamente em `main`.

## Branches

Uma branch por tarefa coerente, nomeada `<tipo>/<escopo-curto>`:

```text
feat/fare-engine
fix/payment-webhook-dedup
docs/adr-catalog
chore/bootstrap-project
```

## Commits

Conventional Commits, com **prefixo e escopo em inglês** e **descrição em
português**:

```text
feat(fare): implementar classificacao de viagem por segmentos
fix(payments): deduplicar webhook aprovado reprocessado
test(orders): cobrir transicao invalida de estado
docs(adr): registrar decisao de toolchain Python
chore(ci): adicionar job de typecheck
```

Tipos aceitos: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`,
`build`, `ci`.

Sem force push. Sem merge direto em `main`.

## Idioma

| Item | Idioma |
|---|---|
| Documentação (README, ADR, SPEC, comentários) | Português |
| Identificadores, nomes de módulo, tipos, funções | Inglês |
| Prefixo e escopo de commit | Inglês |
| Descrição de commit | Português |
| Mensagens de erro para o usuário final | Português |
| Códigos de erro (`error.code`) | Inglês, maiúsculas |

## Antes de abrir PR

```powershell
.\scripts\dev.ps1 verify
```

```bash
make verify
```

Depois:

1. Inspecione o diff completo.
2. Confirme conformidade com a SPEC e os ADRs aplicáveis.
3. Preencha o template de PR: What, Why, SPEC, ADR, Tests, Risks.
4. Reporte riscos e pendências abertas.

## Testes

| Camada | Alvo | Marcador |
|---|---|---|
| `tests/unit/` | Regra de domínio pura | `unit` |
| `tests/integration/` | Fronteira de banco e provider | `integration` |
| `tests/e2e/` | Jornada completa de compra | `e2e` |
| `tests/evals/` | Comportamento probabilístico do agente | `eval` |

- Mudança de comportamento exige teste.
- Correção de bug exige teste de regressão que falhe antes da correção.
- Marcador é obrigatório.
- **Nunca** delete, marque como skip ou enfraqueça um teste para fazer a CI
  passar.

## Dependências

Gerenciadas por `uv` (ADR-013):

```bash
uv add --package urbanopay <pacote>     # dependência de runtime da API
uv add --dev <pacote>                   # ferramenta de desenvolvimento
```

Commite o `uv.lock` na mesma mudança. Dependência estrutural exige ADR
**antes** da instalação.

## Quando um ADR é obrigatório

- Nova infraestrutura, provider ou dependência estrutural.
- Mudança de máquina de estados de domínio.
- Mudança de fronteira entre módulos.
- Mudança na fronteira entre IA probabilística e domínio determinístico.
- Alteração de política de segurança ou de idempotência.

Em dúvida se algo exige ADR: exige. Use a skill `new-adr`.

## Regras que não se negociam

- Nunca `float` para dinheiro. `Decimal` em Python, `NUMERIC` no PostgreSQL.
- Mensagem do usuário nunca prova pagamento.
- Somente o provider ou o backend estabelece `PaymentStatus.APPROVED`.
- Fulfillment só após pagamento aprovado e Order pago.
- Falha de fulfillment após pagamento nunca gera nova cobrança.
- Nenhum secret no código, em prompt ou em log.
- Nunca logar OTP, CPF completo ou número completo de cartão.
- Nenhuma regra de negócio determinística em prompt.
- Nenhuma tool genérica para o Sales Agent.
- Nunca invente regra de negócio para preencher lacuna documental: reporte a
  lacuna em `docs/OPEN-QUESTIONS.md`.

## O que não é delegado ao agente de IA

Fonte: AGENT-HARNESS §12.

Merge em `main`; force push; qualquer ação em produção; uso de credencial real;
pagamento real; alteração de política de segurança; remoção de teste para
passar a CI; mudança arquitetural silenciosa; mudança de regra sem documento;
migration destrutiva; desativação de autorização ou de idempotência.
