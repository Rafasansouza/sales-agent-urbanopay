"""Painel do turno: fatos que a interface exibe (ADR-011, SPEC-004 §21).

A interface precisa mostrar o Pix, o total do pedido e o comprovante. Nada
disso é calculado aqui — e nada disso é novo: são exatamente os fatos que os
presenters já produziram para o modelo, republicados para a UI.

Por que republicar em vez de o frontend derivar da mensagem: a resposta do
agente é **prosa**, e prosa não é contrato. Extrair um valor de dinheiro de uma
frase seria dar ao frontend a responsabilidade de interpretar — exatamente o
que ADR-005 tira dele.

Três regras que este módulo materializa:

- **nada é calculado**, só copiado do envelope de tool;
- **valor monetário permanece string decimal** (ADR-006). Ele existe para ser
  exibido, nunca somado;
- **nada de PII**: os presenters já sanitizaram, e aqui não se acrescenta campo
  algum que eles não tenham produzido.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from urbanopay_agent.domain.results import ResultType

if TYPE_CHECKING:
    from collections.abc import Sequence

    from urbanopay_agent.domain.results import ToolData, ToolResult


@dataclass(frozen=True, slots=True)
class OrderPanel:
    """Pedido em curso, como a interface o mostra."""

    order_id: str
    status: str
    total: str
    currency: str
    requires_approval: bool


@dataclass(frozen=True, slots=True)
class PixPanel:
    """Cobrança Pix do sandbox.

    `qr_code` é o payload que o cliente copia ou escaneia. Ele é transitório:
    nunca é persistido e nunca é registrado em log.
    """

    payment_id: str
    status: str
    amount: str
    currency: str
    qr_code: str | None


@dataclass(frozen=True, slots=True)
class ReceiptPanel:
    """Comprovante simulado. `document_kind` viaja sempre (SPEC-005 §13.1)."""

    receipt_id: str
    amount: str
    currency: str
    masked_card: str
    document_kind: str
    issued_at: str


@dataclass(frozen=True, slots=True)
class TurnPanel:
    """O que a interface pode exibir depois de um turno."""

    order: OrderPanel | None = None
    pix: PixPanel | None = None
    receipt: ReceiptPanel | None = None
    fulfillment_status: str | None = None


def _text(data: ToolData, chave: str) -> str | None:
    valor = data.get(chave)
    return valor if isinstance(valor, str) else None


def build_panel(results: Sequence[ToolResult]) -> TurnPanel:
    """Extrai o painel dos resultados do turno.

    Percorre na ordem e deixa o **último** resultado de cada tipo prevalecer: um
    turno pode ler o Order e depois confirmá-lo, e o que a interface mostra é o
    estado final, não o intermediário.

    Resultado que não deu certo é ignorado: painel montado sobre falha
    afirmaria à interface algo que não aconteceu.
    """
    panel = TurnPanel()
    for result in results:
        if not result.ok:
            continue
        data = result.data
        if result.result_type is ResultType.ORDER:
            order_id, total = _text(data, "order_id"), _text(data, "total")
            status = _text(data, "status")
            if order_id and total and status:
                panel = _replace(
                    panel,
                    order=OrderPanel(
                        order_id=order_id,
                        status=status,
                        total=total,
                        currency=_text(data, "currency") or "BRL",
                        requires_approval=data.get("requires_approval") is True,
                    ),
                )
        elif result.result_type in (ResultType.PAYMENT, ResultType.PAYMENT_STATUS):
            payment_id, status = _text(data, "payment_id"), _text(data, "status")
            if payment_id and status:
                panel = _replace(
                    panel,
                    pix=PixPanel(
                        payment_id=payment_id,
                        status=status,
                        amount=_text(data, "amount") or "",
                        currency=_text(data, "currency") or "BRL",
                        qr_code=_text(data, "qr_code"),
                    ),
                )
        elif result.result_type is ResultType.FULFILLMENT_STATUS:
            panel = _replace(panel, fulfillment_status=_text(data, "status"))
        elif result.result_type is ResultType.RECEIPT:
            receipt_id = _text(data, "receipt_id")
            if receipt_id:
                panel = _replace(
                    panel,
                    receipt=ReceiptPanel(
                        receipt_id=receipt_id,
                        amount=_text(data, "amount") or "",
                        currency=_text(data, "currency") or "BRL",
                        masked_card=_text(data, "masked_card") or "",
                        document_kind=_text(data, "document_kind") or "",
                        issued_at=_text(data, "issued_at") or "",
                    ),
                )
    return panel


def _replace(panel: TurnPanel, **campos: object) -> TurnPanel:
    from dataclasses import replace

    return replace(panel, **campos)  # type: ignore[arg-type]
