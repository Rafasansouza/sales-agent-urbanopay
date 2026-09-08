"""Montagem dos serviços que as tools consomem (ADR-006: DI explícita).

Este é o **único** arquivo do módulo `agent` que conhece infraestrutura. As
camadas `domain` e `application` recebem serviços de aplicação já prontos e não
sabem que existe SQLAlchemy — regra verificada por teste de arquitetura.

Dois formatos de serviço convivem no repositório, e a diferença não é
acidental:

- serviços **transacionais** (`identity`, `orders`, `payments`, `fulfillment`)
  recebem um Unit of Work e abrem a própria sessão por operação;
- serviços **somente-leitura** (`fare`, `cards`) recebem repositories já
  ligados a uma sessão.

Para os segundos, os adaptadores abaixo abrem **uma sessão por consulta**, no
mesmo padrão já usado pelo port de recuperação da SPEC-005. É correto porque
nenhuma dessas leituras precisa de transação comum: o Fare Engine resolve o
instante de referência **uma vez** e o usa idêntico em todas as consultas de
vigência (SPEC-001 §6), então a coerência vem do timestamp, não do isolamento.

Nenhum provider é escolhido aqui. `PaymentProvider` e `OtpGenerator` chegam por
injeção obrigatória: não existe adaptador de Mercado Pago, e inventar uma
seleção por configuração criaria um caminho que ninguém exercita. A escolha por
`Settings` pertence à composição HTTP, na Etapa 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from urbanopay.modules.cards.application.services import CardService
from urbanopay.modules.cards.infrastructure.repositories import SqlAlchemyCardRepository
from urbanopay.modules.fare.application.services import FareService
from urbanopay.modules.fare.infrastructure.repositories import (
    SqlAlchemyFareRepository,
    SqlAlchemyFareRuleRepository,
)
from urbanopay.modules.fulfillment.application.services import FulfillmentService
from urbanopay.modules.fulfillment.infrastructure.uow import SqlAlchemyFulfillmentUnitOfWork
from urbanopay.modules.identity.application.services import (
    AuthenticationService,
    SessionService,
)
from urbanopay.modules.identity.infrastructure.uow import SqlAlchemyIdentityUnitOfWork
from urbanopay.modules.orders.application.services import OrderService, QuoteService
from urbanopay.modules.orders.domain.policies import ApprovalPolicy
from urbanopay.modules.orders.infrastructure.uow import SqlAlchemyOrdersUnitOfWork
from urbanopay.modules.payments.application.services import PaymentService
from urbanopay.modules.payments.infrastructure.uow import SqlAlchemyPaymentsUnitOfWork

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from urbanopay.core.config import Settings
    from urbanopay.modules.cards.domain.entities import Card
    from urbanopay.modules.fare.domain.entities import Fare, FareRule
    from urbanopay.modules.fare.domain.enums import FareProfile, TripType
    from urbanopay.modules.fare.domain.value_objects import FareLookupKey
    from urbanopay.modules.identity.domain.ports import OtpGenerator
    from urbanopay.modules.identity.domain.value_objects import IdentityHasher
    from urbanopay.modules.payments.domain.ports import PaymentProvider


class _SessionScopedFareRepository:
    """`FareRepository` com uma sessão por consulta."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_active_fares(
        self, profile: FareProfile, keys: frozenset[FareLookupKey], at: datetime
    ) -> dict[FareLookupKey, Fare]:
        async with self._session_factory() as session:
            return await SqlAlchemyFareRepository(session).find_active_fares(profile, keys, at)

    async def known_bus_lines(self, line_codes: frozenset[str]) -> frozenset[str]:
        async with self._session_factory() as session:
            return await SqlAlchemyFareRepository(session).known_bus_lines(line_codes)


class _SessionScopedFareRuleRepository:
    """`FareRuleRepository` com uma sessão por consulta."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_active_rule(self, trip_type: TripType, at: datetime) -> FareRule | None:
        async with self._session_factory() as session:
            return await SqlAlchemyFareRuleRepository(session).find_active_rule(trip_type, at)


class _SessionScopedCardRepository:
    """`CardRepository` com uma sessão por consulta.

    Somente leitura e sempre escopado pelo cliente autenticado: `get_owned`
    aplica titularidade na **mesma** query, e continua sendo a única porta de
    acesso a cartão por aqui. O port de mutação de saldo não é composto: ele
    pertence ao fulfillment, e nenhuma tool o alcança.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_for_customer(self, customer_id: UUID) -> list[Card]:
        async with self._session_factory() as session:
            return await SqlAlchemyCardRepository(session).list_for_customer(customer_id)

    async def get_owned(self, customer_id: UUID, card_id: UUID) -> Card | None:
        async with self._session_factory() as session:
            return await SqlAlchemyCardRepository(session).get_owned(customer_id, card_id)


@dataclass(frozen=True, slots=True)
class AgentServices:
    """Serviços de aplicação disponíveis às tools.

    Contém **apenas** serviços de aplicação. Não há sessão, repositório
    concreto nem provider aqui: uma tool não tem como alcançar o banco por
    fora do serviço que a SPEC autoriza.

    Ausentes de propósito, porque nenhuma tool pode invocá-los:
    `FulfillmentRecoveryService`, o port de crédito de saldo e qualquer
    caminho de webhook.
    """

    sessions: SessionService
    authentication: AuthenticationService
    fare: FareService
    cards: CardService
    quotes: QuoteService
    orders: OrderService
    payments: PaymentService
    fulfillment: FulfillmentService


def build_agent_services(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    hasher: IdentityHasher,
    otp_generator: OtpGenerator,
    payment_provider: PaymentProvider,
) -> AgentServices:
    """Compõe os serviços a partir de uma fábrica de sessões.

    Cada serviço transacional recebe a **própria** instância de Unit of Work:
    uma `AsyncSession` nunca é compartilhada entre tasks concorrentes
    (ADR-012), e uma instância de UoW não é reentrante.

    Os TTLs vêm de `Settings`, que é a fonte canônica de configuração — nenhum
    valor de política é redefinido aqui.
    """
    return AgentServices(
        sessions=SessionService(
            SqlAlchemyIdentityUnitOfWork(session_factory),
            session_ttl=timedelta(minutes=settings.session_ttl_minutes),
        ),
        authentication=AuthenticationService(
            SqlAlchemyIdentityUnitOfWork(session_factory),
            hasher=hasher,
            otp_generator=otp_generator,
            otp_ttl=timedelta(minutes=settings.otp_ttl_minutes),
            otp_max_attempts=settings.otp_max_attempts,
            session_ttl=timedelta(minutes=settings.session_ttl_minutes),
        ),
        fare=FareService(
            fares=_SessionScopedFareRepository(session_factory),
            fare_rules=_SessionScopedFareRuleRepository(session_factory),
        ),
        cards=CardService(_SessionScopedCardRepository(session_factory)),
        quotes=QuoteService(
            SqlAlchemyOrdersUnitOfWork(session_factory),
            quote_ttl=timedelta(minutes=settings.quote_ttl_minutes),
        ),
        orders=OrderService(
            SqlAlchemyOrdersUnitOfWork(session_factory),
            ApprovalPolicy(),
            draft_ttl=timedelta(minutes=settings.order_draft_ttl_minutes),
        ),
        payments=PaymentService(SqlAlchemyPaymentsUnitOfWork(session_factory), payment_provider),
        fulfillment=FulfillmentService(SqlAlchemyFulfillmentUnitOfWork(session_factory)),
    )
