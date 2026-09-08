"""Estado conversacional (SPEC-004 §3, §3.1).

Regra que governa todo este módulo:

> **Agent state é cache de orquestração, nunca autoridade de negócio.**

O que vive aqui são **referências** — quais recursos a conversa está tratando —
e nada mais. Saldo, `fare_profile`, status de Order, Payment, Approval,
Fulfillment e Card **não** entram: eles ficam obsoletos, e um valor obsoleto
usado em decisão é um defeito financeiro esperando acontecer. Antes de operação
crítica, o backend relê o estado persistido.

Também não entram, em nenhuma fase: `authenticated`, `customer_id`, CPF, OTP,
hash ou segredo. Identidade é derivada da sessão de `identity` a cada operação
protegida — guardá-la aqui criaria uma segunda autoridade, que sobreviveria à
expiração da sessão.

O estado é **efêmero** nesta etapa: não existe tabela, não existe migration e
não existe checkpoint. A persistência conversacional depende do ADR-014
(H-11) e pertence à Etapa 2 (§22).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from urbanopay.modules.agent.domain.catalog import ToolName


class ConversationPhase(StrEnum):
    """Fase da conversa (SPEC-004 §3).

    `AWAITING_DOCUMENT` e `AWAITING_OTP` refinam `AUTHENTICATION` para o
    handler de entrada sensível de §13.1: é a fase que diz ao transporte que a
    próxima mensagem do cliente precisa ser interceptada **antes** do modelo.
    A entrada nessas fases pertence ao grafo (Etapa 2).
    """

    DISCOVERY = "DISCOVERY"
    CALCULATION = "CALCULATION"
    RECOMMENDATION = "RECOMMENDATION"
    AUTHENTICATION = "AUTHENTICATION"
    AWAITING_DOCUMENT = "AWAITING_DOCUMENT"
    AWAITING_OTP = "AWAITING_OTP"
    CARD_SELECTION = "CARD_SELECTION"
    QUOTE = "QUOTE"
    ORDER_CONFIRMATION = "ORDER_CONFIRMATION"
    APPROVAL = "APPROVAL"
    PAYMENT = "PAYMENT"
    FULFILLMENT = "FULFILLMENT"
    POST_SALE = "POST_SALE"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


SENSITIVE_INPUT_PHASES = frozenset(
    {ConversationPhase.AWAITING_DOCUMENT, ConversationPhase.AWAITING_OTP}
)
"""Fases em que a mensagem do cliente carrega CPF ou OTP (§13.1).

Nelas, a entrada é tratada por handler determinístico antes de qualquer
chamada ao provider, e o histórico destinado ao modelo recebe
`[DOCUMENT_REDACTED]` / `[OTP_REDACTED]`.
"""

DOCUMENT_REDACTION_MARKER = "[DOCUMENT_REDACTED]"
OTP_REDACTION_MARKER = "[OTP_REDACTED]"


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    """Order apresentada ao cliente e aguardando confirmação explícita (§9.1).

    É o vínculo que impede que um "sim" confirme a Order errada, uma Order
    antiga ou uma Order que o cliente nunca viu.

    ⚠️ **`display_total` NÃO é autoritativo.** Ele existe para uma única
    finalidade: compor a frase já apresentada ("você confirma R$ 100,00?").
    Nenhuma decisão o consulta — o valor que vale é `order.total`, relido do
    PostgreSQL a cada operação crítica (§3.1).
    """

    order_id: uuid.UUID
    display_total: str
    presented_at: datetime

    def binds(self, order_id: uuid.UUID) -> bool:
        return self.order_id == order_id


@dataclass(frozen=True, slots=True)
class ConversationState:
    """Referências de orquestração de uma conversa. Imutável.

    Contadores de turno servem aos limites de SPEC-004 §14 e são orquestração,
    não negócio: reiniciar um contador não altera nada que já aconteceu.
    """

    conversation_id: uuid.UUID
    session_id: uuid.UUID
    phase: ConversationPhase = ConversationPhase.DISCOVERY
    selected_card_id: uuid.UUID | None = None
    current_quote_id: uuid.UUID | None = None
    current_order_id: uuid.UUID | None = None
    current_payment_id: uuid.UUID | None = None
    pending_confirmation: PendingConfirmation | None = None
    tool_calls_this_turn: int = 0
    last_tool: ToolName | None = None
    last_code: str | None = None

    def begin_turn(self) -> ConversationState:
        """Zera o contador de tool calls do turno (§14)."""
        return replace(self, tool_calls_this_turn=0)

    def with_phase(self, phase: ConversationPhase) -> ConversationState:
        return replace(self, phase=phase)

    def counted_tool_call(self, tool: ToolName, code: str) -> ConversationState:
        return replace(
            self,
            tool_calls_this_turn=self.tool_calls_this_turn + 1,
            last_tool=tool,
            last_code=code,
        )

    def with_selected_card(self, card_id: uuid.UUID) -> ConversationState:
        return replace(self, selected_card_id=card_id)

    def with_quote(self, quote_id: uuid.UUID) -> ConversationState:
        return replace(self, current_quote_id=quote_id)

    def awaiting_confirmation(self, pending: PendingConfirmation) -> ConversationState:
        """Registra a Order apresentada, que passa a ser a única confirmável."""
        return replace(self, current_order_id=pending.order_id, pending_confirmation=pending)

    def confirmed(self) -> ConversationState:
        """Consome a confirmação pendente.

        Limpar é o que impede que um segundo "sim", num turno posterior, volte
        a encontrar contexto de confirmação aberto.
        """
        return replace(self, pending_confirmation=None)

    def with_payment(self, payment_id: uuid.UUID) -> ConversationState:
        return replace(self, current_payment_id=payment_id)


def new_conversation(session_id: uuid.UUID) -> ConversationState:
    """Cria o estado de uma conversa nova sobre uma sessão de `identity`."""
    return ConversationState(conversation_id=uuid.uuid4(), session_id=session_id)
