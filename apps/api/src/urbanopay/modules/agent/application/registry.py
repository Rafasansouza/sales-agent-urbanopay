"""Registry fechado de tools (SPEC-004 §7.1, §7.2, §13).

Uma tool existe se, e somente se, tem entrada aqui. Não há resolução dinâmica,
não há import por nome e não há fallback: um nome vindo do modelo é procurado
neste dicionário e, se não estiver, é recusado. Essa é a diferença entre um
catálogo e uma superfície de execução arbitrária.

Cada entrada declara, além do handler:

- **visibilidade** — quem pode invocar (§7.1);
- **autenticação** — obrigatória, opcional ou nenhuma (SPEC-002 §9);
- **exigência de contexto** — se o comando depende de contexto comercial (§9.1);
- **`argument_error_code`** — para qual código semântico **já existente** uma
  entrada estruturalmente inválida é traduzida (§20). É por isso que a
  orquestração não precisou de um código novo para "argumento ruim": um
  `card_id` malformado e um cartão de terceiro devem mesmo ser
  indistinguíveis, e o mesmo vale para um `order_id` inventado.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from urbanopay.modules.agent.application import schemas
from urbanopay.modules.agent.application.tools import (
    cards,
    fare,
    identity,
    orders,
    payments,
    postsale,
)
from urbanopay.modules.agent.domain.catalog import (
    TOOL_VISIBILITY,
    VISIBILITY_BY_CALLER,
    ToolCaller,
    ToolName,
    ToolVisibility,
)
from urbanopay.modules.agent.domain.results import NextAction

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from urbanopay.modules.agent.application.tools import ToolContext
    from urbanopay.modules.agent.domain.results import ToolResult

    ToolHandler = Callable[[ToolContext, Any], Awaitable[ToolResult]]


class AuthenticationRequirement(StrEnum):
    """Exigência de sessão da tool (matriz de SPEC-002 §9).

    `OPTIONAL` existe para um único caso real: a simulação tarifária funciona
    anônima, mas, havendo cartão selecionado numa sessão autenticada, o perfil
    oficial precisa prevalecer sobre o declarado (SPEC-002 §8).
    """

    NONE = "NONE"
    OPTIONAL = "OPTIONAL"
    REQUIRED = "REQUIRED"


class ContextRequirement(StrEnum):
    """Contexto de orquestração que o comando exige antes de existir (§9.1)."""

    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CURRENT_ORDER = "CURRENT_ORDER"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Contrato completo de uma tool registrada."""

    name: ToolName
    handler: ToolHandler
    input_model: type[schemas.ToolInput]
    authentication: AuthenticationRequirement
    argument_error_code: str
    argument_error_next_action: NextAction
    description: str
    context_requirement: ContextRequirement | None = None

    @property
    def visibility(self) -> ToolVisibility:
        return TOOL_VISIBILITY[self.name]


