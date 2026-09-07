"""Erros semânticos do domínio de Orders (SPEC-003 §16).

Puros: código estável + mensagem, sem HTTP e sem PII. Nenhuma mensagem carrega
valor monetário, identificador de cliente ou dado de cartão.

Sobre `*_NOT_FOUND` versus `*_NOT_ACCESSIBLE`: a SPEC-003 §16 define os dois
códigos, e a regra de segurança proíbe revelar a existência de recurso de
outro cliente. A conciliação adotada é:

- consulta **feita pelo cliente** usa sempre `*_NOT_ACCESSIBLE`, com a mesma
  mensagem para "não existe" e "é de outro cliente" — anti-enumeração, igual
  ao `CARD_NOT_ACCESSIBLE` da SPEC-002;
- `*_NOT_FOUND` fica reservado a consultas cujo ator **não** é o cliente
  (superfície administrativa de aprovação), onde não há o que enumerar.
"""

from __future__ import annotations

from typing import ClassVar


class OrdersError(Exception):
    """Base dos erros de Orders."""

    code: ClassVar[str]
    default_message: ClassVar[str]

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


# --- Quote ---------------------------------------------------------------


class QuoteNotFoundError(OrdersError):
    """Quote inexistente, em consulta não feita pelo cliente."""

    code = "QUOTE_NOT_FOUND"
    default_message = "Orçamento não encontrado."


class QuoteNotAccessibleError(OrdersError):
    """Quote inexistente OU de outro cliente (SPEC-003 §4). Anti-enumeração."""

    code = "QUOTE_NOT_ACCESSIBLE"
    default_message = "Orçamento não acessível para este cliente."


class QuoteExpiredError(OrdersError):
    """Quote fora da validade derivada de `expires_at` (SPEC-003 §4)."""

    code = "QUOTE_EXPIRED"
    default_message = "Orçamento expirado. Gere um novo orçamento."


class QuoteAlreadyConsumedError(OrdersError):
    """Já existe Order referenciando esta Quote (SPEC-003 §4).

    Reutiliza o código documentado `INVALID_ORDER_STATE` em vez de introduzir
    um código novo. A Quote é snapshot de **uma** compra: permitir dois Orders
    sobre a mesma Quote criaria dois pedidos pagáveis a partir de um único
    consentimento de valor. A garantia final é a unicidade de `orders.quote_id`
    no banco; esta verificação apenas produz erro semântico antes disso.

    ⚠️ A §4 descreve o consumo da Quote mas não nomeia o erro da segunda
    tentativa — lacuna documental registrada, resolvida aqui pelo lado
    conservador.
    """

    code = "INVALID_ORDER_STATE"
    default_message = "Este orçamento já foi utilizado em um pedido."


# --- Order ---------------------------------------------------------------


class OrderNotFoundError(OrdersError):
    """Order inexistente, em consulta não feita pelo cliente."""

    code = "ORDER_NOT_FOUND"
    default_message = "Pedido não encontrado."


class OrderNotAccessibleError(OrdersError):
    """Order inexistente OU de outro cliente. Anti-enumeração."""

    code = "ORDER_NOT_ACCESSIBLE"
    default_message = "Pedido não acessível para este cliente."


class OrderAlreadyPaidError(OrdersError):
    """Order já pago (SPEC-003 §14): `PAID` é terminal, sem reversão."""

    code = "ORDER_ALREADY_PAID"
    default_message = "Este pedido já foi pago."


class OrderExpiredError(OrdersError):
    """`DRAFT` expirado não é confirmável (SPEC-003 §5.1)."""

    code = "ORDER_EXPIRED"
    default_message = "Pedido expirado. Gere um novo pedido."


class OrderRequiresApprovalError(OrdersError):
    """Order aguarda decisão humana (SPEC-003 §7)."""

    code = "ORDER_REQUIRES_APPROVAL"
    default_message = "Este pedido depende de aprovação para prosseguir."


class InvalidOrderStateError(OrdersError):
    """Estado atual incompatível com a operação solicitada."""

    code = "INVALID_ORDER_STATE"
    default_message = "O pedido não está em um estado compatível com esta operação."


class InvalidOrderStateTransitionError(OrdersError):
    """Transição não prevista na máquina de estados (SPEC-003 §14)."""

    code = "INVALID_ORDER_STATE_TRANSITION"
    default_message = "Transição de estado inválida para este pedido."


# --- Validação de entrada -----------------------------------------------


class UnsupportedOperationTypeError(OrdersError):
    """`operation_type` fora do escopo implementável (SPEC-003 §1.1).

    ⚠️ Código **não listado** em SPEC-003 §16: a SPEC restringe o MVP a
    `RECHARGE` mas não nomeia o erro da recusa. Recusa explícita é
    obrigatoriamente melhor que comportamento fictício para produto sem
    especificação (A-05), então o código existe aqui e está registrado como
    lacuna documental a ratificar.
    """

    code = "UNSUPPORTED_OPERATION_TYPE"
    default_message = "Este tipo de operação não está disponível."


class InvalidRechargeAmountError(OrdersError):
    """Valor de recarga inválido: não positivo ou com mais de 2 decimais.

    ⚠️ Código **não listado** em SPEC-003 §16. Em `RECHARGE` o valor é
    escolhido pelo cliente (§1.1) e precisa de validação determinística, mas a
    SPEC não nomeia o erro correspondente. Registrado como lacuna documental a
    ratificar. A mensagem não repete o valor recebido.
    """

    code = "INVALID_RECHARGE_AMOUNT"
    default_message = "Valor de recarga inválido."
