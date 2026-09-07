"""Cria as tabelas do Fare Engine: fares e fare_rules (SPEC-001).

Revision ID: fare0001
Revises:
Create Date: 2026-09-07

Primeira migration funcional do projeto. Escrita à mão (não é autogenerate):
EXCLUDE constraints e as invariantes específicas do PostgreSQL exigem revisão
explícita (ADR-012).

Decisões desta revision:

- `CREATE EXTENSION IF NOT EXISTS btree_gist`: exigida pelas EXCLUDE
  constraints com igualdade em colunas de texto. O downgrade NÃO remove a
  extensão — ela é recurso compartilhado do banco (o init local também a cria).
- Vigência como intervalo semiaberto `[valid_from, valid_until)`, com
  `valid_until IS NULL` representando vigência aberta.
- EXCLUDE garante no máximo uma tarifa vigente por (modo, linha, perfil) e uma
  regra vigente por classificação, em qualquer instante — materialização
  física de SPEC-001 §8 e §13.
- `line_code` é texto livre (sem limite arbitrário); BUS exige linha não
  branca e METRO não possui linha, ambos por constraint.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "fare0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Exigida pelas EXCLUDE constraints (igualdade gist em texto). Idempotente;
    # o PostgreSQL da CI não executa o init SQL local, então a migration é o
    # ponto canônico de criação.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "fares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("line_code", sa.Text(), nullable=True),
        sa.Column("fare_profile", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("valid_from", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("valid_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fares")),
        sa.CheckConstraint("mode IN ('BUS', 'METRO')", name=op.f("ck_fares_mode_valid")),
        sa.CheckConstraint(
            "fare_profile IN ('INTEGRAL', 'MEIA')", name=op.f("ck_fares_profile_valid")
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_fares_amount_non_negative")),
        sa.CheckConstraint(
            "(mode = 'BUS') = (line_code IS NOT NULL)", name=op.f("ck_fares_bus_requires_line")
        ),
        sa.CheckConstraint(
            "line_code IS NULL OR btrim(line_code) <> ''",
            name=op.f("ck_fares_line_code_not_blank"),
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name=op.f("ck_fares_validity_order"),
        ),
    )
    op.create_index(
        op.f("ix_fares_lookup"), "fares", ["mode", "line_code", "fare_profile", "valid_from"]
    )
    op.execute(
        "ALTER TABLE fares ADD CONSTRAINT ex_fares_no_overlapping_validity "
        "EXCLUDE USING gist ("
        "(COALESCE(line_code, '')) WITH =, "
        "mode WITH =, "
        "fare_profile WITH =, "
        "tstzrange(valid_from, valid_until, '[)') WITH &&)"
    )

    op.create_table(
        "fare_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trip_type", sa.Text(), nullable=False),
        sa.Column("discount_percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("valid_from", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("valid_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fare_rules")),
        # Restrito a INTEGRATION no MVP: COMMON/SINGLE têm 0% por definição da
        # SPEC §5; ampliar exige migration explícita.
        sa.CheckConstraint(
            "trip_type IN ('INTEGRATION')", name=op.f("ck_fare_rules_trip_type_valid")
        ),
        sa.CheckConstraint(
            "discount_percentage >= 0 AND discount_percentage <= 100",
            name=op.f("ck_fare_rules_discount_within_bounds"),
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name=op.f("ck_fare_rules_validity_order"),
        ),
    )
    op.execute(
        "ALTER TABLE fare_rules ADD CONSTRAINT ex_fare_rules_no_overlapping_validity "
        "EXCLUDE USING gist ("
        "trip_type WITH =, "
        "tstzrange(valid_from, valid_until, '[)') WITH &&)"
    )


def downgrade() -> None:
    # Constraints e índices caem junto com as tabelas. A extensão btree_gist
    # permanece: recurso compartilhado, possivelmente em uso por outros
    # objetos e também criada pelo init SQL do ambiente local.
    op.drop_table("fare_rules")
    op.drop_table("fares")
