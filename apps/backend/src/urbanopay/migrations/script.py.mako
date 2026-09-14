"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Lembretes (ADR-012):
- autogenerate produz uma CANDIDATA; revise cada operação antes de aceitar;
- índices parciais, CHECKs e invariantes específicas do PostgreSQL exigem
  revisão explícita — o autogenerate não as cobre com confiabilidade;
- migration destrutiva exige revisão humana sinalizada no PR;
- toda constraint deve ter nome determinístico (naming convention).
"""

from __future__ import annotations

${imports if imports else ""}
from alembic import op
import sqlalchemy as sa

# Identificadores da revision, usados pelo Alembic.
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | None = ${repr(branch_labels)}
depends_on: str | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
