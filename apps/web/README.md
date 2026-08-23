# apps/web — Frontend

**Documentos:** ADR-001, ADR-011 (**Proposta**)
**Estado:** placeholder — aguardando decisão de stack

## Por que este diretório está vazio

ADR-001 estabelece `apps/web` como parte da estrutura do monorepo, mas
**nenhum documento aceito define a stack do frontend**.

CLAUDE.md determina que dependências majoritárias exijam ADR antes da
implementação. O `ADR-011` foi escrito e está com status **Proposta**.

O `.gitignore` do repositório já ignora `.next/` e `node_modules/`, o que
sugere Next.js — mas indício de configuração não é decisão arquitetural.

## Enquanto ADR-011 não for aceito

- Não instale nenhuma dependência JavaScript ou TypeScript.
- Não crie `package.json`, scaffold, build ou configuração de framework.
- A CI não possui job de frontend.
- O critério de aceite E2E do PRD §18 só pode ser demonstrado via API.

Se você receber uma tarefa que exija implementar frontend, **reporte a
pendência** em vez de escolher a stack.

## Alternativas em avaliação

Detalhadas em `docs/adr/ADR-011-web-frontend-stack.md`:

| Opção | Ganho | Custo |
|---|---|---|
| Next.js (App Router) + TypeScript | ecossistema maduro para streaming de UI | segunda camada de servidor; risco de regra de negócio migrar para o BFF |
| Vite + React + TypeScript | fronteira limpa: cliente puro da API | streaming exige mais trabalho manual |
| Templates server-side no FastAPI | menor superfície | experiência conversacional pobre |

## Invariantes que valerão qualquer que seja a escolha

Detalhadas em `.claude/rules/frontend/web.md`:

1. **Nenhuma regra de negócio no cliente.** Tarifa, desconto, total,
   elegibilidade, perfil e status vêm sempre da API (ADR-005).
2. **Nenhum segredo no cliente.** Access token do Mercado Pago, chave de LLM e
   secret do Langfuse são exclusivamente backend (ADR-007).
3. **Nenhuma PII desnecessária.** O frontend nunca recebe CPF completo, número
   completo de cartão ou valor de OTP. Cartão sempre mascarado (SPEC-002).
4. **Estado financeiro é do backend.** A UI nunca afirma pagamento concluído
   por ação do usuário; o status vem de `get_payment_status` (SPEC-003).
5. **Dinheiro é string decimal.** Nunca converter para número de ponto
   flutuante para exibir ou comparar (ADR-006).
6. **Sem polling agressivo** no acompanhamento de pagamento (ADR-007).

## Pendências relacionadas

- **A-08** — stack não decidida.
- **A-07** — interface administrativa de aprovação humana não especificada.
- **PRD §19** — nome comercial do agente e identidade visual pendentes. Não
  invente nome nem marca.
