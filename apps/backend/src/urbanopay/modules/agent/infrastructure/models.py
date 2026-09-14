"""Modelos ORM da camada conversacional (ADR-014; ADR-012).

**A tabela não contém dado pessoal algum** — não por sanitização, mas por
composição: todas as colunas são UUID opaco, texto de enum, inteiro ou
timestamp. Não há texto livre, não há JSONB e não há coluna monetária.

A ausência é o controle. Sem coluna onde caibam, não existe caminho pelo qual
CPF, OTP, hash, segredo, payload de provider, mensagem, saldo, `fare_profile`,
status ou valor de exibição entrem no estado durável.

`agent_turn_requests` resolve D-6 do ADR-014 — idempotência do **request HTTP**,
que é preocupação distinta das idempotências de negócio (`create_order`,
`confirm_order`, `create_payment`) e **não** usa `idempotency_records`, que é
trilha de auditoria de comando de domínio (A-13).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from urbanopay.db.base import Base
from urbanopay.modules.agent.domain.conversation import ConversationPhase

_PHASES = ", ".join(f"'{phase.value}'" for phase in ConversationPhase)


class AgentConversationModel(Base):
    """Estado conversacional durável de uma conversa (ADR-014).

    Snapshot por turno, sobrescrito: uma linha por conversa, sem histórico de
    versões. `version` é mecanismo de concorrência, não trilha.
    """

    __tablename__ = "agent_conversations"
    __table_args__ = (
        sa.CheckConstraint(f"phase IN ({_PHASES})", name="phase_valid"),
        # O par de confirmação é atômico: ou a conversa tem confirmação
        # pendente com instante de apresentação, ou não tem nenhuma das duas.
        sa.CheckConstraint(
            "(pending_confirmation_order_id IS NULL) = (pending_confirmation_presented_at IS NULL)",
            name="pending_confirmation_pair",
        ),
        # SPEC-004 §9.1 no banco: a confirmação pendente SEMPRE vincula o Order
        # corrente. É a defesa, em constraint, contra um "sim" confirmar outra
        # Order — inclusive uma Order válida do mesmo cliente.
        sa.CheckConstraint(
            "pending_confirmation_order_id IS NULL"
            " OR pending_confirmation_order_id = current_order_id",
            name="pending_confirmation_binds_current_order",
        ),
        sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.Index("ix_agent_conversations_session_id", "session_id"),
        sa.Index("ix_agent_conversations_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    # Única FK da tabela: `session_id` é âncora de identidade e ownership, e
    # dela se deriva `customer_id` a cada operação protegida. Os demais
    # identificadores são referências de navegação, revalidadas a cada uso —
    # uma FK sobre eles imporia integridade que o desenho não quer, e
    # distinguiria "id inexistente" de "recurso de terceiro" na escrita,
    # enfraquecendo a anti-enumeração.
    session_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("sessions.id"))
    phase: Mapped[str] = mapped_column(sa.Text())

    selected_card_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    current_quote_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    current_order_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    current_payment_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())

    pending_confirmation_order_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    pending_confirmation_presented_at: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True)
    )

    version: Mapped[int] = mapped_column(sa.Integer(), default=1)
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))


class AgentTurnRequestModel(Base):
    """Deduplicação do request HTTP de conversa (ADR-014 D-6).

    Escopo `(conversation_id, request_id)`: um retry do mesmo POST devolve a
    resposta anterior em vez de executar um segundo turno.

    **Não substitui idempotência de negócio.** Order, confirmação e cobrança
    continuam protegidos por suas próprias keys derivadas de evidência
    persistida e por constraints de banco — e continuariam protegidos se esta
    tabela não existisse. O que ela evita é custo de LLM, contador inflado e
    duas respostas divergentes para a mesma mensagem.

    `response_body` guarda a resposta já sanitizada da API, que por contrato
    não carrega PII nem valor autoritativo.
    """

    __tablename__ = "agent_turn_requests"
    __table_args__ = (sa.UniqueConstraint("conversation_id", "request_id"),)

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid())
    request_id: Mapped[str] = mapped_column(sa.Text())
    response_body: Mapped[str] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
