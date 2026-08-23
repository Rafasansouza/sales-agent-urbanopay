---
description: Regras do frontend web. A stack está pendente de ADR-011.
paths:
  - "apps/web/**"
---

# Regra — Frontend Web

**Documentos:** ADR-001, ADR-005, ADR-006, ADR-007, ADR-011 (Proposta).

## Estado atual — leia antes de qualquer coisa

**A stack do frontend não foi decidida.** `ADR-011` está com status
**Proposta**.

Enquanto esse ADR não for aceito:

- não instale nenhuma dependência JavaScript ou TypeScript;
- não crie scaffold, `package.json`, build ou configuração de framework;
- `apps/web/` contém apenas documentação.

Se receber uma tarefa que exija implementar frontend, **reporte a pendência**
(A-08 em `docs/OPEN-QUESTIONS.md`) em vez de escolher a stack.

## Invariantes que valerão qualquer que seja a stack

### Nenhuma regra de negócio no cliente

Fonte: ADR-005, ADR-006.

Tarifa, desconto, subtotal, total, elegibilidade de produto, perfil tarifário e
status de pagamento vêm **sempre** da API. O frontend exibe; não calcula, não
decide e não recalcula.

Um valor monetário recomputado no cliente é defeito, mesmo que coincida com o
do backend.

### Nenhum segredo no cliente

Fonte: ADR-007.

`MERCADOPAGO_ACCESS_TOKEN`, `ANTHROPIC_API_KEY`, `LANGFUSE_SECRET_KEY` e
qualquer credencial equivalente são exclusivamente backend. Nunca embuta
credencial em bundle, variável pública de build ou código de cliente.

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

- **A-08** — stack não decidida (ADR-011).
- **A-07** — interface administrativa de aprovação humana não especificada.
- **PRD §19** — nome comercial do agente e identidade visual pendentes. Não
  invente nome nem marca.
