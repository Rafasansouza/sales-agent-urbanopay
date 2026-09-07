"""Modelos ORM do Fare Engine (SPEC-001 §2, §8; ADR-012).

Somente mapeamento de persistência: nenhuma regra de negócio, nenhum
arredondamento. Os modelos nunca atravessam a fronteira do repositório.

Vigência: intervalo semiaberto `[valid_from, valid_until)`, com
`valid_until IS NULL` representando vigência aberta. A não-sobreposição por
chave é garantida por EXCLUDE constraint (gist + btree_gist), materializando
SPEC-001 §8 ("alteração encerra a vigência anterior") e §13 (determinismo:
no máximo uma tarifa/regra vigente por chave em qualquer instante).

`line_code` é texto livre sem limite arbitrário; a validade estrutural
(BUS exige linha não-branca, METRO não possui linha) é constraint física.
Datas em TIMESTAMPTZ; a aplicação trabalha sempre com datetimes tz-aware.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from urbanopay.db.base import Base

# Expressão de vigência compartilhada pelas EXCLUDE constraints.
_VALIDITY_RANGE = sa.text("tstzrange(valid_from, valid_until, '[)')")


class FareModel(Base):
    """Tarifa oficial persistida (SPEC-001 §2)."""

    __tablename__ = "fares"
    __table_args__ = (
        sa.CheckConstraint("mode IN ('BUS', 'METRO')", name="mode_valid"),
        sa.CheckConstraint("fare_profile IN ('INTEGRAL', 'MEIA')", name="profile_valid"),
        sa.CheckConstraint("amount >= 0", name="amount_non_negative"),
        # BUS exige linha; METRO proíbe (igualdade booleana cobre os dois lados).
        sa.CheckConstraint("(mode = 'BUS') = (line_code IS NOT NULL)", name="bus_requires_line"),
        sa.CheckConstraint(
            "line_code IS NULL OR btrim(line_code) <> ''", name="line_code_not_blank"
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from", name="validity_order"
        ),
        # No máximo uma tarifa vigente por (modo, linha, perfil) em qualquer
        # instante. COALESCE contorna NULL <> NULL, que furaria a exclusão
        # para METRO. Exige btree_gist (criada na migration de schema).
        ExcludeConstraint(
            (sa.text("COALESCE(line_code, '')"), "="),
            (sa.text("mode"), "="),
            (sa.text("fare_profile"), "="),
            (_VALIDITY_RANGE, "&&"),
            name="ex_fares_no_overlapping_validity",
            using="gist",
        ),
        sa.Index("ix_fares_lookup", "mode", "line_code", "fare_profile", "valid_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    mode: Mapped[str] = mapped_column(sa.Text())
    line_code: Mapped[str | None] = mapped_column(sa.Text())
    fare_profile: Mapped[str] = mapped_column(sa.Text())
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2, asdecimal=True))
    valid_from: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True))


class FareRuleModel(Base):
    """Regra tarifária persistida (SPEC-001 §5, §8).

    `trip_type` restrito a INTEGRATION no MVP: COMMON e SINGLE têm desconto 0%
    por definição da SPEC §5 — a invariante é estrutural, não dado. Ampliar o
    conjunto exige migration explícita, o que força a revisão documental.
    """

    __tablename__ = "fare_rules"
    __table_args__ = (
        sa.CheckConstraint("trip_type IN ('INTEGRATION')", name="trip_type_valid"),
        sa.CheckConstraint(
            "discount_percentage >= 0 AND discount_percentage <= 100",
            name="discount_within_bounds",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from", name="validity_order"
        ),
        ExcludeConstraint(
            (sa.text("trip_type"), "="),
            (_VALIDITY_RANGE, "&&"),
            name="ex_fare_rules_no_overlapping_validity",
            using="gist",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    trip_type: Mapped[str] = mapped_column(sa.Text())
    discount_percentage: Mapped[Decimal] = mapped_column(sa.Numeric(5, 2, asdecimal=True))
    valid_from: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True))
