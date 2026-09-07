"""Abstração de provider de pagamento.

Fonte: ADR-007.

A porta `PaymentProvider` vive em
`urbanopay.modules.payments.domain.ports` — o domínio declara o que precisa, e
este pacote reúne as implementações.

Estado atual:

- `FakePaymentProvider` (`fake.py`) — usado em desenvolvimento e em toda a
  suíte de testes. Nenhuma chamada de rede;
- `MercadoPagoPaymentProvider` — **não implementado**. Quando nascer: somente
  sandbox, credenciais por variável de ambiente, nenhum secret versionado, e
  a tradução do vocabulário do provider para `PaymentStatus` acontece no
  adaptador, nunca no domínio.

Regras permanentes: `amount` vem de `order.total`, derivado server-side; o
access token vive exclusivamente no backend e nunca é exposto ao frontend nem
ao LLM.
"""
