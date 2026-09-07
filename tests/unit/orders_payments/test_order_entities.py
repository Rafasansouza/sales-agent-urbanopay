"""Entidades e validação de valor de Orders (SPEC-003 §1.1, §4, §5.1)."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.orders_payments.builders import FIXED_NOW, make_order, make_quote
from urbanopay.modules.orders.domain.entities import (
    RECHARGE_ITEM_DESCRIPTION,
    LineItem,
    validate_money_amount,
)
from urbanopay.modules.orders.domain.enums import OperationType, OrderStatus
from urbanopay.modules.orders.domain.errors import (
    InvalidRechargeAmountError,
    QuoteExpiredError,
    UnsupportedOperationTypeError,
)

# --- validação de dinheiro ----------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("valor", ["0.01", "1.00", "50.00", "199.99", "9999999999.99"])
def test_valores_validos_sao_aceitos(valor: str) -> None:
    validate_money_amount(Decimal(valor))


@pytest.mark.unit
@pytest.mark.parametrize(
    "valor",
    [
        "0",  # não positivo
        "0.00",
        "-1.00",  # negativo
        "-0.01",
        "10.001",  # três casas
        "1.999",
        "10000000000.00",  # além de Numeric(12, 2)
    ],
)
def test_valores_invalidos_sao_recusados(valor: str) -> None:
    with pytest.raises(InvalidRechargeAmountError):
        validate_money_amount(Decimal(valor))


@pytest.mark.unit
@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_valores_nao_finitos_sao_recusados(valor: str) -> None:
    """NaN e infinito não têm expoente inteiro: recusados antes de qualquer conta."""
    with pytest.raises(InvalidRechargeAmountError):
        validate_money_amount(Decimal(valor))


@pytest.mark.unit
def test_validacao_nunca_arredonda() -> None:
    """Valor com três casas é **recusado**, nunca corrigido em silêncio."""
    with pytest.raises(InvalidRechargeAmountError):
        LineItem.for_recharge(Decimal("10.005"))


@pytest.mark.unit
def test_mensagem_de_erro_nao_repete_o_valor() -> None:
    """Erro de valor não vaza o montante para log nem para resposta."""
    with pytest.raises(InvalidRechargeAmountError) as exc:
        validate_money_amount(Decimal("-1234.56"))
    assert "1234" not in str(exc.value)


# --- LineItem -----------------------------------------------------------


@pytest.mark.unit
def test_linha_de_recarga_e_coerente() -> None:
    item = LineItem.for_recharge(Decimal("75.50"))

    assert item.description == RECHARGE_ITEM_DESCRIPTION
    assert item.quantity == 1
    assert item.unit_amount == Decimal("75.50")
    assert item.total_amount == Decimal("75.50")
    # Espelha `ck_order_items_total_matches_quantity`.
    assert item.total_amount == item.unit_amount * item.quantity


# --- escopo do MVP (§1.1) -----------------------------------------------


@pytest.mark.unit
def test_recharge_e_suportado() -> None:
    OperationType.RECHARGE.require_supported()


@pytest.mark.unit
def test_ticket_purchase_e_recusado_explicitamente() -> None:
    """Recusa explícita, nunca comportamento fictício para produto sem SPEC."""
    with pytest.raises(UnsupportedOperationTypeError):
        OperationType.TICKET_PURCHASE.require_supported()


# --- Quote (§4) ---------------------------------------------------------


@pytest.mark.unit
def test_quote_valida_dentro_da_janela() -> None:
    quote = make_quote()
    assert quote.is_expired(FIXED_NOW) is False
    quote.ensure_usable(FIXED_NOW)


@pytest.mark.unit
def test_quote_expira_no_instante_do_vencimento() -> None:
    """Fronteira inclusiva: `at >= expires_at` já é expirada."""
    quote = make_quote(expires_at=FIXED_NOW)

    assert quote.is_expired(FIXED_NOW) is True
    with pytest.raises(QuoteExpiredError) as exc:
        quote.ensure_usable(FIXED_NOW)
    assert exc.value.code == "QUOTE_EXPIRED"


@pytest.mark.unit
def test_quote_nao_possui_status() -> None:
    """A validade é derivada de `expires_at`; não existe coluna de status."""
    assert not hasattr(make_quote(), "status")


@pytest.mark.unit
def test_recarga_nao_tem_desconto() -> None:
    quote = make_quote(total=Decimal("250.00"))

    assert quote.discount_amount == Decimal("0.00")
    assert quote.subtotal == quote.total
    assert quote.total == quote.subtotal - quote.discount_amount


# --- Order (§5.1) -------------------------------------------------------


@pytest.mark.unit
def test_draft_expira_pelo_ttl() -> None:
    order = make_order(status=OrderStatus.DRAFT, expires_at=FIXED_NOW + timedelta(minutes=10))

    assert order.is_draft_expired(FIXED_NOW) is False
    assert order.is_draft_expired(FIXED_NOW + timedelta(minutes=10)) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.REQUIRES_APPROVAL,
        OrderStatus.CONFIRMED,
        OrderStatus.PAYMENT_PENDING,
        OrderStatus.PAID,
    ],
)
def test_ttl_nao_se_aplica_depois_da_confirmacao(status: OrderStatus) -> None:
    """Após confirmar, o Order pode aguardar o tempo que precisar (§5.1)."""
    order = make_order(status=status, expires_at=FIXED_NOW)
    assert order.is_draft_expired(FIXED_NOW + timedelta(days=365)) is False


@pytest.mark.unit
def test_order_e_imutavel() -> None:
    """Nenhuma camada altera `status` por atribuição direta.

    `setattr` com nome em string, em vez de `order.status = ...`, para que a
    verificação seja de comportamento em runtime sem precisar silenciar o
    type checker.
    """
    order = make_order()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(order, "status", OrderStatus.PAID)  # noqa: B010
