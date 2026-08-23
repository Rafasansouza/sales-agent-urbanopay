# ADR-011 — Stack do Frontend Web

**Status:** Proposta
**Data:** 2026-08-23

> Este ADR **não está aceito**. Enquanto o status for `Proposta`, nenhuma
> dependência de frontend deve ser instalada e nenhum scaffold deve ser criado
> em `apps/web/`. Ver `docs/OPEN-QUESTIONS.md` (A-08).

## Contexto

ADR-001 estabelece `apps/web` como parte da estrutura inicial do monorepo e o
Agent Harness prevê uma regra específica em `.claude/rules/frontend/web.md`.
Entretanto, **nenhum documento aceito define a stack do frontend**.

O `.gitignore` do repositório já ignora `.next/` e `node_modules/`, o que
sugere Next.js, mas indício de configuração não é decisão arquitetural.

CLAUDE.md determina que dependências majoritárias exigem ADR antes da
implementação. Por isso o bootstrap criou apenas um `README.md` em `apps/web/`.

## Requisitos que a escolha precisa atender

Derivados do PRD e das SPECs já aceitas:

1. Interface conversacional com streaming de respostas do agente
   (PRD §5, §18; latência conversacional P95 ≤ 3 s em PRD §16).
2. Exibição de Pix sandbox, incluindo QR code e cópia de código
   (PRD §8, passos 17–18).
3. Acompanhamento de estado assíncrono: `PAYMENT_PENDING` → `PAID` →
   `FULFILLING` → `COMPLETED`, sem polling agressivo (ADR-007).
4. Nenhum segredo no cliente. `MERCADOPAGO_ACCESS_TOKEN` é exclusivamente
   backend (ADR-007).
5. Nenhuma regra de negócio no frontend. Tarifa, desconto, total e status vêm
   sempre da API (ADR-005).
6. Masking preservado: o frontend nunca recebe CPF completo, número completo
   de cartão nem OTP (SPEC-002 §6, §12).
7. Suporte à interface administrativa de aprovação humana — cujo escopo ainda
   é pendência aberta (PRD §19; ver A-07 em `docs/OPEN-QUESTIONS.md`).

## Alternativas em avaliação

### A. Next.js (App Router) + TypeScript
Ecossistema maduro para streaming de UI, roteamento e renderização no
servidor. Consistente com o `.gitignore` existente. Custo: introduz uma
segunda camada de servidor no monorepo, o que exige disciplina para não
migrar regra de negócio para o BFF, violando ADR-005 e ADR-006.

### B. SPA com Vite + React + TypeScript
Fronteira mais limpa: o frontend é estritamente cliente da API FastAPI, o que
reduz o risco de vazamento de regra de negócio para o servidor web. Custo:
sem renderização no servidor, exige mais trabalho manual em streaming.

### C. Templates server-side no FastAPI
Menor superfície e nenhuma dependência JS relevante. Custo: experiência
conversacional pobre; conflita com a expectativa de produto de portfólio do
PRD.

## Decisão

**Pendente.** Requer escolha explícita entre A, B e C.

## Consequências

Enquanto este ADR não for aceito:

- `apps/web/` contém apenas documentação;
- `.claude/rules/frontend/web.md` registra as invariantes já conhecidas, mas
  não define stack;
- a CI não possui job de frontend;
- o critério de aceite E2E do PRD §18 só pode ser demonstrado via API.
