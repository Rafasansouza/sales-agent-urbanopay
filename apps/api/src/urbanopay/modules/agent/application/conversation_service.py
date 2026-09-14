"""Serviço de conversa: o ciclo de vida de um turno (ADR-014; SPEC-004).

```text
1. carregar ConversationState por conversation_id
2. avaliar expiração na leitura (ausente ou expirada ⇒ conversa nova)
3. reler o backend e reconciliar o contexto
4. interceptar entrada sensível, ANTES de qualquer chamada ao provider
5. executar o turno (grafo)
6. ações de negócio já comitaram nos seus próprios Unit of Work
7. optimistic update do ConversationState, em transação própria
8. fim do turno
```

Duas decisões estruturais moram aqui.

**A persistência conversacional não compartilha transação** com Order,
Approval, Payment, Fulfillment ou saldo. Se o commit de negócio deu certo e a
gravação da conversa falhou, **não existe compensação financeira**: o turno
seguinte relê o backend e reconstrói o contexto. A direção inversa — uma falha
de gravação de conversa desfazendo um efeito financeiro válido — trocaria um
problema recuperável por um irrecuperável.

**Nenhuma transação permanece aberta durante a chamada ao LLM.** A leitura
fecha antes do grafo começar, e a escrita abre depois de ele terminar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from urbanopay.modules.agent.application import sensitive_input
from urbanopay.modules.agent.application.reconciliation import reconcile
from urbanopay.modules.agent.application.turn import TurnOutcome
from urbanopay.modules.agent.domain.conversation import (
    ConversationPhase,
    StoredConversation,
    new_conversation,
)
from urbanopay.modules.identity.domain.errors import (
    NotAuthenticatedError,
    SessionExpiredError,
    SessionNotFoundError,
)
from urbanopay.modules.orders.domain.errors import (
    OrderNotAccessibleError,
    OrderNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from urbanopay.modules.agent.application.executor import ToolExecutor
    from urbanopay.modules.agent.application.turn import TurnRunner
    from urbanopay.modules.agent.domain.conversation import ConversationState
    from urbanopay.modules.agent.domain.ports import ConversationRepository
    from urbanopay.modules.identity.application.services import SessionService
    from urbanopay.modules.orders.application.services import OrderService


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """Resultado de um turno, pronto para o transporte.

    Só campos que a API pode expor: nada de identificador interno de Quote,
    Payment ou Fulfillment, nada de valor autoritativo e nada de PII.
    """

    conversation_id: UUID
    session_id: UUID
    phase: str
    reply: str
    code: str | None
    next_action: str | None


class ConversationService:
    """Orquestra o ciclo de vida de uma conversa."""

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        runner: TurnRunner,
        executor: ToolExecutor,
        sessions: SessionService,
        orders: OrderService,
        conversation_ttl_minutes: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._conversations = conversations
        self._runner = runner
        self._executor = executor
        self._sessions = sessions
        self._orders = orders
        self._ttl = conversation_ttl_minutes
        self._clock = clock

    async def handle_message(
        self,
        *,
        message: str,
        conversation_id: UUID | None = None,
        session_id: UUID | None = None,
    ) -> ConversationTurn:
        """Processa uma mensagem do cliente e devolve a resposta do turno."""
        now = self._clock()
        stored = await self._load(conversation_id=conversation_id, session_id=session_id, now=now)

        identity = await self._resolve_identity(stored.state)
        state = await self._reconciled(stored.state, customer_id=identity)
        state = state.begin_turn()

        outcome = await self._execute(state, message=message, authenticated=identity is not None)
        saved = await self._persist(stored, outcome.state, now=self._clock())

        return ConversationTurn(
            conversation_id=saved.conversation_id,
            session_id=saved.session_id,
            phase=saved.phase.value,
            reply=outcome.reply,
            code=outcome.last_code,
            next_action=outcome.next_action.value if outcome.next_action else None,
        )

    # --- etapas ------------------------------------------------------------

    async def _load(
        self, *, conversation_id: UUID | None, session_id: UUID | None, now: datetime
    ) -> StoredConversation:
        """Carrega a conversa, ou cria uma nova.

        Conversa expirada é tratada como **ausente**, avaliado na leitura: é o
        que faz a correção não depender de nenhuma rotina de purga ter rodado.
        Nada financeiro é tocado por isso — Order, Payment e Fulfillment têm
        ciclos próprios e são autoritativos.
        """
        if conversation_id is not None:
            existing = await self._conversations.get(conversation_id)
            if existing is not None and not existing.is_expired(now):
                state = existing.state
                if session_id is not None and session_id != state.session_id:
                    # Revinculação a outra sessão limpa a confirmação pendente:
                    # a pessoa do outro lado pode ter mudado.
                    state = state.with_session(session_id)
                return StoredConversation(
                    state=state,
                    version=existing.version,
                    created_at=existing.created_at,
                    updated_at=existing.updated_at,
                    expires_at=existing.expires_at,
                )

        resolved = session_id or (await self._sessions.create_anonymous_session(now)).id
        return await self._conversations.create(
            new_conversation(resolved), now=now, ttl_minutes=self._ttl
        )

    async def _resolve_identity(self, state: ConversationState) -> UUID | None:
        """Verdade da sessão, relida a cada turno.

        Sessão expirada **não** apaga a conversa: ela apenas deixa de
        autenticar. Como o estado conversacional nunca guardou `authenticated`,
        não existe nada a invalidar aqui — é o retorno do investimento de não
        ter uma segunda autoridade de identidade.
        """
        try:
            status = await self._sessions.get_authentication_status(state.session_id)
        except (SessionNotFoundError, SessionExpiredError, NotAuthenticatedError):
            return None
        return status.customer_id if status.authenticated else None

    async def _reconciled(
        self, state: ConversationState, *, customer_id: UUID | None
    ) -> ConversationState:
        """Alinha a conversa ao backend antes de qualquer decisão.

        Roda **antes** do modelo, para que ele não veja um contexto que já
        sabemos obsoleto. Não escreve nada no domínio: só ajusta referências.
        """
        order_id = state.current_order_id
        if order_id is None or customer_id is None:
            return state
        try:
            order = await self._orders.get_order(customer_id=customer_id, order_id=order_id)
        except (OrderNotFoundError, OrderNotAccessibleError):
            # Referência morta ou de outro cliente: a conversa recomeça limpa,
            # e o "não é seu" é indistinguível de "não existe", de propósito.
            return state.without_journey_references()
        return reconcile(state, order.status)

    async def _execute(
        self, state: ConversationState, *, message: str, authenticated: bool
    ) -> TurnOutcome:
        """Entrada sensível primeiro; só depois, se necessário, o modelo.

        Nas fases `AWAITING_DOCUMENT` e `AWAITING_OTP`, o CPF e o OTP são
        consumidos por handler determinístico e **nunca** alcançam o provider,
        o grafo, o log ou a tabela (SPEC-004 §13.1).
        """
        if sensitive_input.is_sensitive(state):
            handled = await sensitive_input.handle(self._executor, state=state, message=message)
            # O turno segue com a mensagem já redigida: o modelo compõe a
            # resposta a partir do resultado da autenticação, sem ver o valor.
            outcome = await self._runner.run(
                state=handled.state,
                message=handled.redacted_message,
                authenticated=authenticated,
                # O efeito do turno já aconteceu: reexecutar o playbook sobre
                # um marcador de redação trataria `[OTP_REDACTED]` como fala.
                skip_action=True,
            )
            return TurnOutcome(
                state=outcome.state,
                reply=outcome.reply,
                results=(handled.result, *outcome.results),
            )
        return await self._runner.run(state=state, message=message, authenticated=authenticated)

    async def _persist(
        self, stored: StoredConversation, state: ConversationState, *, now: datetime
    ) -> ConversationState:
        """Snapshot do fim do turno, com concorrência otimista.

        Conflito não é tratado aqui: ele sobe como `ConversationConflictError`
        e é o transporte que decide o contrato de resposta. Mesclar contextos
        divergentes é o que produziria a confirmação errada.
        """
        saved = await self._conversations.update(
            state, expected_version=stored.version, now=now, ttl_minutes=self._ttl
        )
        return saved.state


__all__ = ["ConversationPhase", "ConversationService", "ConversationTurn"]
