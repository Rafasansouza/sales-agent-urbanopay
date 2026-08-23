---
name: prepare-task
description: Prepara uma tarefa antes de qualquer implementação — identifica o domínio, carrega PRD/SPEC/ADR relevantes, inspeciona código e testes existentes e produz um plano. Use no início de toda tarefa de desenvolvimento. Não edita nenhum arquivo.
---

# prepare-task

Primeira etapa do fluxo de desenvolvimento definido em AGENT-HARNESS §13.

## Regra absoluta desta skill

**Nenhum arquivo é criado, editado ou removido durante esta skill.** O produto
é um plano. Se você sentir necessidade de editar algo, o plano ainda não está
pronto.

## Procedimento

### 1. Entender o requisito

Reformule a tarefa em uma frase. Se não conseguir, a tarefa está ambígua:
liste as interpretações possíveis e pergunte antes de continuar.

### 2. Confirmar o contexto Git

```bash
git rev-parse --abbrev-ref HEAD
git status --short
```

Se estiver em `main`, pare. Nunca se implementa em `main`.
Se houver alterações não relacionadas pendentes, reporte antes de prosseguir.

### 3. Identificar o domínio

| Assunto | Módulo | SPEC | ADRs |
|---|---|---|---|
| Tarifa, trajeto, desconto | `fare` | SPEC-001 | 004, 005 |
| Cliente, OTP, sessão, cartão, saldo | `identity`, `cards` | SPEC-002 | 004, 005 |
| Quote, Order, aprovação, Payment | `orders`, `payments`, `approvals` | SPEC-003 | 005, 007 |
| Agente, grafo, tools, prompt | `agent` | SPEC-004 | 002, 003, 005, 010 |
| Recarga, ledger, ticket, comprovante | `fulfillment`, `tickets`, `postsale` | SPEC-005 | 005, 007 |
| Produto, catálogo | `catalog` | **nenhuma** | 004 |
| Frontend | `apps/web` | **nenhuma** | 001, 011 (Proposta) |

### 4. Carregar apenas o necessário

Leia a SPEC do domínio e os ADRs listados. **Não carregue todas as SPECs**;
contexto irrelevante degrada a qualidade da implementação (AGENT-HARNESS §4).

Leia sempre `docs/OPEN-QUESTIONS.md` e verifique se a tarefa atravessa alguma
pendência.

As regras de `.claude/rules/` referentes aos caminhos afetados são carregadas
automaticamente pelo harness.

### 5. Inspecionar o que já existe

- Código atual do módulo e de seus vizinhos.
- Testes existentes e a camada em que vivem.
- Erros tipados já definidos.
- Migrations já aplicadas, quando aplicável.

Reutilizar o que existe é preferível a criar estrutura paralela.

### 6. Detectar bloqueios antes de planejar

A tarefa está bloqueada se:

- exige regra de negócio que nenhum documento aceito define;
- depende de um item de `OPEN-QUESTIONS.md` não resolvido;
- exige ADR ainda com status `Proposta` — hoje ADR-011 e ADR-012;
- exige nova infraestrutura, provider ou dependência estrutural sem ADR;
- exige mudança de state machine ou de fronteira de domínio sem ADR.

Em qualquer desses casos: **reporte o bloqueio e pare**. Não preencha a lacuna.

### 7. Produzir o plano

```text
TAREFA
<uma frase>

BRANCH
<atual> — <ok | precisa criar branch>

DOMÍNIO E DOCUMENTOS
Módulo(s): ...
SPEC: ...  ADRs: ...
Pendências atravessadas: ...

ESTADO ATUAL
<o que já existe e será reaproveitado>

MUDANÇA PROPOSTA
1. ...
2. ...

TESTES
unit: ...
integration: ...
e2e: ...
eval: ...

INVARIANTES EM RISCO
<quais invariantes esta mudança pode quebrar e como serão protegidas>

MIGRATION
<necessária? destrutiva? precisa de revisão humana?>

FORA DE ESCOPO
<o que deliberadamente não será feito>

BLOQUEIOS
<vazio, ou a lista que impede a implementação>
```

## Saída

Apresente o plano e **aguarde**. A implementação é a skill `implement-spec`.
