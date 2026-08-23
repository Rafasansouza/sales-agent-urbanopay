# Regra — Segurança

Fonte: PRD §13, ADR-005, ADR-008, ADR-009, SPEC-002 §12, AGENT-HARNESS §9.

## Proibições absolutas

- Nunca commitar secret, credencial, token ou chave privada.
- Nunca ler o conteúdo de `.env`, `*.pem`, `*.key`, `*.p12`, `*.pfx`,
  `credentials.*` ou `secrets.*`.
- Nunca expor credencial ao LLM, nem em prompt, nem em contexto, nem em tool
  result.
- Nunca logar valor de OTP.
- Nunca logar CPF completo nem número completo de cartão de transporte.
- Nunca contornar autorização, idempotência ou state machine para "fazer
  funcionar".
- Nunca dar ao Sales Agent capability genérica: SQL arbitrário, HTTP
  arbitrário, shell, acesso direto a Redis.

## Dados sensíveis

Considerados sensíveis por SPEC-002 §12: CPF, nome, e-mail, telefone, número
completo do cartão, saldo e histórico, e dados de pagamento.

Tratamento obrigatório:

- Minimização: envie ao LLM o mínimo necessário.
- Masking: cartão sempre no formato `****4821`.
- Tools operam com `card_id` e `masked_number`, nunca com o número completo.
- IDs internos e opacos em integrações e traces.
- Se a sanitização de telemetria falhar, **prefira não exportar** (ADR-008).

## Autorização

- Autenticação e autorização são sempre validadas server-side.
- Titularidade verificada explicitamente: `card.customer_id == session.customer_id`.
- Recurso de outro cliente responde `CARD_NOT_ACCESSIBLE` **sem revelar se o
  recurso existe**.
- Operação transacional exige sessão com `authenticated=true`.

## Hierarquia de confiança

Fonte: SPEC-002 §16.

```text
mensagem do usuário
  < contexto da IA
    < identidade da sessão
      < dados oficiais do cartão
        < regras determinísticas
```

Dado declarado é sempre inferior a dado verificado.

## Prompt injection

Fonte: SPEC-004 §12.

A defesa principal é **arquitetural**, não textual. Prompt é orientação, nunca
segurança.

Mesmo que o modelo seja completamente manipulado, a cadeia
`schema → service → authorization → state machine → constraints de banco`
deve impedir qualquer efeito inválido.

Cenários adversariais que precisam de teste: tentar alterar perfil tarifário,
saldo, desconto ou tarifa; forjar autenticação; acessar recurso de terceiro;
marcar pagamento como aprovado; ignorar aprovação humana; executar SQL.

## Superfície de API

- Rate limiting em endpoints sensíveis (autenticação, OTP, agente).
- Idempotência em toda operação crítica.
- Resposta de erro nunca revela stack trace, query, secret ou existência de
  recurso de terceiro.

## Credenciais de pagamento

Fonte: ADR-007.

- Somente credenciais de **teste**.
- Access token vive exclusivamente no backend.
- Nunca enviar credencial de pagamento ao frontend ou ao LLM.
