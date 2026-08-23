# Providers externos

**Documentos:** ADR-007 (pagamento), ADR-010 (LLM)
**Estado:** não implementado

## Princípio

Nenhum módulo de domínio conhece o SDK de um provider. O domínio depende de
uma porta tipada; este pacote implementa a porta.

Trocar de provider deve ser uma mudança local a este diretório.

> O modelo é uma dependência substituível; os contratos e regras do produto
> não são. — ADR-010

## `llm/` — ADR-010

Abstração `LLMProvider` / Model Router.

- Nodes **nunca** instanciam SDK de provider diretamente.
- Baseline: Claude Sonnet 5, configurável por `LLM_MODEL`.
- Contratos internos tipados: `IntentResult`, `TripExtractionResult`,
  `ConfirmationResult`, `ModelResponse`.
- Structured outputs passam por Pydantic **e** por validação de domínio.
  Schema válido não implica regra válida.
- `FakeLLMProvider` obrigatório para testes; nenhuma chamada real em CI.
- Fallback automático entre providers está fora do MVP.
- Outage do LLM não pode parar webhook, payment ou fulfillment já persistidos.
- PII enviada ao provider é minimizada. Nunca OTP, CPF completo, número
  completo de cartão, secret ou token.

## `payments/` — ADR-007

Abstração `PaymentProvider` e implementação `MercadoPagoPaymentProvider`.

- Somente credenciais de **teste**; access token exclusivamente no backend.
- `amount` vem de `order.total`, nunca do cliente.
- `X-Idempotency-Key` em toda criação.
- Retry da mesma tentativa reutiliza a key; nova tentativa após rejeição usa
  novo `payment_id` e nova key.
- Webhook é assíncrono, deduplicado e valida origem/assinatura quando
  aplicável.
- Timeout de criação é **estado desconhecido**, não falha definitiva.
- `FakePaymentProvider` obrigatório para testes locais e CI.

## Antes de implementar

Uma nova dependência de SDK é dependência estrutural: exige verificação de ADR
e registro no `uv.lock` na mesma mudança. A compatibilidade dos SDKs com
Python 3.13 ainda não foi validada — ver H-05 em `docs/OPEN-QUESTIONS.md`.
