"""Testes de integração da persistence foundation (ADR-012).

Validam, contra PostgreSQL 17 real: conexão assíncrona via psycopg 3, retorno
de `Decimal` para `NUMERIC`, sessão, commit, rollback, Unit of Work,
`expire_on_commit=False` e a naming convention aplicada no banco.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.conftest import PROBE_SCHEMA, FoundationProbe
from urbanopay.db.unit_of_work import SqlAlchemyUnitOfWork

# ---------------------------------------------------------------------------
# Conexão e driver
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conexao_assincrona_com_postgres_17(engine: AsyncEngine) -> None:
    """O engine psycopg async conecta e o servidor é PostgreSQL 17+."""
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1

        version_num = int((await conn.execute(text("SHOW server_version_num"))).scalar_one())
        assert version_num >= 170_000, (
            f"PostgreSQL {version_num} < 17; a infra local/CI fixa a versão 17 "
            "(infra/docker-compose.yml, ci.yml)"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_driver_devolve_decimal_para_numeric(engine: AsyncEngine) -> None:
    """`NUMERIC` chega como `Decimal` exato — nunca float (R2 do ADR-012)."""
    async with engine.connect() as conn:
        value = (await conn.execute(text("SELECT CAST('7.65' AS NUMERIC(12, 2))"))).scalar_one()

    assert type(value) is Decimal
    assert value == Decimal("7.65")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_numeric_12_2_roundtrip_preserva_decimal(
    probe_tables: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Escrita e leitura de `Numeric(12, 2, asdecimal=True)` preservam Decimal."""
    async with session_factory() as session:
        session.add(FoundationProbe(amount=Decimal("199.90"), note="roundtrip"))
        await session.commit()

    async with session_factory() as session:
        stored = (
            await session.execute(
                select(FoundationProbe.amount).where(FoundationProbe.note == "roundtrip")
            )
        ).scalar_one()

    assert type(stored) is Decimal
    assert stored == Decimal("199.90")


# ---------------------------------------------------------------------------
# Sessão, commit e rollback
# ---------------------------------------------------------------------------


async def _count_notes(session: AsyncSession, note: str) -> int:
    result = await session.execute(
        select(sa.func.count()).select_from(FoundationProbe).where(FoundationProbe.note == note)
    )
    return result.scalar_one()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_commit_persiste_para_outra_sessao(
    probe_tables: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(FoundationProbe(amount=Decimal("1.00"), note="committed"))
        await session.commit()

    async with session_factory() as session:
        assert await _count_notes(session, "committed") == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rollback_desfaz_trabalho_pendente(
    probe_tables: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(FoundationProbe(amount=Decimal("2.00"), note="rolled-back"))
        await session.flush()  # SQL emitido, transação ainda aberta
        await session.rollback()

    async with session_factory() as session:
        assert await _count_notes(session, "rolled-back") == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expire_on_commit_false_mantem_objeto_utilizavel(
    probe_tables: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Após commit e **fechamento** da sessão, o objeto continua legível.

    Com `expire_on_commit=True` o acesso a `probe.amount` após o close
    levantaria erro de instância expirada/desanexada, pois exigiria novo
    SELECT.
    """
    async with session_factory() as session:
        probe = FoundationProbe(amount=Decimal("3.30"), note="no-expire")
        session.add(probe)
        await session.commit()

    # Sessão fechada: qualquer refresh implícito falharia aqui.
    assert probe.amount == Decimal("3.30")
    assert probe.note == "no-expire"
    assert probe.id is not None


# ---------------------------------------------------------------------------
# Unit of Work
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_uow_commit_explicito_persiste(
    probe_tables: None,
    uow: SqlAlchemyUnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with uow:
        uow.session.add(FoundationProbe(amount=Decimal("10.00"), note="uow-commit"))
        await uow.commit()

    async with session_factory() as session:
        assert await _count_notes(session, "uow-commit") == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_uow_saida_sem_commit_faz_rollback(
    probe_tables: None,
    uow: SqlAlchemyUnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with uow:
        uow.session.add(FoundationProbe(amount=Decimal("11.00"), note="uow-no-commit"))
        await uow.session.flush()
        # Sem commit: a saída do contexto deve desfazer tudo.

    async with session_factory() as session:
        assert await _count_notes(session, "uow-no-commit") == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_uow_excecao_faz_rollback(
    probe_tables: None,
    uow: SqlAlchemyUnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    class BoomError(RuntimeError):
        pass

    with pytest.raises(BoomError):
        async with uow:
            uow.session.add(FoundationProbe(amount=Decimal("12.00"), note="uow-exception"))
            await uow.session.flush()
            raise BoomError

    async with session_factory() as session:
        assert await _count_notes(session, "uow-exception") == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_uow_trabalho_apos_ultimo_commit_e_descartado(
    probe_tables: None,
    uow: SqlAlchemyUnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Commit é sempre explícito: o que vier depois do último commit não persiste."""
    async with uow:
        uow.session.add(FoundationProbe(amount=Decimal("13.00"), note="uow-kept"))
        await uow.commit()
        uow.session.add(FoundationProbe(amount=Decimal("14.00"), note="uow-dropped"))
        await uow.session.flush()

    async with session_factory() as session:
        assert await _count_notes(session, "uow-kept") == 1
        assert await _count_notes(session, "uow-dropped") == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_uow_libera_sessao_na_saida(uow: SqlAlchemyUnitOfWork) -> None:
    """Fora do contexto a sessão não é acessível — o recurso foi liberado."""
    async with uow:
        _ = uow.session  # dentro do contexto, ok

    with pytest.raises(RuntimeError, match="fora de contexto"):
        _ = uow.session


# ---------------------------------------------------------------------------
# Naming convention
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_naming_convention_aplicada_no_banco(
    probe_tables: None,
    engine: AsyncEngine,
) -> None:
    """Constraints e índices ganham nomes determinísticos no PostgreSQL.

    A convenção usada pela sonda é importada de `urbanopay.db.base`, portanto
    este teste prova a convenção de produção, não uma cópia.
    """

    def _reflect(
        sync_conn: sa.Connection,
    ) -> tuple[str | None, set[str | None], set[str | None], set[str | None]]:
        inspector = sa.inspect(sync_conn)
        table = "foundation_probe"
        return (
            inspector.get_pk_constraint(table, schema=PROBE_SCHEMA)["name"],
            {uq["name"] for uq in inspector.get_unique_constraints(table, schema=PROBE_SCHEMA)},
            {ck["name"] for ck in inspector.get_check_constraints(table, schema=PROBE_SCHEMA)},
            {ix["name"] for ix in inspector.get_indexes(table, schema=PROBE_SCHEMA)},
        )

    async with engine.connect() as conn:
        pk_name, uq_names, ck_names, ix_names = await conn.run_sync(_reflect)

    assert pk_name == "pk_foundation_probe"
    assert "uq_foundation_probe_note" in uq_names
    assert "ck_foundation_probe_amount_non_negative" in ck_names
    # O padrão `ix_%(column_0_label)s` usa o label completo da coluna, que em
    # tabela com schema qualificado inclui o schema. Nas tabelas de produção
    # (schema default, ADR-012) o nome sai como `ix_<tabela>_<coluna>`.
    assert "ix_it_foundation_foundation_probe_amount" in ix_names
