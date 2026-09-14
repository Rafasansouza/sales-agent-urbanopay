"""Erro de domínio → comportamento conversacional (SPEC-004 §18).

O mapa associa **apenas** o `next_action`: o código semântico vem do próprio
erro (`code`), definido pela SPEC do módulo que o levantou. Redigitá-lo aqui
criaria uma segunda lista de códigos a manter coerente com as SPEC-001..005 —
exatamente o tipo de duplicação que produz divergência silenciosa.

Erro não mapeado **não vira sucesso**: o executor o converte em
`INTERNAL_ERROR` com `STOP` e log sanitizado (§20).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from urbanopay.core.idempotency import IdempotencyConflictError
from urbanopay.modules.agent.domain.results import NextAction
from urbanopay.modules.approvals.domain.errors import (
    ApprovalNotFoundError,
    ApprovalPendingError,
    ApprovalRejectedError,
    InvalidApprovalStateError,
)
from urbanopay.modules.cards.domain.errors import CardNotAccessibleError, CardNotActiveError
from urbanopay.modules.fare.domain.errors import (
    BusLineRequiredError,
    EmptyTripError,
    FareLineNotFoundError,
    FareNotAvailableError,
    FareRuleNotFoundError,
    FareServiceUnavailableError,
    InvalidFareProfileError,
    InvalidSegmentStructureError,
    InvalidTransportModeError,
    UnsupportedTripCompositionError,
)
from urbanopay.modules.fulfillment.domain.errors import (
    EffectConflictError,
    FulfillmentNotFoundError,
    OrderNotPaidError,
    ReceiptNotAvailableError,
    ReconciliationRequiredError,
    UnsupportedFulfillmentTypeError,
)
from urbanopay.modules.identity.domain.errors import (
    AuthenticationChallengeNotFoundError,
    NotAuthenticatedError,
    SessionExpiredError,
    SessionNotFoundError,
)
from urbanopay.modules.orders.domain.errors import (
    InvalidOrderStateError,
    InvalidOrderStateTransitionError,
    InvalidRechargeAmountError,
    OrderAlreadyPaidError,
    OrderExpiredError,
    OrderNotAccessibleError,
    OrderNotFoundError,
    OrderRequiresApprovalError,
    QuoteAlreadyConsumedError,
    QuoteExpiredError,
    QuoteNotAccessibleError,
    QuoteNotFoundError,
    UnsupportedOperationTypeError,
)
from urbanopay.modules.payments.domain.errors import (
    PaymentAlreadyApprovedError,
    PaymentCreationFailedError,
    PaymentNotFoundError,
    PaymentProviderError,
    PaymentProviderTimeoutError,
    PaymentStatusUnknownError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_NEXT_ACTION: Final[Mapping[type[BaseException], NextAction]] = MappingProxyType(
    {
        # --- SPEC-001: tarifa. Nenhum erro autoriza estimativa do modelo. ---
        InvalidFareProfileError: NextAction.ASK_TRIP,
        InvalidTransportModeError: NextAction.ASK_TRIP,
        InvalidSegmentStructureError: NextAction.ASK_TRIP,
        EmptyTripError: NextAction.ASK_TRIP,
        BusLineRequiredError: NextAction.ASK_TRIP,
        FareLineNotFoundError: NextAction.ASK_TRIP,
        FareNotAvailableError: NextAction.ASK_TRIP,
        FareRuleNotFoundError: NextAction.WAIT,
        UnsupportedTripCompositionError: NextAction.ASK_TRIP,
        FareServiceUnavailableError: NextAction.WAIT,
        # --- SPEC-002: identidade e cartões ---
        SessionNotFoundError: NextAction.AUTHENTICATE,
        SessionExpiredError: NextAction.AUTHENTICATE,
        NotAuthenticatedError: NextAction.AUTHENTICATE,
        AuthenticationChallengeNotFoundError: NextAction.RESTART_AUTH,
        # Cartão inacessível e cartão de terceiro respondem igual, de propósito.
        CardNotAccessibleError: NextAction.SELECT_CARD,
        CardNotActiveError: NextAction.SELECT_CARD,
        # --- SPEC-003: Quote, Order, Approval, Payment ---
        QuoteNotFoundError: NextAction.RECREATE_QUOTE,
        QuoteNotAccessibleError: NextAction.RECREATE_QUOTE,
        QuoteExpiredError: NextAction.RECREATE_QUOTE,
        QuoteAlreadyConsumedError: NextAction.REFRESH_ORDER,
        OrderNotFoundError: NextAction.STOP,
        OrderNotAccessibleError: NextAction.STOP,
        OrderAlreadyPaidError: NextAction.CHECK_FULFILLMENT,
        OrderExpiredError: NextAction.RECREATE_ORDER,
        OrderRequiresApprovalError: NextAction.AWAIT_HUMAN_APPROVAL,
        InvalidOrderStateError: NextAction.REFRESH_ORDER,
        InvalidOrderStateTransitionError: NextAction.REFRESH_ORDER,
        UnsupportedOperationTypeError: NextAction.STOP,
        InvalidRechargeAmountError: NextAction.ASK_AMOUNT,
        ApprovalPendingError: NextAction.AWAIT_HUMAN_APPROVAL,
        ApprovalRejectedError: NextAction.STOP,
        ApprovalNotFoundError: NextAction.STOP,
        InvalidApprovalStateError: NextAction.REFRESH_ORDER,
        PaymentNotFoundError: NextAction.STOP,
        PaymentAlreadyApprovedError: NextAction.CHECK_FULFILLMENT,
        # Estado externo desconhecido: nunca nova cobrança, só reconciliação.
        PaymentStatusUnknownError: NextAction.WAIT_RECONCILIATION,
        PaymentProviderTimeoutError: NextAction.WAIT_RECONCILIATION,
        PaymentProviderError: NextAction.WAIT_RECONCILIATION,
        # Recusa determinística: o Order volta a CONFIRMED e admite nova
        # tentativa comercial mais tarde (§13.2).
        PaymentCreationFailedError: NextAction.RETRY_PAYMENT_LATER,
        IdempotencyConflictError: NextAction.STOP,
        # --- SPEC-005: entrega e pós-venda ---
        OrderNotPaidError: NextAction.AWAIT_PAYMENT,
        FulfillmentNotFoundError: NextAction.WAIT,
        ReceiptNotAvailableError: NextAction.WAIT,
        # Evidência inconsistente para a automação financeira.
        ReconciliationRequiredError: NextAction.HUMAN_REVIEW,
        EffectConflictError: NextAction.HUMAN_REVIEW,
        UnsupportedFulfillmentTypeError: NextAction.STOP,
    }
)


def map_domain_error(exc: BaseException) -> tuple[str, NextAction] | None:
    """Devolve `(código semântico, próxima ação)` de um erro conhecido.

    Percorre a MRO para que uma subclasse futura de um erro já mapeado herde o
    comportamento em vez de cair silenciosamente em `INTERNAL_ERROR`.

    `None` significa desconhecido — e desconhecido nunca é tratado como
    sucesso.
    """
    for klass in type(exc).__mro__:
        action = _NEXT_ACTION.get(klass)
        if action is not None:
            code = getattr(exc, "code", None)
            if isinstance(code, str):
                return code, action
            return None
    return None
