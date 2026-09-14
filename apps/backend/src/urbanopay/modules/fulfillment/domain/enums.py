"""Enums do domínio de fulfillment (SPEC-005 §3, §5, §7, §11, §13)."""

from __future__ import annotations

from enum import StrEnum

from urbanopay.modules.fulfillment.domain.errors import UnsupportedFulfillmentTypeError


class FulfillmentType(StrEnum):
    """Tipo de entrega (SPEC-005 §3).

    `TICKET_ISSUANCE` existe no enum porque a SPEC o define, mas **não é
    implementável no MVP**: depende do catálogo bloqueado por A-05 e da
    validade de bilhete que o PRD §19 mantém pendente. A recusa é explícita,
    nunca comportamento fictício.
    """

    RECHARGE = "RECHARGE"
    TICKET_ISSUANCE = "TICKET_ISSUANCE"

    def require_supported(self) -> None:
        """Recusa explicitamente o que não é implementável (§1.1)."""
        if self is not FulfillmentType.RECHARGE:
            raise UnsupportedFulfillmentTypeError


class FulfillmentStatus(StrEnum):
    """Os cinco estados do Fulfillment (SPEC-005 §5).

    Em `RECHARGE`, `PENDING → PROCESSING → COMPLETED` ocorre dentro da mesma
    transação e não é observável de fora — decisão deliberada: commit
    intermediário criaria janela de estado financeiro parcial. Os estados
    passam a ser observáveis quando o fulfillment tiver etapa externa.

    `RECONCILIATION_REQUIRED` marca evidência inconsistente que exige análise
    humana. Não é falha de negócio: é ausência de conclusão segura.
    """

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class LedgerEntryType(StrEnum):
    """Tipo de movimento no ledger do cartão (SPEC-005 §7).

    O MVP credita e não debita, por isso existe um único tipo. Débito exigiria
    decisão documental — e revisão da constraint de saldo não negativo.
    """

    RECHARGE_CREDIT = "RECHARGE_CREDIT"


class FailureClass(StrEnum):
    """Classificação de falha (SPEC-005 §11).

    Em `RECHARGE` não existe retentativa automática: o efeito é uma transação
    local que acontece por inteiro ou não acontece, e não há resultado externo
    a interpretar. A classificação permanece porque orienta a decisão humana e
    ganha uso pleno quando existir etapa externa.
    """

    RETRYABLE = "RETRYABLE"
    NON_RETRYABLE = "NON_RETRYABLE"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


class DocumentKind(StrEnum):
    """Natureza do comprovante (SPEC-005 §13).

    Um único valor, e proposital: este sistema **não** emite documento fiscal.
    O enum existe para que a natureza seja um fato persistido, não uma
    suposição de quem lê a tabela.
    """

    SIMULATED_NON_FISCAL = "SIMULATED_NON_FISCAL"


# Moeda única do MVP, coerente com Order e Payment.
CURRENCY_BRL = "BRL"

# Versão do texto de aviso do comprovante. Persistida junto do Receipt para
# que o documento histórico continue explicitamente não fiscal mesmo que a
# redação mude (§13.1).
DISCLAIMER_VERSION = "1"

DISCLAIMER_TEXT = (
    "DOCUMENTO SIMULADO — SEM VALIDADE FISCAL. "
    "Comprovante de demonstração da plataforma UrbanoPay Mobilidade."
)
