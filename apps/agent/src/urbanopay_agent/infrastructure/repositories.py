"""Persistência do estado conversacional (ADR-014; ADR-012).

Diferente dos repositories de domínio, este **controla a própria transação**: a
persistência conversacional não participa da transação de Order, Approval,
Payment, Fulfillment ou saldo. A separação é deliberada e tem três razões
(ADR-014): cada serviço transacional já abre o próprio Unit of Work;
`create_payment` é bifásico e nenhuma transação pode ficar aberta durante a
chamada ao provider; e acoplar as duas inverteria a direção da falha, deixando
uma falha de gravação de conversa desfazer um efeito financeiro válido.

Nenhuma transação permanece aberta durante chamada ao LLM: a sessão é aberta
para a leitura, fechada, e reaberta para a escrita do fim do turno.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from urbanopay_agent.domain.conversation import (
    ConversationPhase,
    ConversationState,
    PendingConfirmation,
    StoredConversation,
)
from urbanopay_agent.domain.errors import ConversationConflictError
from urbanopay_agent.infrastructure.models import (
    AgentConversationModel,
    AgentTurnRequestModel,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _to_stored(model: AgentConversationModel) -> StoredConversation:
    """Mapeia a linha para o contrato da aplicação.

    `display_total` vem `None` de propósito: ele não é persistido (ADR-014) e
    é recomposto relendo o Order antes de qualquer reapresentação.
    """
    pending: PendingConfirmation | None = None
    if model.pending_confirmation_order_id is not None:
        # A constraint `pending_confirmation_pair` garante que o instante
        # acompanha o identificador; o assert de tipo abaixo é para o mypy.
        presented_at = model.pending_confirmation_presented_at
        if presented_at is not None:
            pending = PendingConfirmation(
                order_id=model.pending_confirmation_order_id,
                display_total=None,
                presented_at=presented_at,
            )

    state = ConversationState(
        conversation_id=model.id,
        session_id=model.session_id,
        phase=ConversationPhase(model.phase),
        selected_card_id=model.selected_card_id,
        current_quote_id=model.current_quote_id,
        current_order_id=model.current_order_id,
        current_payment_id=model.current_payment_id,
        pending_confirmation=pending,
    )
    return StoredConversation(
        state=state,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
        expires_at=model.expires_at,
    )


def _columns(state: ConversationState) -> dict[str, object]:
    """Colunas mutáveis derivadas do estado.

    Note o que **não** aparece aqui: saldo, `fare_profile`, status de qualquer
    agregado, valor monetário, mensagem, CPF, OTP ou hash. Não é filtragem —
    é que não existe coluna onde coubessem.
    """
    pending = state.pending_confirmation
    return {
        "phase": state.phase.value,
        "selected_card_id": state.selected_card_id,
        "current_quote_id": state.current_quote_id,
        "current_order_id": state.current_order_id,
        "current_payment_id": state.current_payment_id,
        "pending_confirmation_order_id": pending.order_id if pending else None,
        "pending_confirmation_presented_at": pending.presented_at if pending else None,
    }


class SqlAlchemyConversationRepository:
    """Implementa `ConversationRepository` sobre uma fábrica de sessões."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self, state: ConversationState, *, now: datetime, ttl_minutes: int
    ) -> StoredConversation:
        expires_at = now + timedelta(minutes=ttl_minutes)
        model = AgentConversationModel(
            id=state.conversation_id,
            session_id=state.session_id,
            version=1,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
            **_columns(state),
        )
        async with self._session_factory() as session:
            session.add(model)
            await session.commit()
        return StoredConversation(
            state=state,
            version=1,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

    async def get(self, conversation_id: UUID) -> StoredConversation | None:
        stmt = sa.select(AgentConversationModel).where(AgentConversationModel.id == conversation_id)
        async with self._session_factory() as session:
            model = (await session.execute(stmt)).scalar_one_or_none()
        return _to_stored(model) if model is not None else None

    async def update(
        self,
        state: ConversationState,
        *,
        expected_version: int,
        now: datetime,
        ttl_minutes: int,
    ) -> StoredConversation:
        """Compare-and-set em `version`.

        Zero linhas atingidas significa que outro turno da mesma conversa
        gravou primeiro. A escrita perdedora é **descartada**, nunca mesclada,
        e nunca vence por chegar depois.
        """
        expires_at = now + timedelta(minutes=ttl_minutes)
        next_version = expected_version + 1
        stmt = (
            sa.update(AgentConversationModel)
            .where(
                AgentConversationModel.id == state.conversation_id,
                AgentConversationModel.version == expected_version,
            )
            .values(
                session_id=state.session_id,
                version=next_version,
                updated_at=now,
                expires_at=expires_at,
                **_columns(state),
            )
            # `RETURNING` devolve o instante de criação original no mesmo
            # round-trip: sem ele, o estado devolvido mentiria sobre quando a
            # conversa nasceu.
            .returning(AgentConversationModel.created_at)
        )
        async with self._session_factory() as session:
            created_at = (await session.execute(stmt)).scalar_one_or_none()
            if created_at is None:
                await session.rollback()
                raise ConversationConflictError
            await session.commit()

        return StoredConversation(
            state=state,
            version=next_version,
            created_at=created_at,
            updated_at=now,
            expires_at=expires_at,
        )


class SqlAlchemyTurnRequestStore:
    """Deduplicação do request HTTP de conversa (ADR-014, D-6).

    Preocupação **distinta** das idempotências de negócio. Order, confirmação
    e cobrança continuam protegidos por keys derivadas de evidência persistida
    e por constraints de banco, e continuariam protegidos se esta tabela não
    existisse. O que ela evita é o que aquelas não cobrem: custo de LLM
    duplicado, contador inflado e duas respostas divergentes para a mesma
    mensagem.

    Deliberadamente **não** reutiliza `idempotency_records`, que é trilha de
    auditoria de comando de domínio (A-13): poluí-la com tráfego conversacional
    degradaria a auditoria financeira.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def replay(self, *, conversation_id: UUID, request_id: str) -> str | None:
        """Resposta anterior deste request, se ele já foi processado."""
        stmt = sa.select(AgentTurnRequestModel.response_body).where(
            AgentTurnRequestModel.conversation_id == conversation_id,
            AgentTurnRequestModel.request_id == request_id,
        )
        async with self._session_factory() as session:
            return (await session.execute(stmt)).scalar_one_or_none()

    async def remember(
        self, *, conversation_id: UUID, request_id: str, response_body: str, now: datetime
    ) -> None:
        """Registra a resposta do turno.

        `ON CONFLICT DO NOTHING`: duas entregas concorrentes do mesmo request
        gravam uma única linha, e a corrida não vira erro — a deduplicação é
        uma constraint de banco, não uma verificação em memória.
        """
        stmt = (
            pg_insert(AgentTurnRequestModel)
            .values(
                id=uuid4(),
                conversation_id=conversation_id,
                request_id=request_id,
                response_body=response_body,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["conversation_id", "request_id"])
        )
        async with self._session_factory() as session:
            await session.execute(stmt)
            await session.commit()
