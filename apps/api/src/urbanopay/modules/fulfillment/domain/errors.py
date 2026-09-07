"""Erros semânticos do domínio de fulfillment (SPEC-005 §11.3).

Puros: código estável + mensagem, sem HTTP e sem PII. Nenhuma mensagem carrega
valor monetário, identificador de cliente, saldo ou dado de cartão.

Os códigos foram aprovados e registrados em A-16/A-17: a SPEC-005 não trazia
seção de erros, ao contrário da SPEC-003 §16. `CARD_NOT_ACTIVE` é **reutilizado**
da SPEC-002 em vez de ganhar nome novo.
"""

from __future__ import annotations

from typing import ClassVar


class FulfillmentError(Exception):
    """Base dos erros de fulfillment."""

    code: ClassVar[str]
    default_message: ClassVar[str]

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class OrderNotPaidError(FulfillmentError):
    """Order não está `PAID` (SPEC-005 §5, §11.3).

    Barreira de entrada do fulfillment: sem pagamento aprovado não existe
    autorização para efeito comercial algum. Produz **zero efeito**.
    """

    code = "ORDER_NOT_PAID"
    default_message = "Este pedido ainda não está pago."


class FulfillmentNotFoundError(FulfillmentError):
    """Não existe fulfillment para o recurso consultado."""

    code = "FULFILLMENT_NOT_FOUND"
    default_message = "Não há entrega registrada para este pedido."


class EffectConflictError(FulfillmentError):
    """Efeito divergente já registrado para o mesmo Order (§8.1).

    Não é replay: replay devolve o resultado anterior. Aqui a evidência
    persistida contradiz o efeito que se tentaria aplicar, e nenhum efeito
    novo acontece.
    """

    code = "EFFECT_CONFLICT"
    default_message = "Já existe um efeito divergente registrado para este pedido."


class ReconciliationRequiredError(FulfillmentError):
    """Evidência inconsistente: exige análise humana (§11.1, §11.2, §12.1).

    Levantado depois de o fulfillment ter sido marcado
    `RECONCILIATION_REQUIRED` e o Order `FULFILLMENT_FAILED` — o estado fica
    **conhecido e auditável**, com zero efeito financeiro.

    ⚠️ A superfície administrativa que resolve o caso permanece aberta em
    A-18. É a situação em que o dinheiro entrou e a entrega é impossível.
    """

    code = "RECONCILIATION_REQUIRED"
    default_message = "Esta entrega exige verificação manual e não foi concluída."


class ReceiptNotAvailableError(FulfillmentError):
    """Comprovante consultado antes de `COMPLETED` (§13)."""

    code = "RECEIPT_NOT_AVAILABLE"
    default_message = "O comprovante estará disponível após a conclusão da entrega."


class UnsupportedFulfillmentTypeError(FulfillmentError):
    """Tipo fora do escopo implementável (§1.1, §9).

    `TICKET_ISSUANCE` depende do catálogo bloqueado por A-05. Recusa explícita
    é obrigatoriamente melhor que comportamento fictício para produto sem
    especificação.
    """

    code = "UNSUPPORTED_FULFILLMENT_TYPE"
    default_message = "Este tipo de entrega não está disponível."
