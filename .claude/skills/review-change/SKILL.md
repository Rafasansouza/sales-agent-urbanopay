---
name: review-change
description: Revisa uma mudança acionando os quatro revisores read-only — spec-guardian, architecture-reviewer, security-reviewer e test-reviewer — e consolida os pareceres. Use antes de considerar qualquer tarefa concluída.
---

# review-change

Etapa de revisão do fluxo de AGENT-HARNESS §13, materializando §8.

## Princípio

Os revisores são **somente leitura**. O agente principal implementa; os
revisores avaliam. Nunca coloque vários agentes editando o mesmo código.

Revisão por IA **não substitui** revisão humana do diff (AGENT-HARNESS §14).

## Procedimento

### 1. Delimitar o escopo

```bash
git status --short
git diff
```

Se o diff estiver vazio, não há o que revisar.

### 2. Acionar os quatro revisores

Acione-os em paralelo, cada um recebendo o escopo do diff e o domínio afetado:

| Revisor | Avalia |
|---|---|
| `spec-guardian` | conformidade com PRD, SPEC e ADR; regra sem requisito |
| `architecture-reviewer` | fronteiras, dependências, agente vs domínio, camada HTTP |
| `security-reviewer` | secrets, PII, autorização, idempotência, prompt injection |
| `test-reviewer` | camada correta, cenários críticos, testes enfraquecidos |

Passe a cada revisor: arquivos alterados, módulo afetado, SPEC e ADRs
aplicáveis, e o que a tarefa pretendia fazer.

### 3. Consolidar

```text
RESUMO DA MUDANÇA
<o que mudou e por quê>

PARECERES
spec-guardian ............ <veredito>
architecture-reviewer .... <veredito>
security-reviewer ........ <veredito>
test-reviewer ............ <veredito>

ACHADOS BLOQUEANTES
[GRAVE] <arquivo>:<linha> — <descrição> (fonte: <documento>)

ACHADOS NÃO BLOQUEANTES
[MÉDIO|BAIXO] ...

ACHADOS DIVERGENTES
<quando dois revisores discordam, apresente ambos; não escolha por conta própria>

DECISÃO
PRONTO PARA REVISÃO HUMANA | REQUER CORREÇÃO | BLOQUEADO POR PENDÊNCIA DOCUMENTAL
```

### 4. Tratar os achados

- **Achado bloqueante** — corrija antes de prosseguir. Todo achado de segurança
  que permita efeito financeiro indevido, vazamento de PII ou ação crítica não
  autorizada é bloqueante.
- **Achado de regra sem requisito** — não "conserte" implementando outra regra.
  Reporte a lacuna documental.
- **Achado que exige ADR** — pare e escreva o ADR com `new-adr`.
- **Achado não bloqueante** — registre explicitamente no relatório final. Não
  silencie.

### 5. Nunca faça

- Enfraquecer teste, asserção ou check para eliminar um achado.
- Descartar achado por parecer improvável.
- Declarar a mudança pronta com achado bloqueante em aberto.
- Fazer commit ou push automaticamente após a revisão.

## Ao terminar

Execute `verify` e entregue o diff para revisão humana.
