"""Catálogo de tools: nomes, visibilidade e proibições (SPEC-004 §7).

Três conjuntos, deliberadamente separados, porque respondem a perguntas
diferentes:

- **`ToolName`** — os 16 contratos que existem e podem ser executados;
- **`UNAVAILABLE_TOOLS`** — nomes que a §7 declara e que **não têm backend**,
  bloqueados por questão aberta. Recusar nomeando o bloqueio é honesto;
  responder com comportamento fictício não é;
- **`BACKEND_ONLY_TOOLS`** — nomes que a camada conversacional jamais alcança,
  ou porque são comandos de backend (existem, e não são dela), ou porque são
  proibidos por SPEC sob qualquer nome.

O ponto central de SPEC-004 §7.1: **estar registrado não é estar visível.** O
schema entregue ao modelo contém exclusivamente `LLM_VISIBLE`. A visibilidade
é declarada aqui, uma única vez, e é dela que o registry e os testes derivam —
não existe segunda lista a manter coerente.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping


class ToolName(StrEnum):
    """Os 16 contratos registrados (SPEC-004 §7.2).

    `create_quote` da §7 materializa-se como `create_recharge_quote`:
    `RECHARGE` é o único `operation_type` do MVP (SPEC-003 §1.1), e um nome
    genérico prometeria um contrato que não existe.
    """

    CALCULATE_TRIP_FARE = "calculate_trip_fare"
    START_AUTHENTICATION = "start_authentication"
    VERIFY_OTP = "verify_otp"
    GET_AUTHENTICATION_STATUS = "get_authentication_status"
    GET_CUSTOMER_CARDS = "get_customer_cards"
    GET_CARD_DETAILS = "get_card_details"
    GET_CARD_BALANCE = "get_card_balance"
    CREATE_RECHARGE_QUOTE = "create_recharge_quote"
    CREATE_ORDER = "create_order"
    CONFIRM_ORDER = "confirm_order"
    GET_ORDER = "get_order"
    GET_APPROVAL_STATUS = "get_approval_status"
    CREATE_PAYMENT = "create_payment"
    GET_PAYMENT_STATUS = "get_payment_status"
    GET_FULFILLMENT_STATUS = "get_fulfillment_status"
    GET_RECEIPT = "get_receipt"


class ToolVisibility(StrEnum):
    """Quem pode invocar uma tool (SPEC-004 §7.1)."""

    LLM_VISIBLE = "LLM_VISIBLE"
    GRAPH_ONLY = "GRAPH_ONLY"
    SENSITIVE_INPUT = "SENSITIVE_INPUT"
    BACKEND_ONLY = "BACKEND_ONLY"


class ToolCaller(StrEnum):
    """Origem da invocação.

    `LLM` é o modelo escolhendo uma tool. `ORCHESTRATOR` é código
    determinístico — os nodes do grafo (Etapa 2) e o handler de entrada
    sensível (§13.1). Nenhum dos dois alcança `BACKEND_ONLY`.
    """

    LLM = "LLM"
    ORCHESTRATOR = "ORCHESTRATOR"


TOOL_VISIBILITY: Final[Mapping[ToolName, ToolVisibility]] = MappingProxyType(
    {
        # --- LLM_VISIBLE (9) — consultas que o modelo formula e explica ---
        ToolName.CALCULATE_TRIP_FARE: ToolVisibility.LLM_VISIBLE,
        ToolName.GET_CUSTOMER_CARDS: ToolVisibility.LLM_VISIBLE,
        ToolName.GET_CARD_DETAILS: ToolVisibility.LLM_VISIBLE,
        ToolName.GET_CARD_BALANCE: ToolVisibility.LLM_VISIBLE,
        ToolName.GET_ORDER: ToolVisibility.LLM_VISIBLE,
        ToolName.GET_APPROVAL_STATUS: ToolVisibility.LLM_VISIBLE,
        ToolName.GET_PAYMENT_STATUS: ToolVisibility.LLM_VISIBLE,
        ToolName.GET_FULFILLMENT_STATUS: ToolVisibility.LLM_VISIBLE,
        ToolName.GET_RECEIPT: ToolVisibility.LLM_VISIBLE,
        # --- GRAPH_ONLY (5) — decisão determinística, não conversacional ---
        # `get_authentication_status` entra aqui porque quem decide parar a
        # jornada para autenticar é código (SPEC-002 §9); o resultado é um
        # booleano de sessão, que o modelo não precisa formular.
        ToolName.GET_AUTHENTICATION_STATUS: ToolVisibility.GRAPH_ONLY,
        ToolName.CREATE_RECHARGE_QUOTE: ToolVisibility.GRAPH_ONLY,
        ToolName.CREATE_ORDER: ToolVisibility.GRAPH_ONLY,
        ToolName.CONFIRM_ORDER: ToolVisibility.GRAPH_ONLY,
        ToolName.CREATE_PAYMENT: ToolVisibility.GRAPH_ONLY,
        # --- SENSITIVE_INPUT (2) — recebem CPF/OTP (§13.1) ---
        ToolName.START_AUTHENTICATION: ToolVisibility.SENSITIVE_INPUT,
        ToolName.VERIFY_OTP: ToolVisibility.SENSITIVE_INPUT,
    }
)

VISIBILITY_BY_CALLER: Final[Mapping[ToolCaller, frozenset[ToolVisibility]]] = MappingProxyType(
    {
        ToolCaller.LLM: frozenset({ToolVisibility.LLM_VISIBLE}),
        ToolCaller.ORCHESTRATOR: frozenset(
            {
                ToolVisibility.LLM_VISIBLE,
                ToolVisibility.GRAPH_ONLY,
                ToolVisibility.SENSITIVE_INPUT,
            }
        ),
    }
)

UNAVAILABLE_TOOLS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "search_products": "A-05",
        "get_product": "A-05",
        "get_ticket": "A-05",
        "calculate_usage_cost": "A-06",
    }
)
"""Declaradas em SPEC-004 §7 e sem backend possível (§7.3).

