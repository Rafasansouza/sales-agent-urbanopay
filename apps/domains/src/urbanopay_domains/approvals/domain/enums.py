"""Enums do domínio de aprovação (SPEC-003 §7)."""

from __future__ import annotations

from enum import StrEnum


class ApprovalStatus(StrEnum):
    """Estados da `Approval` (SPEC-003 §7).

    Sem TTL e **sem estado `CANCELLED`** no MVP: a SPEC não define nenhum, e
    inventar um criaria caminho de encerramento não especificado. Estados
    terminais não retornam a `PENDING`.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
