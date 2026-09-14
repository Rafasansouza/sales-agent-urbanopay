"""Ports da camada conversacional (ADR-014).

O estado conversacional durável **pertence à aplicação**, não ao framework de
orquestração: não existe checkpointer nativo, não existe tabela criada por
runtime e nenhum tipo do LangGraph atravessa esta fronteira.

Regra que governa todo consumidor deste port:

> **O estado conversacional é cache de orquestração. Nunca autoridade
> financeira.**

Ele guarda referências — quais recursos a conversa está tratando. Saldo,
`fare_profile`, status de Card, Order, Approval, Payment e Fulfillment são
relidos do PostgreSQL antes de qualquer operação crítica (SPEC-004 §3.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from urbanopay_agent.domain.conversation import (
        ConversationState,
        StoredConversation,
    )


class ConversationRepository(Protocol):
    """Persistência do estado conversacional.

    Diferente dos repositories de domínio, este **controla a própria
    transação**: a persistência conversacional não participa da transação de
    Order, Approval, Payment, Fulfillment ou saldo (ADR-014). Se o commit de
    negócio deu certo e a gravação da conversa falhou, **não existe
    compensação financeira** — o turno seguinte relê o backend e reconstrói o
    contexto.
    """

    async def create(
        self, state: ConversationState, *, now: datetime, ttl_minutes: int
    ) -> StoredConversation:
        """Insere uma conversa nova e devolve a versão inicial."""
        ...

    async def get(self, conversation_id: UUID) -> StoredConversation | None:
        """Carrega a conversa, sem avaliar expiração.

        A expiração é decisão do chamador, tomada **na leitura**
        (`StoredConversation.is_expired`), para que a correção nunca dependa
        de uma rotina de purga ter rodado.
        """
        ...

    async def update(
        self,
        state: ConversationState,
        *,
        expected_version: int,
        now: datetime,
        ttl_minutes: int,
    ) -> StoredConversation:
        """Grava o snapshot do fim do turno, com concorrência otimista.

        Executa `UPDATE ... WHERE conversation_id = ? AND version = ?`. Se
        nenhuma linha for atingida, outro turno gravou primeiro e a
        implementação levanta `ConversationConflictError`.

        **Nunca last-write-wins silencioso**, e nunca merge: mesclar dois
        contextos divergentes é o que produziria a confirmação errada.
        """
        ...