Resolvem para `TOOL_UNAVAILABLE` nomeando o bloqueio. Consequências:
`TICKET_PURCHASE` não é jornada, e o agente não recomenda valor de recarga.
"""

_BACKEND_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        # Existem no backend e não pertencem à camada conversacional.
        "approve_order",  # SPEC-003 §7 — decisão humana (A-07)
        "reject_order",  # SPEC-003 §7
        "expire_draft",  # SPEC-003 §5.1 — rotina operacional
        "process_payment_webhook",  # ADR-002 — nunca passa pelo grafo
        "reconcile_payment",  # SPEC-003 §13.1 — consulta ativa ao provider
        "fulfill_order",  # SPEC-005 §10.1 — disparo é da composição
        "build_consistency_report",  # SPEC-005 §20.1 — recuperação
    }
)

_FORBIDDEN_TOOLS: Final[frozenset[str]] = frozenset(
    {
        # Capabilities genéricas (PRD §13, SPEC-004 §8).
        "execute_sql",
        "execute_shell",
        "http_request",
        # SPEC-004 §8.
        "set_balance",
        "set_fare",
        "set_fare_profile",
        "set_order_status",
        "set_payment_status",
        "approve_payment",
        "mark_payment_as_paid",
        "mark_order_as_paid",
        "apply_discount",
        "override_rule",
        "apply_recharge",
        "issue_ticket",
        # SPEC-005 §16.
        "retry_fulfillment",
        "reconcile_fulfillment",
        "set_ticket_status",
        # SPEC-002 §11.
        "authenticate_as",
        "change_customer",
        "change_fare_profile",
        "change_balance",
        "link_card",
        # H-12: o OTP nunca é revelado, sob nenhuma superfície.
        "get_otp",
    }
)

BACKEND_ONLY_TOOLS: Final[frozenset[str]] = _BACKEND_COMMANDS | _FORBIDDEN_TOOLS
"""Nomes que a camada conversacional jamais alcança.

Não são registrados: qualquer resolução produz `TOOL_NOT_AUTHORIZED`. A lista
existe para tornar a proibição **executável e testável**, em vez de apenas
escrita — um nome que reaparecesse como tool seria reprovado por teste.
"""


def visibility_of(name: str) -> ToolVisibility | None:
    """Visibilidade declarada de um nome, ou `None` se ele é desconhecido.

    `BACKEND_ONLY` é devolvido para os nomes da denylist justamente para que a
    recusa seja explicável: eles não são "desconhecidos", são proibidos.
    """
    if name in BACKEND_ONLY_TOOLS:
        return ToolVisibility.BACKEND_ONLY
    try:
        tool = ToolName(name)
    except ValueError:
        return None
    return TOOL_VISIBILITY[tool]


def llm_visible_tools() -> tuple[ToolName, ...]:
    """Os nomes que podem compor o schema entregue ao modelo (§7.1)."""
    return tuple(tool for tool in ToolName if TOOL_VISIBILITY[tool] is ToolVisibility.LLM_VISIBLE)
