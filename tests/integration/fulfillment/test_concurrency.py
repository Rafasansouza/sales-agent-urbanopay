"""Concorrência real do fulfillment (SPEC-005 §7, §19; ADR-012).

Duas `AsyncSession` distintas em `asyncio.gather`, porque uma sessão nunca é
compartilhada entre tasks concorrentes (ADR-012). Só assim
`SELECT ... FOR UPDATE` e o índice único parcial são exercitados de verdade —
o dublê em memória dos testes unit não modela lock de linha.

Ordem de lock exercitada: `Order → Card → Fulfillment`.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.fulfillment.conftest import LATER, FulfillmentTestData
from urbanopay.modules.fulfillment.application.services import FulfillmentService
from urbanopay.modules.fulfillment.infrastructure.uow import (
    SqlAlchemyFulfillmentUnitOfWork,
)


def _service(session_factory: async_sessionmaker[AsyncSession]) -> FulfillmentService:
    """Serviço com UoW próprio — uma sessão por task concorrente."""
    return FulfillmentService(SqlAlchemyFulfillmentUnitOfWork(session_factory))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dois_fulfillments_concorrentes_creditam_uma_unica_vez(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """O cenário crítico da SPEC-005: nenhum crédito duplicado (§19.3).

    O lock do Order serializa as duas transações; a segunda encontra o ledger
    e devolve o resultado anterior. O índice único parcial é a última defesa.
    """
    cenario = await data.add_scenario(total=Decimal("50.00"), balance=Decimal("10.00"))

    async def tentar() -> object:
        try:
            return await _service(session_factory).fulfill_order(
                order_id=cenario.order_id, at=LATER
            )
        except Exception as exc:
            return exc

    resultados = await asyncio.gather(tentar(), tentar())

    # Exatamente um efeito, em todas as dimensões.
    assert await data.count_ledger(cenario.order_id) == 1
    assert await data.count_receipts(cenario.order_id) == 1
    assert await data.count_fulfillments(cenario.order_id) == 1
    assert await data.balance_of(cenario.card_id) == Decimal("60.00")
    assert await data.order_status(cenario.order_id) == "COMPLETED"

    sucessos = [r for r in resultados if not isinstance(r, Exception)]
    assert len(sucessos) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tres_fulfillments_concorrentes_creditam_uma_unica_vez(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Mais contenção, mesma garantia."""
    cenario = await data.add_scenario(total=Decimal("25.00"), balance=Decimal("0.00"))

    async def tentar() -> object:
        try:
            return await _service(session_factory).fulfill_order(
                order_id=cenario.order_id, at=LATER
            )
        except Exception as exc:
            return exc

    await asyncio.gather(tentar(), tentar(), tentar())

    assert await data.count_ledger(cenario.order_id) == 1
    assert await data.count_receipts(cenario.order_id) == 1
    assert await data.balance_of(cenario.card_id) == Decimal("25.00")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_distintos_do_mesmo_cartao_creditam_os_dois(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """O lock do Card serializa sem perder efeito — não é exclusão mútua.

    Dois Orders diferentes apontando para o **mesmo** cartão devem produzir
    dois créditos. É o contraponto necessário aos testes acima: a proteção
    contra duplicidade não pode custar créditos legítimos.

    ⚠️ **Teste de regressão de deadlock.** Este cenário reprovou a ordem de
    lock original (`Order → Fulfillment → Card`) com
    `psycopg.errors.DeadlockDetected`, de forma intermitente: as chaves
    estrangeiras `fulfillments.card_id` e `card_ledger_entries.card_id` fazem
    o PostgreSQL travar a linha do cartão em `FOR KEY SHARE` no INSERT, e as
    duas transações tentavam elevar esse lock compartilhado a exclusivo. A
    ordem correta é `Order → Card → Fulfillment`. Se alguém mover o lock do
    cartão para depois dos inserts, este teste volta a falhar.
    """
    import uuid

    import sqlalchemy as sa

    from urbanopay.modules.orders.infrastructure.models import OrderModel

    primeiro = await data.add_scenario(total=Decimal("30.00"), balance=Decimal("0.00"))
    segundo = await data.add_scenario(total=Decimal("20.00"), balance=Decimal("0.00"))

    # Aponta o segundo Order para o cartão do primeiro, mantendo o cliente.
    async with session_factory() as session:
        await session.execute(
            sa.update(OrderModel)
            .where(OrderModel.id == segundo.order_id)
            .values(card_id=primeiro.card_id, customer_id=primeiro.customer_id)
        )
        await session.commit()

    async def tentar(order_id: uuid.UUID) -> object:
        try:
            return await _service(session_factory).fulfill_order(order_id=order_id, at=LATER)
        except Exception as exc:
            return exc

    resultados = await asyncio.gather(tentar(primeiro.order_id), tentar(segundo.order_id))

    assert all(not isinstance(r, Exception) for r in resultados), resultados
    assert await data.count_ledger(primeiro.order_id) == 1
    assert await data.count_ledger(segundo.order_id) == 1
    # Os dois créditos somaram no mesmo cartão, sem perda por corrida.
    assert await data.balance_of(primeiro.card_id) == Decimal("50.00")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fulfillment_concorrente_com_consulta_mantem_estado_consistente(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Consulta durante o efeito nunca vê estado parcial."""
    cenario = await data.add_scenario(total=Decimal("40.00"), balance=Decimal("0.00"))
    service = _service(session_factory)

    async def aplicar() -> object:
        return await service.fulfill_order(order_id=cenario.order_id, at=LATER)

    async def consultar() -> Decimal:
        # Ou o saldo anterior, ou o final — nunca algo no meio.
        return await data.balance_of(cenario.card_id)

    resultado, saldo_durante = await asyncio.gather(aplicar(), consultar())

    assert not isinstance(resultado, Exception)
    assert saldo_durante in (Decimal("0.00"), Decimal("40.00"))
    assert await data.balance_of(cenario.card_id) == Decimal("40.00")
    assert await data.count_ledger(cenario.order_id) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_nao_pago_sob_concorrencia_produz_zero_efeito(
    data: FulfillmentTestData, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    cenario = await data.add_scenario(order_status="CONFIRMED", balance=Decimal("10.00"))

    async def tentar() -> object:
        try:
            return await _service(session_factory).fulfill_order(
                order_id=cenario.order_id, at=LATER
            )
        except Exception as exc:
            return exc

    resultados = await asyncio.gather(tentar(), tentar())

    assert all(isinstance(r, Exception) for r in resultados)
    assert await data.count_ledger(cenario.order_id) == 0
    assert await data.count_fulfillments(cenario.order_id) == 0
    assert await data.balance_of(cenario.card_id) == Decimal("10.00")
