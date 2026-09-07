---
name: verify
description: Executa a verificação completa do repositório — formatação, lint, type check, testes unitários, de integração, e2e e evals relevantes. Use antes de entregar qualquer mudança para revisão humana.
---

# verify

Materializa AGENT-HARNESS §7 e o checklist de conclusão de CLAUDE.md.

## Regra absoluta

Se um check falha, **corrija o código**. Nunca:

- desabilite regra de lint para silenciar um erro;
- adicione `# type: ignore` sem justificativa em comentário;
- marque teste como skip ou xfail para fazer a suíte passar;
- afrouxe asserção;
- remova check da CI.

## Ordem de execução

Execute em ordem e **pare no primeiro erro** — verificar tipos com o código
malformatado só produz ruído.

### Suíte rápida

```powershell
.\scripts\dev.ps1 fmt-check
.\scripts\dev.ps1 lint
.\scripts\dev.ps1 typecheck
.\scripts\dev.ps1 test-unit
```

Equivalente agregado:

```powershell
.\scripts\dev.ps1 verify
```

Em ambiente com `make`: `make verify`.

### Suíte completa

Requer infraestrutura local no ar:

```powershell
.\scripts\dev.ps1 up
.\scripts\dev.ps1 test-integration
.\scripts\dev.ps1 test-e2e
```

### Evals

Somente quando a mudança afeta comportamento do agente — prompt, tools, grafo,
provider ou modelo:

```powershell
.\scripts\dev.ps1 evals
```

Troca de modelo de LLM **exige** execução da suíte de regressão completa
(ADR-010).

## Escopo por tipo de mudança

| Mudança | Verificação mínima |
|---|---|
| Regra de domínio | suíte rápida |
| Repositório, migration, provider | suíte rápida + integration |
| Endpoint HTTP | suíte rápida + integration |
| Jornada de compra | suíte rápida + integration + e2e |
| Prompt, tool, grafo, modelo | suíte rápida + evals |
| Documentação apenas | fmt-check + lint |

## Estado atual do repositório

Nesta fase do bootstrap:

- `test-integration`, `test-e2e` e `evals` **não coletam nenhum teste**, porque
  as SPEC-001 a SPEC-005 ainda não foram implementadas. Zero testes coletados
  nessas camadas é o resultado esperado, não uma falha.
- Esses alvos toleram **exclusivamente** o código de saída 5 do pytest
  ("nenhum teste coletado") e emitem aviso. Qualquer outro código reprova. A
  tolerância deve ser removida quando a camada tiver testes — ver H-07 em
  `docs/OPEN-QUESTIONS.md`.
- `migrate` falha deliberadamente: ADR-012 está **Aceito** (Alembic é a
  ferramenta decidida), mas a persistência ainda não foi implementada — o
  Alembic não foi instalado e nenhuma migration foi materializada.

## Depois de verificar

1. Inspecione o diff: `git diff`.
2. Confirme conformidade com a SPEC e os ADRs aplicáveis.
3. Reporte:

```text
VERIFICAÇÃO
fmt-check ......... OK | FALHA
lint .............. OK | FALHA
typecheck ......... OK | FALHA
test-unit ......... N passaram, M falharam
test-integration .. N passaram | não executado (motivo)
test-e2e .......... N passaram | não executado (motivo)
evals ............. N casos | não executado (motivo)

RISCOS REMANESCENTES
- ...

PENDÊNCIAS NÃO RESOLVIDAS
- ...
```

Não faça commit nem push sem solicitação explícita.
