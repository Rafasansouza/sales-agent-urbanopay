"""Catálogo fechado, visibilidade e proibições (SPEC-004 §7.1, §7.2, §7.3, §8).

Estes testes são o enforcement técnico das listas que a SPEC escreve. Uma tool
proibida que reaparecesse sob outro nome, ou uma tool de escrita que ganhasse
um argumento crítico, seria reprovada aqui — não apenas desaconselhada.
"""

from __future__ import annotations

import inspect

import pytest

from urbanopay.modules.agent.application import registry, schemas
from urbanopay.modules.agent.domain.catalog import (
    BACKEND_ONLY_TOOLS,
    TOOL_VISIBILITY,
    UNAVAILABLE_TOOLS,
    ToolCaller,
    ToolName,
    ToolVisibility,
    llm_visible_tools,
    visibility_of,
)

# SPEC-004 §7.2: a contagem é normativa, não indicativa.
EXPECTED_COUNTS = {
    ToolVisibility.LLM_VISIBLE: 9,
    ToolVisibility.GRAPH_ONLY: 5,
    ToolVisibility.SENSITIVE_INPUT: 2,
}

EXPECTED_LLM_VISIBLE = frozenset(
    {
        "calculate_trip_fare",
        "get_customer_cards",
        "get_card_details",
        "get_card_balance",
        "get_order",
        "get_approval_status",
        "get_payment_status",
        "get_fulfillment_status",
        "get_receipt",
    }
)

EXPECTED_GRAPH_ONLY = frozenset(
    {
        "get_authentication_status",
        "create_recharge_quote",
        "create_order",
        "confirm_order",
        "create_payment",
    }
)

EXPECTED_SENSITIVE_INPUT = frozenset({"start_authentication", "verify_otp"})

# Argumentos que nenhuma tool pode receber (SPEC-004 §9.1, §18; SPEC-003 §18).
FORBIDDEN_ARGUMENT_NAMES = frozenset(
    {
        "status",
        "order_status",
        "payment_status",
        "approval_status",
        "balance",
        "new_balance",
        "fare_profile",
        "official_fare_profile",
        "payment_id",
        "customer_id",
        "requires_approval",
        "idempotency_key",
        "key",
        "discount",
        "discount_amount",
        "total",
        "amount_paid",
        "approved",
        "actor",
    }
)


@pytest.mark.unit
def test_catalogo_tem_dezesseis_contratos_registrados() -> None:
    """A contagem de §7.2 é exata: 16 contratos, 9 + 5 + 2."""
    assert len(ToolName) == 16
    assert len(registry.TOOL_SPECS) == 16
    assert sum(EXPECTED_COUNTS.values()) == 16


@pytest.mark.unit
@pytest.mark.parametrize(
    ("visibility", "expected"),
    [
        (ToolVisibility.LLM_VISIBLE, EXPECTED_LLM_VISIBLE),
        (ToolVisibility.GRAPH_ONLY, EXPECTED_GRAPH_ONLY),
        (ToolVisibility.SENSITIVE_INPUT, EXPECTED_SENSITIVE_INPUT),
    ],
)
def test_distribuicao_por_visibilidade(
    visibility: ToolVisibility, expected: frozenset[str]
) -> None:
    actual = {tool.value for tool, level in TOOL_VISIBILITY.items() if level is visibility}
    assert actual == expected
    assert len(actual) == EXPECTED_COUNTS[visibility]


@pytest.mark.unit
def test_schema_do_llm_contem_apenas_llm_visible() -> None:
    """O catálogo entregue ao modelo é o subconjunto visível — e só ele."""
    names = {entry["name"] for entry in registry.llm_tool_schema()}
    assert names == EXPECTED_LLM_VISIBLE
    assert names.isdisjoint(EXPECTED_GRAPH_ONLY)
    assert names.isdisjoint(EXPECTED_SENSITIVE_INPUT)
    assert names.isdisjoint(BACKEND_ONLY_TOOLS)


