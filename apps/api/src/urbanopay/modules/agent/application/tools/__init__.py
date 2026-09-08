"""Implementações das tools (SPEC-004 §7).

Uma função por tool. Todas recebem o mesmo `ToolContext` e devolvem o mesmo
envelope, e **nenhuma** escreve no estado conversacional: a transição de estado
é derivada do resultado, num único lugar (`state_transitions`), para que não
exista uma segunda regra escondida dentro de um handler.

O que os handlers **não** fazem, por construção: resolver sessão (o executor já
resolveu), decidir se a tool podia ser chamada (o executor já decidiu), montar
idempotency key à mão (a política é pura e vive no domínio) e formatar dado de
saída (os presenters são o único caminho).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from urbanopay.modules.agent.domain.conversation import ConversationState
    from urbanopay.modules.agent.infrastructure.composition import AgentServices


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Tudo o que um handler pode alcançar.

    `customer_id` chega **já resolvido pelo executor** a partir da sessão, e é
    `None` apenas nas tools que a matriz de SPEC-002 §9 permite a sessão
    anônima. Nenhum handler recebe `customer_id` do modelo, e nenhum tem acesso
    a sessão de banco, repositório concreto ou provider.
    """

    services: AgentServices
    state: ConversationState
    customer_id: UUID | None = None

    def require_customer(self) -> UUID:
        """Identidade autenticada da operação.

        Falha aqui é defeito de configuração do registry — uma tool que exige
        autenticação sem declará-la —, não entrada do usuário.
        """
        if self.customer_id is None:  # pragma: no cover - garantido pelo executor
            raise RuntimeError("Tool autenticada executada sem identidade resolvida.")
        return self.customer_id
