<!--
Fonte: AGENT-HARNESS §14 — o PR explica What, Why, SPEC, ADR, Tests e Risks.
Revisão por IA não substitui revisão humana.
-->

## What

<!-- O que mudou, em uma ou duas frases. -->

## Why

<!-- Por que essa mudança é necessária. Qual problema ou requisito ela atende. -->

## SPEC

<!--
Qual especificação é atendida, com a seção. Ex.: SPEC-001 §6, SPEC-003 §11.

Se não existe SPEC para o comportamento implementado, isto é um problema:
explique por quê a mudança não precisa de requisito, ou abra a SPEC antes.
-->

## ADR

<!--
Quais decisões arquiteturais se aplicam. Ex.: ADR-005, ADR-007.

Esta mudança introduz nova infraestrutura, provider, dependência estrutural,
alteração de state machine ou de fronteira de domínio? Se sim, qual ADR a
autoriza? ADR com status `Proposta` não autoriza implementação.
-->

## Tests

<!--
O que foi testado e em qual camada.

- unit:
- integration:
- e2e:
- eval:

Correção de bug: qual teste de regressão falha sem a correção?
-->

## Risks

<!--
O que pode dar errado, o que ficou fora de escopo e quais pendências
permanecem abertas.
-->

---

## Checklist

- [ ] Não estou implementando diretamente em `main`
- [ ] Commits seguem Conventional Commits (prefixo e escopo em inglês, descrição em português)
- [ ] Inspecionei o diff completo
- [ ] `make verify` / `.\scripts\dev.ps1 verify` passa
- [ ] Mudança de comportamento possui teste
- [ ] Correção de bug possui teste de regressão
- [ ] Mudança de schema possui migration versionada
- [ ] Nenhum teste foi deletado, marcado como skip ou enfraquecido
- [ ] Nenhum secret, credencial ou PII foi adicionado ao código, a teste ou a log
- [ ] Nenhum valor monetário usa ponto flutuante
- [ ] Nenhuma regra de negócio determinística foi movida para prompt
- [ ] Nenhuma tool genérica foi exposta ao Sales Agent
- [ ] Nenhuma regra de negócio foi inventada para preencher lacuna documental
- [ ] `docs/OPEN-QUESTIONS.md` atualizado, se a mudança tocou alguma pendência
- [ ] Executei `/review-change`