@pytest.mark.unit
def test_schema_do_llm_declara_contrato_de_entrada() -> None:
    """Cada entrada do schema carrega nome, descrição e JSON Schema."""
    for entry in registry.llm_tool_schema():
        assert entry["description"]
        assert entry["input_schema"]["type"] == "object"
        # `extra="forbid"` no Pydantic: argumento não declarado é recusado.
        assert entry["input_schema"]["additionalProperties"] is False


@pytest.mark.unit
def test_llm_visible_tools_coincide_com_o_schema() -> None:
    assert {tool.value for tool in llm_visible_tools()} == EXPECTED_LLM_VISIBLE


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(BACKEND_ONLY_TOOLS))
def test_tool_backend_only_nao_e_resolvivel(name: str) -> None:
    """Nenhum nome proibido ou de backend resolve para uma tool executável."""
    assert registry.get_spec(name) is None
    assert visibility_of(name) is ToolVisibility.BACKEND_ONLY


@pytest.mark.unit
def test_denylist_cobre_as_proibicoes_das_specs() -> None:
    """As listas de SPEC-002 §11, SPEC-004 §8 e SPEC-005 §16 estão cobertas."""
    obrigatorias = {
        # SPEC-004 §8
        "set_balance",
        "set_fare",
        "set_fare_profile",
        "set_order_status",
        "set_payment_status",
        "approve_payment",
        "mark_payment_as_paid",
        "apply_discount",
        "override_rule",
        "apply_recharge",
        "issue_ticket",
        # SPEC-002 §11
        "authenticate_as",
        "change_customer",
        "change_fare_profile",
        "change_balance",
        "link_card",
        # SPEC-005 §16
        "retry_fulfillment",
        "reconcile_fulfillment",
        "set_ticket_status",
        # Comandos de backend que existem e não pertencem ao agente.
        "approve_order",
        "reject_order",
        "fulfill_order",
        "reconcile_payment",
        "process_payment_webhook",
        # H-12: o OTP nunca é revelado.
        "get_otp",
        # Capabilities genéricas.
        "execute_sql",
        "execute_shell",
        "http_request",
    }
    assert obrigatorias <= BACKEND_ONLY_TOOLS


@pytest.mark.unit
def test_denylist_e_disjunta_do_catalogo() -> None:
    """Nada pode estar registrado e proibido ao mesmo tempo."""
    assert {tool.value for tool in ToolName}.isdisjoint(BACKEND_ONLY_TOOLS)
    assert set(UNAVAILABLE_TOOLS).isdisjoint(BACKEND_ONLY_TOOLS)
    assert {tool.value for tool in ToolName}.isdisjoint(UNAVAILABLE_TOOLS)


@pytest.mark.unit
def test_tools_indisponiveis_declaram_o_bloqueio() -> None:
    """A-05 e A-06 nomeadas, sem tool fictícia (SPEC-004 §7.3)."""
    assert UNAVAILABLE_TOOLS == {
        "search_products": "A-05",
        "get_product": "A-05",
        "get_ticket": "A-05",
        "calculate_usage_cost": "A-06",
    }


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(EXPECTED_GRAPH_ONLY | EXPECTED_SENSITIVE_INPUT))
def test_llm_nao_alcanca_graph_only_nem_sensitive_input(name: str) -> None:
    spec = registry.get_spec(name)
    assert spec is not None
    assert not registry.is_callable_by(spec, ToolCaller.LLM)
    assert registry.is_callable_by(spec, ToolCaller.ORCHESTRATOR)


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(EXPECTED_LLM_VISIBLE))
def test_llm_visible_e_alcancavel_por_ambos(name: str) -> None:
    spec = registry.get_spec(name)
    assert spec is not None
    assert registry.is_callable_by(spec, ToolCaller.LLM)
    assert registry.is_callable_by(spec, ToolCaller.ORCHESTRATOR)


