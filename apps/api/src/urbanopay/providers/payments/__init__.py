"""Abstração de provider de pagamento.

Fonte: ADR-007.

Estado: não implementado. A porta `PaymentProvider`, a implementação
`MercadoPagoPaymentProvider` e o `FakePaymentProvider` nascem com a
implementação da SPEC-003.

Regra permanente: `amount` vem de `order.total`, derivado server-side, e
somente credenciais de teste são aceitas.
"""
