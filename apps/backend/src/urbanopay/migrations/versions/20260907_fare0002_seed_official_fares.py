"""Carrega as tarifas oficiais iniciais do MVP e a regra de integração.

Revision ID: fare0002
Revises: fare0001
Create Date: 2026-09-07

Migration de DADOS, separada da de schema por decisão aprovada. Este é o
pequeno conjunto de referência obrigatório do MVP (SPEC-001 §2: "os valores
devem existir como dados persistidos") — 12 tarifas (5 linhas de ônibus × 2
perfis + metrô × 2 perfis) e 1 regra de INTEGRATION com 15%.

Os registros são DERIVADOS da tabela aceita de SPEC-001 §2, não contados à
mão; um teste de integração valida que todas as tarifas esperadas existem.

Decisões desta revision:

- `valid_from = 2026-01-01T00:00:00Z` é uma **decisão fictícia do MVP,
  explicitamente aprovada** — não é regra inferida da SPEC. Consultas
  anteriores a essa data resultam em `FARE_NOT_AVAILABLE`, por definição.
- `valid_until = NULL`: vigência aberta.
- IDs determinísticos via UUIDv5 sobre chave semântica: a migration é
  reprodutível e o downgrade remove exatamente o que o upgrade inseriu.
- Esta migration NÃO estabelece o Alembic como fluxo padrão de alteração
  tarifária: mudanças operacionais futuras terão fluxo administrativo próprio,
  preservando histórico conforme SPEC-001 §8.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "fare0002"
down_revision: str | None = "fare0001"
branch_labels: str | None = None
depends_on: str | None = None

# Vigência inicial fictícia do MVP — decisão aprovada, não regra da SPEC.
INITIAL_VALIDITY_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

# Tabela aceita de SPEC-001 §2: linha -> (INTEGRAL, MEIA).
BUS_FARES: dict[str, tuple[Decimal, Decimal]] = {
    "101": (Decimal("6.00"), Decimal("3.00")),
    "202": (Decimal("7.00"), Decimal("3.50")),
    "303": (Decimal("8.00"), Decimal("4.00")),
    "404": (Decimal("9.00"), Decimal("4.50")),
    "505": (Decimal("10.00"), Decimal("5.00")),
}
METRO_FARES: tuple[Decimal, Decimal] = (Decimal("10.00"), Decimal("5.00"))

INTEGRATION_DISCOUNT = Decimal("15.00")

# Namespace fixo para IDs determinísticos (UUIDv5).
_SEED_NAMESPACE = uuid.UUID("5eedfa7e-0000-4000-8000-000000000000")


def _fare_id(mode: str, line_code: str | None, profile: str) -> uuid.UUID:
    return uuid.uuid5(_SEED_NAMESPACE, f"fare:{mode}:{line_code or ''}:{profile}")


def _rule_id(trip_type: str) -> uuid.UUID:
    return uuid.uuid5(_SEED_NAMESPACE, f"fare_rule:{trip_type}")


def _fare_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_code, (integral, meia) in sorted(BUS_FARES.items()):
        for profile, amount in (("INTEGRAL", integral), ("MEIA", meia)):
            rows.append(
                {
                    "id": _fare_id("BUS", line_code, profile),
                    "mode": "BUS",
                    "line_code": line_code,
                    "fare_profile": profile,
                    "amount": amount,
                    "valid_from": INITIAL_VALIDITY_START,
                    "valid_until": None,
                }
            )
    for profile, amount in (("INTEGRAL", METRO_FARES[0]), ("MEIA", METRO_FARES[1])):
        rows.append(
            {
                "id": _fare_id("METRO", None, profile),
                "mode": "METRO",
                "line_code": None,
                "fare_profile": profile,
                "amount": amount,
                "valid_from": INITIAL_VALIDITY_START,
                "valid_until": None,
            }
        )
    return rows


_FARES_TABLE = sa.table(
    "fares",
    sa.column("id", sa.Uuid()),
    sa.column("mode", sa.Text()),
    sa.column("line_code", sa.Text()),
    sa.column("fare_profile", sa.Text()),
    sa.column("amount", sa.Numeric(12, 2)),
    sa.column("valid_from", sa.TIMESTAMP(timezone=True)),
    sa.column("valid_until", sa.TIMESTAMP(timezone=True)),
)

_FARE_RULES_TABLE = sa.table(
    "fare_rules",
    sa.column("id", sa.Uuid()),
    sa.column("trip_type", sa.Text()),
    sa.column("discount_percentage", sa.Numeric(5, 2)),
    sa.column("valid_from", sa.TIMESTAMP(timezone=True)),
    sa.column("valid_until", sa.TIMESTAMP(timezone=True)),
)


def upgrade() -> None:
    op.bulk_insert(_FARES_TABLE, _fare_rows())
    op.bulk_insert(
        _FARE_RULES_TABLE,
        [
            {
                "id": _rule_id("INTEGRATION"),
                "trip_type": "INTEGRATION",
                "discount_percentage": INTEGRATION_DISCOUNT,
                "valid_from": INITIAL_VALIDITY_START,
                "valid_until": None,
            }
        ],
    )


def downgrade() -> None:
    # Remove exatamente os registros inseridos pelo upgrade (mesmos IDs
    # determinísticos). O schema permanece intacto.
    fare_ids = [row["id"] for row in _fare_rows()]
    op.execute(_FARES_TABLE.delete().where(_FARES_TABLE.c.id.in_(fare_ids)))
    op.execute(_FARE_RULES_TABLE.delete().where(_FARE_RULES_TABLE.c.id == _rule_id("INTEGRATION")))