@pytest.mark.unit
def test_nenhuma_tool_recebe_argumento_critico() -> None:
    """Nenhum contrato de entrada aceita estado, dinheiro alheio ou key.

    É a defesa contra "argumentos arbitrários": mesmo um modelo manipulado não
    encontra onde escrever `status`, `balance` ou `idempotency_key`.
    """
    offenders: dict[str, set[str]] = {}
    for spec in registry.TOOL_SPECS.values():
        fields = set(spec.input_model.model_fields)
        found = fields & FORBIDDEN_ARGUMENT_NAMES
        if found:
            offenders[spec.name.value] = found
    assert not offenders, f"Tools com argumento critico: {offenders}"


@pytest.mark.unit
def test_apenas_a_recarga_recebe_valor_monetario() -> None:
    """O valor da recarga é a única grandeza monetária que entra pela conversa.

    E entra como **string decimal**: `float` no caminho do dinheiro é proibido
    em qualquer ponto (ADR-012).
    """
    with_amount = {
        spec.name.value
        for spec in registry.TOOL_SPECS.values()
        if "amount" in spec.input_model.model_fields
    }
    assert with_amount == {"create_recharge_quote"}
    assert schemas.CreateRechargeQuoteInput.model_fields["amount"].annotation is str


@pytest.mark.unit
def test_create_payment_nao_recebe_valor_nem_cartao() -> None:
    """SPEC-003 §10: `create_payment(order_id)`, e o backend deriva o resto."""
    assert set(schemas.CreatePaymentInput.model_fields) == {"order_id"}


@pytest.mark.unit
def test_contratos_recusam_argumento_nao_declarado() -> None:
    """`extra="forbid"`: injeção de campo é recusada, nunca ignorada."""
    for spec in registry.TOOL_SPECS.values():
        assert spec.input_model.model_config.get("extra") == "forbid"


@pytest.mark.unit
def test_exigencia_de_sessao_segue_a_matriz_de_autorizacao() -> None:
    """SPEC-004 §7.2 / SPEC-002 §9: 12 protegidas, 1 opcional, 3 anônimas.

    `calculate_trip_fare` é a **única** opcional: a simulação é pública, mas o
    perfil oficial do cartão precisa prevalecer quando existe cartão
    selecionado numa sessão autenticada.
    """
    por_exigencia: dict[registry.AuthenticationRequirement, set[str]] = {}
    for spec in registry.TOOL_SPECS.values():
        por_exigencia.setdefault(spec.authentication, set()).add(spec.name.value)

    assert por_exigencia[registry.AuthenticationRequirement.OPTIONAL] == {"calculate_trip_fare"}
    assert por_exigencia[registry.AuthenticationRequirement.NONE] == {
        "start_authentication",
        "verify_otp",
        "get_authentication_status",
    }
    assert len(por_exigencia[registry.AuthenticationRequirement.REQUIRED]) == 12
    # Nenhuma tool que toca cartão, pedido, pagamento ou entrega é anônima.
    assert por_exigencia[registry.AuthenticationRequirement.REQUIRED] == (
        EXPECTED_LLM_VISIBLE | EXPECTED_GRAPH_ONLY
    ) - {"calculate_trip_fare", "get_authentication_status"}


@pytest.mark.unit
def test_apenas_comandos_com_contexto_exigem_contexto() -> None:
    """§9.1: só `confirm_order` e `create_payment` derivam o identificador."""
    com_contexto = {
        spec.name.value
        for spec in registry.TOOL_SPECS.values()
        if spec.context_requirement is not None
    }
    assert com_contexto == {"confirm_order", "create_payment"}


@pytest.mark.unit
def test_toda_tool_registrada_tem_handler_assincrono_e_visibilidade() -> None:
    for tool in ToolName:
        spec = registry.TOOL_SPECS[tool]
        assert inspect.iscoroutinefunction(spec.handler)
        assert spec.visibility in EXPECTED_COUNTS
        assert spec.description
        assert spec.argument_error_code


@pytest.mark.unit
@pytest.mark.parametrize("name", ["", "  ", "drop_table", "calculate_trip_fare "])
def test_nome_desconhecido_nao_resolve(name: str) -> None:
    """Sem fallback, sem normalização silenciosa, sem resolução dinâmica."""
    assert registry.get_spec(name) is None
    assert visibility_of(name) is None
