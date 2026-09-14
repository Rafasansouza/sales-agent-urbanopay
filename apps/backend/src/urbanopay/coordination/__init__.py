"""Composição em processo entre módulos (A-19; ADR-001).

Esta camada existe para um problema específico e nomeado: `payments` precisa
disparar `fulfillment` depois de aprovar um pagamento, mas **`payments` não
pode importar `fulfillment`** — `fulfillment` já lê `payments` para validar
`Payment APPROVED` (SPEC-005 §11.1), e inverter a direção criaria ciclo.

A saída é pôr o coordenador **acima** dos dois: nenhum dos módulos conhece o
outro nessa direção, e a comunicação continua sendo em processo, exatamente o
que ADR-001 já prevê.

A-19 registrou explicitamente que composição em processo **não** é fronteira
arquitetural nova e não exige ADR próprio. Exigiria, e passaria a exigir, se
aqui entrasse fila, broker, worker, scheduler ou qualquer mecanismo assíncrono
persistente — nenhum dos quais existe nesta versão.
"""

from __future__ import annotations

from urbanopay.coordination.post_payment import PostPaymentCoordinator

__all__ = ["PostPaymentCoordinator"]
