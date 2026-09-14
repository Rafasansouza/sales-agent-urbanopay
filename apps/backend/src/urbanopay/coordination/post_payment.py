"""Seam pós-pagamento: quem invoca `fulfill_order` (SPEC-005 §10.1, A-19).

A política que este módulo implementa, literalmente:

> Todo caminho de backend que faça o estado convergir para `Payment APPROVED`
> ⇒ `Order PAID` deve, **depois do commit financeiro**, entregar o `order_id` a
> uma camada de composição `BACKEND_ONLY`, responsável por chamar
> `fulfill_order(order_id)`.

Quatro restrições que o desenho preserva:

- **o Sales Agent não chega aqui.** `fulfill_order` é `BACKEND_ONLY` e não é
  tool em nível algum (SPEC-004 §7.4). Nenhuma fala do cliente aciona entrega;
- **`payments` não importa `fulfillment`.** O coordenador vive acima dos dois;
- **o disparo acontece depois do commit**, nunca dentro da transação que aprova
  o pagamento: entrega e cobrança são eventos distintos;
- **não é retentativa automática.** Falha de entrega não repete cobrança, não
  troca cartão e não estorna. O caso vai para `RECONCILIATION_REQUIRED`, e a
  resolução administrativa permanece aberta em A-18.

O mesmo seam serve webhook e reconciliação — os dois caminhos que aplicam
`APPROVED` — para que não existam duas regras sobre quando entregar.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from urbanopay_domains.payments.domain.enums import PaymentStatus

if TYPE_CHECKING:
    import uuid

    from urbanopay_domains.fulfillment.application.services import FulfillmentService
    from urbanopay_domains.fulfillment.domain.results import FulfillmentResult

logger = logging.getLogger(__name__)


class PostPaymentCoordinator:
    """Chama `fulfill_order` após um pagamento aprovado."""

    def __init__(self, fulfillment: FulfillmentService) -> None:
        self._fulfillment = fulfillment

    async def on_payment_settled(
        self, *, order_id: uuid.UUID, payment_status: PaymentStatus
    ) -> FulfillmentResult | None:
        """Entrega, se e somente se o pagamento foi aprovado.

        O gatilho é `Payment APPROVED`, e não uma leitura do Order, porque
        `Payment APPROVED ⇒ Order PAID` é aplicado pelo `PaymentService` na
        **mesma transação** (SPEC-003 §12): consultar o Order aqui seria
        perguntar de novo algo que já foi decidido e comitado.

        Qualquer outro desfecho é legítimo e não entrega nada — `REJECTED`,
        `EXPIRED` e `CANCELLED` devolvem o Order a `CONFIRMED` (§13.2), e
        `CREATED`/`PENDING` ainda não concluíram.

        Devolve `None` quando não houve entrega, para que o chamador distinga
        "não se aplicava" de "entregou".
        """
        if payment_status is not PaymentStatus.APPROVED:
            return None
        return await self.fulfill(order_id=order_id)

    async def fulfill(self, *, order_id: uuid.UUID) -> FulfillmentResult | None:
        """Executa a entrega, sem deixar a falha derrubar o caminho financeiro.

        O pagamento **já está aprovado e comitado** quando chegamos aqui.
        Propagar uma exceção de entrega faria o chamador — webhook ou
        reconciliação — parecer ter falhado, e um provider que recebe erro
        reenvia o evento. Um Order pago que não entregou é caso de
        reconciliação, não de retentativa de cobrança.

        O caso não se perde: a capacidade de recuperação de SPEC-005 §20.1
        localiza `Order PAID` sem `Fulfillment COMPLETED`, e a reentrada
        continua sendo por comando explícito de backend (§5.1).
        """
        try:
            result = await self._fulfillment.fulfill_order(order_id=order_id)
        except Exception:
            # Log sem argumento cru e sem stack trace na resposta: o
            # identificador do Order é opaco e já é o suficiente para
            # reconciliar.
            logger.exception("fulfillment pos-pagamento falhou", extra={"order_id": str(order_id)})
            return None

        logger.info(
            "fulfillment pos-pagamento concluido",
            extra={
                "order_id": str(order_id),
                "fulfillment_status": result.fulfillment.status.value,
                # `replayed` distingue "entregou agora" de "já estava entregue".
                # Sem ele, um reprocessamento pareceria um segundo crédito.
                "replayed": result.replayed,
            },
        )
        return result
