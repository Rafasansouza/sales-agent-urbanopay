"""Política de aprovação humana (SPEC-003 §7).

Único lugar do sistema onde o limiar existe. A SPEC exige encapsulamento:
o valor **nunca** aparece em `if` espalhado pela aplicação, e nenhum outro
módulo redefine a regra.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from urbanopay.modules.orders.domain.enums import OperationType

# Limiar inicial da SPEC-003 §7. A comparação é ESTRITAMENTE MAIOR:
# R$ 200,00 exatos NÃO exigem aprovação.
DEFAULT_APPROVAL_THRESHOLD = Decimal("200.00")


@dataclass(frozen=True, slots=True)
class ApprovalPolicy:
    """Decide se um Order exige aprovação humana.

    Determinística e pura: mesma entrada, mesma saída. O limiar é injetável
    para que testes exercitem a fronteira sem reescrever a regra.
    """

    threshold: Decimal = DEFAULT_APPROVAL_THRESHOLD

    def requires_approval(self, *, operation_type: OperationType, total: Decimal) -> bool:
        """`True` quando `total > threshold` (§7).

        A regra da SPEC é escrita para `RECHARGE`, o único tipo implementável
        no MVP (§1.1); `TICKET_PURCHASE` é recusado antes de chegar aqui. O
        limiar é aplicado a qualquer tipo por conservadorismo: na dúvida,
        exigir aprovação humana é o lado seguro.
        """
        del operation_type  # ainda não diferencia: só RECHARGE é alcançável.
        return total > self.threshold
