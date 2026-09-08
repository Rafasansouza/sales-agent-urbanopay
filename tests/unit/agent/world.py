"""Mundo em memória para os testes unitários do Sales Agent.

Monta um `AgentServices` **real** — os serviços de aplicação de verdade — sobre
os fakes de porta que cada módulo já mantém. Isso importa: se estes testes
usassem dublês dos próprios serviços, provariam apenas que a camada de tools
chama alguém, não que a fronteira segura de fato.

Escopo deliberado: `orders`/`payments` compartilham um `Store`, e `fulfillment`
tem o seu. Nada aqui tenta reproduzir a coerência transacional do PostgreSQL —
isso é trabalho dos testes de integração, e fingir aqui daria falsa confiança.

Todos os dados são fictícios.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from tests.unit.cards.fakes import InMemoryCardRepository, make_card
from tests.unit.fare.fakes import (
    InMemoryFareRepository,
    InMemoryFareRuleRepository,
    make_rule,
    official_fares,
)
from tests.unit.fulfillment import fakes as fulfillment_fakes
from tests.unit.identity.fakes import (
    FakeIdentityUnitOfWork,
    FakeOtpGenerator,
    build_hasher,
    make_customer,
)
from tests.unit.orders_payments.fakes import (
    FakeOrdersUnitOfWork,
    FakePaymentsUnitOfWork,
    Store,
)
from urbanopay.modules.agent.domain.conversation import ConversationState
from urbanopay.modules.agent.infrastructure.composition import AgentServices
from urbanopay.modules.cards.application.services import CardService
from urbanopay.modules.cards.domain.enums import CardStatus, FareProfile
from urbanopay.modules.fare.application.services import FareService
from urbanopay.modules.fulfillment.application.services import FulfillmentService
from urbanopay.modules.identity.application.services import (
    AuthenticationService,
    SessionService,
)
from urbanopay.modules.identity.domain.entities import Session
from urbanopay.modules.orders.application.services import OrderService, QuoteService
from urbanopay.modules.orders.domain.policies import ApprovalPolicy
from urbanopay.modules.payments.application.services import PaymentService
from urbanopay.providers.payments.fake import FakePaymentProvider

if TYPE_CHECKING:
    from urbanopay.modules.cards.domain.entities import Card
    from urbanopay.modules.identity.domain.entities import Customer

FIXED_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
SESSION_TTL = timedelta(minutes=30)
OTP_TTL = timedelta(minutes=5)
QUOTE_TTL = timedelta(minutes=10)
DRAFT_TTL = timedelta(minutes=10)


class AgentWorld:
    """Serviços reais sobre portas em memória, com atalhos de cenário."""

    def __init__(
        self,
        *,
        customer: Customer | None = None,
        cards: list[Card] | None = None,
        extra_cards: list[Card] | None = None,
        authenticated: bool = True,
    ) -> None:
        self.customer = customer if customer is not None else make_customer()
        self.cards = (
            cards
            if cards is not None
            else [make_card(customer_id=self.customer.id, profile=FareProfile.INTEGRAL)]
        )
        # `extra_cards` existe no repositório mas não pertence ao cliente deste
        # mundo: é assim que se monta o cenário cross-user sem que o cartão
        # apareça em `self.cards`.
        stored_cards = [*self.cards, *(extra_cards or [])]
        self.identity_uow = FakeIdentityUnitOfWork([self.customer])
        self.store = Store()
        self.provider = FakePaymentProvider()

        # A sessão é ancorada no relógio real, e não em `FIXED_NOW`: os
        # serviços resolvem `now` internamente (é deles a autoridade sobre o
        # tempo), então uma sessão com validade fixa no passado tornaria todo
        # cenário uma sessão expirada.
        now = datetime.now(UTC)
        self.session = Session(
            id=uuid.uuid4(),
            customer_id=self.customer.id if authenticated else None,
            authenticated=authenticated,
            created_at=now,
            expires_at=now + SESSION_TTL,
        )
        self.identity_uow.session_store[self.session.id] = self.session

        fulfillment_store = fulfillment_fakes.Store()
        self.services = AgentServices(
            sessions=SessionService(self.identity_uow, session_ttl=SESSION_TTL),
            authentication=AuthenticationService(
                self.identity_uow,
                hasher=build_hasher(),
                otp_generator=FakeOtpGenerator(),
                otp_ttl=OTP_TTL,
                otp_max_attempts=5,
                session_ttl=SESSION_TTL,
            ),
            fare=FareService(
                fares=InMemoryFareRepository(official_fares()),
                fare_rules=InMemoryFareRuleRepository([make_rule()]),
            ),
            cards=CardService(InMemoryCardRepository(stored_cards)),
            quotes=QuoteService(FakeOrdersUnitOfWork(self.store), quote_ttl=QUOTE_TTL),
            orders=OrderService(
                FakeOrdersUnitOfWork(self.store), ApprovalPolicy(), draft_ttl=DRAFT_TTL
            ),
            payments=PaymentService(FakePaymentsUnitOfWork(self.store), self.provider),
            fulfillment=FulfillmentService(
                fulfillment_fakes.FakeFulfillmentUnitOfWork(fulfillment_store)
            ),
        )

    @property
    def card(self) -> Card:
        return self.cards[0]

    def state(self) -> ConversationState:
        """Estado inicial de uma conversa sobre a sessão deste mundo."""
        return ConversationState(conversation_id=uuid.uuid4(), session_id=self.session.id)

    def expire_session(self) -> None:
        """Move a expiração da sessão para o passado, sem tocar em relógio global."""
        expired = self.identity_uow.session_store[self.session.id]
        self.identity_uow.session_store[self.session.id] = Session(
            id=expired.id,
            customer_id=expired.customer_id,
            authenticated=expired.authenticated,
            created_at=expired.created_at,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )


def blocked_card(customer_id: uuid.UUID) -> Card:
    return make_card(customer_id=customer_id, last4="7934", status=CardStatus.BLOCKED)


def other_customer_card() -> Card:
    """Cartão de outro cliente — o cenário cross-user de SPEC-002 §14."""
    return make_card(customer_id=uuid.uuid4(), last4="1257")


RECHARGE_AMOUNT = Decimal("100.00")
ABOVE_APPROVAL_THRESHOLD = Decimal("250.00")