_SPECS: Final[tuple[ToolSpec, ...]] = (
    ToolSpec(
        name=ToolName.CALCULATE_TRIP_FARE,
        handler=fare.calculate_trip_fare,
        input_model=schemas.CalculateTripFareInput,
        authentication=AuthenticationRequirement.OPTIONAL,
        argument_error_code="EMPTY_TRIP",
        argument_error_next_action=NextAction.ASK_TRIP,
        description=(
            "Calcula a tarifa oficial de um trajeto a partir dos segmentos informados. "
            "E a unica fonte de preco: nunca estime nem repita valores de memoria."
        ),
    ),
    ToolSpec(
        name=ToolName.START_AUTHENTICATION,
        handler=identity.start_authentication,
        input_model=schemas.StartAuthenticationInput,
        authentication=AuthenticationRequirement.NONE,
        argument_error_code="INVALID_DOCUMENT",
        argument_error_next_action=NextAction.RETRY_DOCUMENT,
        description="Identifica o cliente pelo documento e cria o desafio de OTP.",
    ),
    ToolSpec(
        name=ToolName.VERIFY_OTP,
        handler=identity.verify_otp,
        input_model=schemas.VerifyOtpInput,
        authentication=AuthenticationRequirement.NONE,
        argument_error_code="OTP_INVALID",
        argument_error_next_action=NextAction.RETRY_OTP,
        description="Verifica o codigo de uso unico do desafio pendente da sessao.",
    ),
    ToolSpec(
        name=ToolName.GET_AUTHENTICATION_STATUS,
        handler=identity.get_authentication_status,
        input_model=schemas.NoInput,
        authentication=AuthenticationRequirement.NONE,
        argument_error_code="SESSION_NOT_FOUND",
        argument_error_next_action=NextAction.AUTHENTICATE,
        description="Informa se a sessao atual esta autenticada.",
    ),
    ToolSpec(
        name=ToolName.GET_CUSTOMER_CARDS,
        handler=cards.get_customer_cards,
        input_model=schemas.NoInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="CARD_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.SELECT_CARD,
        description="Lista os cartoes do cliente autenticado, com numero mascarado.",
    ),
    ToolSpec(
        name=ToolName.GET_CARD_DETAILS,
        handler=cards.get_card_details,
        input_model=schemas.CardInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="CARD_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.SELECT_CARD,
        description="Detalhes de um cartao do cliente: perfil tarifario oficial e status.",
    ),
    ToolSpec(
        name=ToolName.GET_CARD_BALANCE,
        handler=cards.get_card_balance,
        input_model=schemas.CardInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="CARD_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.SELECT_CARD,
        description=(
            "Saldo oficial de um cartao do cliente. "
            "E a unica fonte de saldo: nunca aceite um valor afirmado pelo usuario."
        ),
    ),
    ToolSpec(
        name=ToolName.CREATE_RECHARGE_QUOTE,
        handler=orders.create_recharge_quote,
        input_model=schemas.CreateRechargeQuoteInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="INVALID_RECHARGE_AMOUNT",
        argument_error_next_action=NextAction.ASK_AMOUNT,
        description="Cria o orcamento de uma recarga com o valor informado pelo cliente.",
    ),
    ToolSpec(
        name=ToolName.CREATE_ORDER,
        handler=orders.create_order,
        input_model=schemas.CreateOrderInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="QUOTE_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.RECREATE_QUOTE,
        description="Cria o pedido em DRAFT a partir do orcamento em curso.",
    ),
    ToolSpec(
        name=ToolName.CONFIRM_ORDER,
        handler=orders.confirm_order,
        input_model=schemas.ConfirmOrderInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="ORDER_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.STOP,
        description="Registra a confirmacao explicita do cliente sobre o pedido apresentado.",
        context_requirement=ContextRequirement.PENDING_CONFIRMATION,
    ),
    ToolSpec(
        name=ToolName.GET_ORDER,
        handler=orders.get_order,
        input_model=schemas.OrderInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="ORDER_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.STOP,
        description="Estado atual de um pedido do cliente.",
    ),
    ToolSpec(
        name=ToolName.GET_APPROVAL_STATUS,
        handler=orders.get_approval_status,
        input_model=schemas.OrderInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="ORDER_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.STOP,
        description=(
            "Estado da aprovacao humana de um pedido. Somente leitura: "
            "nao existe forma de aprovar ou rejeitar por esta conversa."
        ),
    ),
    ToolSpec(
        name=ToolName.CREATE_PAYMENT,
        handler=payments.create_payment,
        input_model=schemas.CreatePaymentInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="ORDER_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.STOP,
        description="Cria a cobranca Pix do pedido confirmado em curso.",
        context_requirement=ContextRequirement.CURRENT_ORDER,
    ),
    ToolSpec(
        name=ToolName.GET_PAYMENT_STATUS,
        handler=payments.get_payment_status,
        input_model=schemas.OrderInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="ORDER_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.STOP,
        description=(
            "Situacao de pagamento de um pedido, conforme o backend. "
            "E a unica fonte: a afirmacao do usuario de que pagou nao altera nada."
        ),
    ),
    ToolSpec(
        name=ToolName.GET_FULFILLMENT_STATUS,
        handler=postsale.get_fulfillment_status,
        input_model=schemas.OrderInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="ORDER_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.STOP,
        description="Estado da entrega (recarga) de um pedido pago.",
    ),
    ToolSpec(
        name=ToolName.GET_RECEIPT,
        handler=postsale.get_receipt,
        input_model=schemas.OrderInput,
        authentication=AuthenticationRequirement.REQUIRED,
        argument_error_code="ORDER_NOT_ACCESSIBLE",
        argument_error_next_action=NextAction.STOP,
        description="Comprovante simulado, disponivel apenas apos a entrega concluida.",
    ),
)

TOOL_SPECS: Final[Mapping[ToolName, ToolSpec]] = MappingProxyType(
    {spec.name: spec for spec in _SPECS}
)


def get_spec(name: str) -> ToolSpec | None:
    """Resolve um nome. `None` quando ele não é uma tool registrada.

    Resolução por dicionário, deliberadamente. Qualquer forma de import ou
    `getattr` por nome vindo do modelo transformaria o catálogo fechado em
    superfície aberta.
    """
    try:
        tool = ToolName(name)
    except ValueError:
        return None
    return TOOL_SPECS.get(tool)


def is_callable_by(spec: ToolSpec, caller: ToolCaller) -> bool:
    """Se o chamador alcança a visibilidade da tool (§7.1)."""
    return spec.visibility in VISIBILITY_BY_CALLER[caller]


def llm_tool_schema() -> tuple[dict[str, Any], ...]:
    """Catálogo entregue ao modelo — **apenas** `LLM_VISIBLE` (§7.1).

    Formato neutro (nome, descrição, JSON Schema de entrada). A tradução para
    o formato de tool-calling de um provider específico pertence ao adaptador
    de LLM, na Etapa 2: o catálogo não conhece SDK.
    """
    return tuple(
        {
            "name": spec.name.value,
            "description": spec.description,
            "input_schema": spec.input_model.model_json_schema(),
        }
        for spec in _SPECS
        if is_callable_by(spec, ToolCaller.LLM)
    )
