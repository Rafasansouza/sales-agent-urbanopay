"""Entidades do domínio de Orders (SPEC-003 §4, §5, §5.1).

Domínio puro: nenhum import de SQLAlchemy, de FastAPI ou de outro módulo de
domínio (verificado por teste de arquitetura).

Dinheiro é sempre `Decimal` — nunca `float`, em nenhum ponto do caminho.
Neste módulo **não existe arredondamento monetário**: em `RECHARGE`
(§1.1) o valor é escolhido pelo cliente, `subtotal == total` e
`discount_amount == 0`, portanto não há aritmética a arredondar. O único ponto
de `ROUND_HALF_UP` do sistema segue sendo o Fare Engine (SPEC-001 §7). Aqui a
escala é **validada**, não corrigida: um valor com mais de duas casas é
recusado, jamais arredondado em silêncio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from urbanopay.modules.orders.domain.enums import (
    CancellationReason,
    OperationType,
    OrderStatus,
)
from urbanopay.modules.orders.domain.errors import (
    InvalidRechargeAmountError,
    OrderExpiredError,
    QuoteExpiredError,
)

if TYPE_CHECKING:
    from uuid import UUID

# Descrição da linha única de uma recarga (§1.1: produto "Recarga Livre").
RECHARGE_ITEM_DESCRIPTION = "Recarga Livre"

_MAX_MONEY_DECIMAL_PLACES = 2
# Limite técnico derivado de `Numeric(12, 2)` (ADR-012), não regra de negócio:
# a coluna comporta até 9.999.999.999,99. Recusar antes de persistir evita que
# um estouro de precisão apareça como erro de infraestrutura.
_MAX_PERSISTABLE_AMOUNT = Decimal("9999999999.99")


def validate_money_amount(amount: Decimal) -> None:
    """Valida um valor monetário de entrada (positivo, 2 casas, persistível).

    Nunca arredonda e nunca repete o valor recebido na mensagem de erro.
    """
    if not amount.is_finite():
        raise InvalidRechargeAmountError
    if amount <= 0:
        raise InvalidRechargeAmountError
    # `exponent` é `int` em todo Decimal finito, mas assume `'n'`, `'N'` ou
    # `'F'` em NaN e infinito. O `isinstance` mantém a verificação garantida
    # por tipo, em vez de depender da checagem anterior.
    exponent = amount.as_tuple().exponent
    if not isinstance(exponent, int) or -exponent > _MAX_MONEY_DECIMAL_PLACES:
        raise InvalidRechargeAmountError
    if amount > _MAX_PERSISTABLE_AMOUNT:
        raise InvalidRechargeAmountError


@dataclass(frozen=True, slots=True)
class LineItem:
    """Item de linha congelado (SPEC-003 §5: o Order congela produto e valor).

    Snapshot mínimo, aprovado no plano: **sem chave estrangeira para catálogo**
    e sem `product_code` arbitrário — em `RECHARGE` o `operation_type` já
    identifica a operação, e catálogo de produtos não possui especificação
    (A-05). Persistido como `quote_items` / `order_items`; a entidade
    `OrderItem` da §3 é a materialização deste value object.
    """

    description: str
    quantity: int
    unit_amount: Decimal
    total_amount: Decimal

    @classmethod
    def for_recharge(cls, amount: Decimal) -> LineItem:
        """Linha única de uma recarga de valor livre."""
        validate_money_amount(amount)
        return cls(
            description=RECHARGE_ITEM_DESCRIPTION,
            quantity=1,
            unit_amount=amount,
            total_amount=amount,
        )


@dataclass(frozen=True, slots=True)
class Quote:
    """Orçamento — snapshot que não reserva dinheiro (SPEC-003 §4).

    **Não possui coluna de status**: a validade é derivada de `expires_at`, e o
    consumo é o fato relacional de existir um Order que a referencia.

    `fare_profile` é `str` por ser **snapshot de auditoria** do perfil oficial
    vigente (§1.1), não insumo de cálculo: tipá-lo com o enum do módulo
    `cards` criaria dependência entre domínios sem ganho algum.
    """

    id: UUID
    customer_id: UUID
    card_id: UUID
    operation_type: OperationType
    fare_profile: str
    items: tuple[LineItem, ...]
    subtotal: Decimal
    discount_amount: Decimal
    total: Decimal
    currency: str
    expires_at: datetime
    created_at: datetime

    def is_expired(self, at: datetime) -> bool:
        """Validade derivada exclusivamente de `expires_at` (§4)."""
        return at >= self.expires_at

    def ensure_usable(self, at: datetime) -> None:
        """Recusa Quote expirada com `QUOTE_EXPIRED` (§4)."""
        if self.is_expired(at):
            raise QuoteExpiredError


@dataclass(frozen=True, slots=True)
class Order:
    """Pedido — congela produto, quantidade, tarifa, perfil, desconto e total.

    Imutável como dataclass: as transições vivem em `state_machine.py` e
    devolvem uma nova instância. Isso torna impossível mutar `status` por
    atribuição direta em qualquer camada.

    `requires_approval` é determinado na criação pela `ApprovalPolicy` e
    congelado junto com os valores (§5). Recalcular depois permitiria contornar
    a aprovação alterando o total.
    """

    id: UUID
    customer_id: UUID
    card_id: UUID
    quote_id: UUID
    operation_type: OperationType
    status: OrderStatus
    items: tuple[LineItem, ...]
    subtotal: Decimal
    discount_amount: Decimal
    total: Decimal
    currency: str
    requires_approval: bool
    expires_at: datetime
    cancellation_reason: CancellationReason | None
    created_at: datetime
    updated_at: datetime

    def is_draft_expired(self, at: datetime) -> bool:
        """TTL se aplica **somente enquanto `DRAFT`** (§5.1)."""
        return self.status is OrderStatus.DRAFT and at >= self.expires_at

    def ensure_not_expired(self, at: datetime) -> None:
        """Recusa confirmação de `DRAFT` expirado com `ORDER_EXPIRED` (§5.1)."""
        if self.is_draft_expired(at):
            raise OrderExpiredError
