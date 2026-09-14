---
description: Regras do frontend web (ADR-011, aceito). Next.js App Router + TypeScript.
paths:
  - "apps/frontend/**"
---

# Regra — Frontend Web

**Documentos:** ADR-001, ADR-005, ADR-006, ADR-007, ADR-011 (Aceito), ADR-015.

## Stack

**Next.js (App Router) + TypeScript**, decidido em ADR-011 e implementado em
`apps/frontend/`. A-08 está fechada.

## O BFF é um proxy burro

O servidor Next existe para **renderizar e transportar**.

```text
Browser → Next (route handler = proxy) → UrbanoPay API → Domain → PostgreSQL
```

`lib/proxy.ts` é o **único** ponto que fala com o backend, e ele nem lê o corpo
da resposta: repassa status e bytes como vieram.

Se você estiver escrevendo um `if` sobre status de pagamento dentro de um route
handler, a regra está no lugar errado. Nenhum enum de domínio é reimplementado
com semântica própria: `OrderStatus` e `PaymentStatus` chegam como string e
servem para **rotular**, nunca para decidir se algo pode acontecer.

## Invariantes

### Nenhuma regra de negócio no cliente

Fonte: ADR-005, ADR-006.

Tarifa, desconto, subtotal, total, elegibilidade de produto, perfil tarifário e
status de pagamento vêm **sempre** da API. O frontend exibe; não calcula, não
decide e não recalcula.

Um valor monetário recomputado no cliente é defeito, mesmo que coincida com o
do backend.

### Nenhum segredo no cliente

Fonte: ADR-007.

`MERCADOPAGO_ACCESS_TOKEN`, `OPENAI_API_KEY`, `LANGFUSE_SECRET_KEY` e qualquer
credencial equivalente são exclusivamente backend.

**Nada com prefixo `NEXT_PUBLIC_` carrega segredo** — tudo com esse prefixo vai
para o bundle, por construção. A CI verifica que nenhuma credencial vazou.

### Nenhuma PII desnecessária

Fonte: SPEC-002 §6, §12.

O frontend nunca recebe CPF completo, número completo de cartão nem valor de
OTP. Cartão é sempre exibido mascarado (`****4821`), a partir do
`masked_number` fornecido pela API.

### Estado financeiro é do backend

Fonte: SPEC-003 §2.

A interface nunca afirma que um pagamento foi concluído com base em ação do
usuário. O status vem de `get_payment_status`. Uma ação de "já paguei" na UI
pode, no máximo, disparar uma consulta.

Acompanhamento de `PAYMENT_PENDING → PAID → FULFILLING → COMPLETED` não usa
polling agressivo (ADR-007).

### Contratos da API

Fonte: ADR-006.

Valor monetário trafega como **string decimal** e deve ser tratado como tal.
Nunca converta para `number` de JavaScript para exibir ou comparar dinheiro.

Timestamps em ISO 8601. IDs são opacos: não derive significado deles.

Erros trazem `error.code` estável e `trace_id`. Trate pelo `code`, nunca pela
mensagem.

## Pendências que afetam o frontend

- **A-07** — interface administrativa de aprovação humana não especificada. A
  interface **exibe** que o pedido aguarda aprovação e para ali; não invente
  tela de decisão.
- **Streaming de tokens** — adiado com motivo em ADR-011. Se voltar à mesa,
  começa por um ADR sobre o contrato do provider, não pelo frontend.
- **PRD §19** — nome comercial do agente e identidade visual pendentes. Não
  invente nome nem marca.
