"""Erros semânticos do domínio de pagamentos (SPEC-003 §16).

Puros: código estável + mensagem, sem HTTP e sem PII. Nenhuma mensagem
carrega valor monetário, identificador externo, token ou credencial.
"""

from __future__ import annotations

from typing import ClassVar


class PaymentsError(Exception):
    """Base dos erros de pagamento."""

    code: ClassVar[str]
    default_message: ClassVar[str]

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class PaymentNotFoundError(PaymentsError):
    """Payment inexistente (§16)."""

    code = "PAYMENT_NOT_FOUND"
    default_message = "Pagamento não encontrado."


class PaymentAlreadyApprovedError(PaymentsError):
    """Já existe pagamento aprovado para o Order (§16).

    Barreira contra cobrança duplicada: um Order tem no máximo um Payment
    `APPROVED`, garantido também por índice único parcial no banco.
    """

    code = "PAYMENT_ALREADY_APPROVED"
    default_message = "Este pedido já possui um pagamento aprovado."


class PaymentProviderError(PaymentsError):
    """Falha de comunicação ou resposta inválida do provider (§16).

    Não confundir com `PaymentCreationFailedError`: aqui o provider não
    estabeleceu desfecho algum.
    """

    code = "PAYMENT_PROVIDER_ERROR"
    default_message = "O provedor de pagamento está indisponível."


class PaymentCreationFailedError(PaymentsError):
    """O provider recusou a criação de forma determinística (§9, §16).

    Falha reproduzível: repetir a mesma requisição produz o mesmo resultado,
    e é por isso que o registro de idempotência vai para `FAILED` (§11.1).
    """

    code = "PAYMENT_CREATION_FAILED"
    default_message = "Não foi possível criar o pagamento."


class PaymentStatusUnknownError(PaymentsError):
    """Estado externo desconhecido (§9.1, §11.3).

    Levantado quando a criação sofreu timeout ou resposta inconclusiva, e
    também quando a mesma idempotency key é reapresentada enquanto o registro
    está `IN_PROGRESS`.

    Contrato de segurança financeira: **nenhum novo POST** é emitido por
    causa deste erro. A resolução é consulta ao provider com a mesma key. O
    tempo autoriza reconciliação, nunca cobrança.
    """

    code = "PAYMENT_STATUS_UNKNOWN"
    default_message = "O estado do pagamento ainda não foi confirmado pelo provedor."


class PaymentProviderTimeoutError(PaymentsError):
    """Timeout na chamada ao provider — estado desconhecido, nunca falha.

    Erro de fronteira: os adaptadores o levantam, e a camada de aplicação o
    traduz para `PaymentStatusUnknownError` mantendo `Payment CREATED`,
    `Order PAYMENT_PENDING` e `Idempotency IN_PROGRESS` (§9.1).
    """

    code = "PAYMENT_STATUS_UNKNOWN"
    default_message = "O provedor de pagamento não respondeu em tempo."
