"""Enums do domínio de identidade (SPEC-002 §2)."""

from __future__ import annotations

from enum import StrEnum


class CustomerStatus(StrEnum):
    """Status do cliente (SPEC-002 §2)."""

    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    INACTIVE = "INACTIVE"


class ChallengeStatus(StrEnum):
    """Status do desafio de OTP (SPEC-002 §2)."""

    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"
