"""Erros semânticos do domínio de aprovação (SPEC-003 §16).

Puros: código estável + mensagem, sem HTTP e sem PII.

Sobre reuso de código: a SPEC-003 §16 não define código para "aprovação já
decidida". Conforme a decisão aprovada de **não inventar código novo** para a
redecisão, `InvalidApprovalStateError` reutiliza o código documentado
`INVALID_ORDER_STATE` — a operação recusada é, de fato, uma operação sobre um
Order em estado incompatível. O erro vive neste módulo para não inverter a
direção de dependência (`approvals` nunca importa `orders`).
"""

from __future__ import annotations

from typing import ClassVar


class ApprovalsError(Exception):
    """Base dos erros de aprovação."""

    code: ClassVar[str]
    default_message: ClassVar[str]

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class ApprovalPendingError(ApprovalsError):
    """Operação exige decisão humana que ainda não ocorreu (§16)."""

    code = "APPROVAL_PENDING"
    default_message = "Este pedido aguarda aprovação."


class ApprovalRejectedError(ApprovalsError):
    """A aprovação foi rejeitada (§16)."""

    code = "APPROVAL_REJECTED"
    default_message = "A aprovação deste pedido foi rejeitada."


class ApprovalNotFoundError(ApprovalsError):
    """Não existe `Approval` para o Order informado.

    Reutiliza `ORDER_NOT_FOUND`: quem consulta aprovação é a superfície
    administrativa (A-07), e a ausência de aprovação para um Order é, do ponto
    de vista do consultante, ausência do recurso pedido. Nenhum código novo é
    introduzido.
    """

    code = "ORDER_NOT_FOUND"
    default_message = "Não há aprovação registrada para este pedido."


class InvalidApprovalStateError(ApprovalsError):
    """Decisão sobre `Approval` que já saiu de `PENDING` (§7).

    Estados terminais não retornam a `PENDING` e não são redecididos.
    """

    code = "INVALID_ORDER_STATE"
    default_message = "Esta aprovação já foi decidida."
