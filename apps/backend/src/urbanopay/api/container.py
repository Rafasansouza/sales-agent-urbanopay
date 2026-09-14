"""Composition root da aplicação HTTP (ADR-006: DI explícita).

Este é o único lugar que escolhe implementações concretas. Ele monta o engine,
a fábrica de sessões, os serviços de domínio, o provider de LLM, o provider de
pagamento, o runner do grafo e o coordenador pós-pagamento.

Três fronteiras que a montagem preserva:

- **o `ConversationRepository` não entra em `AgentServices`.** Aquele dataclass
  é "serviços disponíveis às tools", e **nenhuma tool pode ler ou escrever a
  persistência da conversa". O repositório pertence ao serviço de conversa, um
  nível acima;
- **o coordenador pós-pagamento é `BACKEND_ONLY`** e não é alcançável pela
  camada conversacional (SPEC-005 §10.1, A-19);
- **o sink de OTP só existe em `local`** (H-12), e nunca é tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from urbanopay.coordination import PostPaymentCoordinator
from urbanopay.core.config import PaymentProviderName, Settings
from urbanopay.db.engine import create_engine_from_settings
from urbanopay.db.session import create_session_factory
from urbanopay.modules.agent.application.conversation_service import ConversationService
from urbanopay.modules.agent.application.executor import ToolExecutor
from urbanopay.modules.agent.infrastructure.composition import build_agent_services
from urbanopay.modules.agent.infrastructure.graph import LangGraphTurnRunner
from urbanopay.modules.agent.infrastructure.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyTurnRequestStore,
)
from urbanopay.modules.identity.domain.value_objects import IdentityHasher
from urbanopay.modules.identity.infrastructure.dev_otp import DevOtpSink, RecordingOtpGenerator
from urbanopay.modules.identity.infrastructure.otp import SecretsOtpGenerator
from urbanopay.modules.payments.application.services import PaymentService
from urbanopay.modules.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork
from urbanopay.providers.llm import build_llm_provider
from urbanopay.providers.payments.fake import FakePaymentProvider

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from urbanopay.modules.agent.infrastructure.composition import AgentServices
    from urbanopay.modules.payments.domain.ports import PaymentProvider


@dataclass(frozen=True, slots=True)
class AppContainer:
    """Tudo o que os routers precisam, já montado."""

    settings: Settings
    engine: AsyncEngine
    services: AgentServices
    conversations: ConversationService
    payments: PaymentService
    coordinator: PostPaymentCoordinator
    payment_provider: PaymentProvider
    turn_requests: SqlAlchemyTurnRequestStore
    conversation_repository: SqlAlchemyConversationRepository
    session_factory: async_sessionmaker[AsyncSession]
    hasher: IdentityHasher
    otp_sink: DevOtpSink | None

    async def dispose(self) -> None:
        await self.engine.dispose()


def _build_payment_provider(settings: Settings) -> PaymentProvider:
    """Escolhe o provider de pagamento.

    `FakePaymentProvider` é o sandbox do MVP: ele demonstra criação, `PENDING`,
    `APPROVED`, `REJECTED` e timeout inconclusivo sem depender de rede
    (ADR-007). O adaptador do Mercado Pago exige credencial de teste que este
    repositório não possui, e por isso `mercadopago` ainda recusa
    explicitamente em vez de fingir.
    """
    if settings.payment_provider is PaymentProviderName.MERCADOPAGO:
        raise ValueError(
            "PAYMENT_PROVIDER=mercadopago exige um adaptador com credencial de teste, "
            "que nao existe neste MVP. Use PAYMENT_PROVIDER=fake."
        )
    return FakePaymentProvider()


def build_container(settings: Settings | None = None) -> AppContainer:
    """Monta a aplicação a partir da configuração."""
    resolved = settings or Settings()

    # Falha de credencial acontece **aqui**, no startup, e não no meio de uma
    # conversa: `LLM_PROVIDER=openai` sem chave não sobe (ADR-015).
    resolved.require_llm_credentials()

    engine = create_engine_from_settings(resolved)
    session_factory = create_session_factory(engine)
    hasher = IdentityHasher(resolved.identity_hash_secret.get_secret_value())

    otp_sink = DevOtpSink() if resolved.is_local else None
    generator = SecretsOtpGenerator()
    otp_generator = RecordingOtpGenerator(generator, otp_sink) if otp_sink else generator

    payment_provider = _build_payment_provider(resolved)

    services = build_agent_services(
        session_factory,
        settings=resolved,
        hasher=hasher,
        otp_generator=otp_generator,
        payment_provider=payment_provider,
    )

    executor = ToolExecutor(services, max_tool_calls_per_turn=resolved.max_tool_calls_per_turn)
    runner = LangGraphTurnRunner(
        executor=executor,
        llm=build_llm_provider(resolved),
        max_llm_calls_per_turn=resolved.max_llm_calls_per_turn,
    )

    conversation_repository = SqlAlchemyConversationRepository(session_factory)
    conversations = ConversationService(
        conversations=conversation_repository,
        runner=runner,
        executor=executor,
        sessions=services.sessions,
        orders=services.orders,
        conversation_ttl_minutes=resolved.conversation_ttl_minutes,
    )

    # `PaymentService` próprio para o caminho de backend (webhook e
    # reconciliação): ele não passa pelo agente, e uma instância de Unit of
    # Work não é reentrante.
    payments = PaymentService(SqlAlchemyPaymentsUnitOfWork(session_factory), payment_provider)

    return AppContainer(
        settings=resolved,
        engine=engine,
        services=services,
        conversations=conversations,
        payments=payments,
        coordinator=PostPaymentCoordinator(services.fulfillment),
        payment_provider=payment_provider,
        turn_requests=SqlAlchemyTurnRequestStore(session_factory),
        conversation_repository=conversation_repository,
        session_factory=session_factory,
        hasher=hasher,
        otp_sink=otp_sink,
    )


__all__ = ["AppContainer", "build_container"]
