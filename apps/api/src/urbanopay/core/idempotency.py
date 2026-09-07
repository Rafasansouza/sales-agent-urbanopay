"""Contrato transversal de idempotência de comando (SPEC-003 §11).

Concern transversal, não domínio: `orders`, `approvals` e `payments` a usam.
Segue o mesmo padrão de `core/persistence.py` — aqui vivem apenas contratos,
enums e value objects; a implementação SQLAlchemy fica em `db/idempotency.py`.

**Este módulo nunca importa SQLAlchemy** (verificado por teste de arquitetura).

Semântica dos status (SPEC-003 §11.1):

- `IN_PROGRESS` — a key foi reivindicada e a operação ainda não concluiu;
- `COMPLETED` — a operação executou e o **resultado é conhecido**, inclusive
  quando o Payment resultante terminou em estado não aprovado;
- `FAILED` — falha **determinística da própria operação**, reproduzida em
  replay. `Payment.REJECTED` não é `Idempotency.FAILED`.

Fronteira transacional (SPEC-003 §11.2): comandos locais reivindicam, aplicam
o efeito e completam na MESMA transação — não existe `IN_PROGRESS` órfão
observável. Somente `create_payment`, que tem efeito externo, usa duas fases.

Não existe apropriação de key por tempo (§11.3): o tempo autoriza
reconciliação, nunca cobrança.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID


class IdempotencyStatus(StrEnum):
    """Ciclo de vida do registro de idempotência (SPEC-003 §11.1)."""

    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IdempotencyConflictError(Exception):
    """Mesma key com payload diferente (SPEC-003 §16: `IDEMPOTENCY_CONFLICT`).

    Erro puro: código semântico, sem HTTP e sem PII.
    """

    code: ClassVar[str] = "IDEMPOTENCY_CONFLICT"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "A chave de idempotência já foi usada com outro conteúdo de requisição."
        )


def request_fingerprint(payload: Mapping[str, str]) -> str:
    """Impressão determinística do payload, para detectar divergência.

    Não é mecanismo de segurança (não leva segredo): serve apenas para
    distinguir "mesma requisição" de "requisição diferente com a mesma key".
    Os valores chegam já normalizados como texto pelo chamador — em especial,
    valores monetários como string decimal, nunca float.
    """
    canonical = json.dumps(dict(sorted(payload.items())), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Registro de idempotência de um comando crítico (SPEC-003 §11)."""

    key: str
    operation: str
    request_fingerprint: str
    status: IdempotencyStatus
    resource_id: UUID | None
    response_reference: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    def is_stale(self, at: datetime, stale_after_seconds: int) -> bool:
        """Indica se o registro está em `IN_PROGRESS` há tempo demais.

        Serve **exclusivamente** para acionar reconciliação (consulta ao
        provider). Nunca autoriza nova cobrança — ver SPEC-003 §11.3.
        """
        if self.status is not IdempotencyStatus.IN_PROGRESS:
            return False
        return (at - self.updated_at).total_seconds() >= stale_after_seconds


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    """Resultado da tentativa de reivindicar uma key.

    `acquired=True` ⇒ esta execução é a dona da operação e deve prosseguir.
    `acquired=False` ⇒ outra execução já reivindicou; `existing` traz o
    registro para que o chamador decida entre replay, conflito ou estado
    desconhecido.
    """

    acquired: bool
    existing: IdempotencyRecord | None


class IdempotencyRepository(Protocol):
    """Persistência dos registros de idempotência.

    Escopo de unicidade: `(operation, key)`. Implementações nunca comitam — a
    fronteira transacional é do Unit of Work do módulo chamador.
    """

    async def claim(
        self,
        *,
        operation: str,
        key: str,
        fingerprint: str,
        at: datetime,
    ) -> IdempotencyClaim:
        """Reivindica a key de forma atômica (`INSERT ... ON CONFLICT`)."""
        ...

    async def get(self, *, operation: str, key: str) -> IdempotencyRecord | None: ...

    async def complete(
        self,
        *,
        operation: str,
        key: str,
        resource_id: UUID | None,
        response_reference: str | None,
        at: datetime,
    ) -> None:
        """Marca `COMPLETED` — resultado conhecido, qualquer que seja ele."""
        ...

    async def fail(
        self,
        *,
        operation: str,
        key: str,
        response_reference: str | None,
        at: datetime,
    ) -> None:
        """Marca `FAILED` — falha determinística a reproduzir em replay."""
        ...


def ensure_same_request(record: IdempotencyRecord, fingerprint: str) -> None:
    """Rejeita reuso de key com payload diferente (SPEC-003 §11)."""
    if record.request_fingerprint != fingerprint:
        raise IdempotencyConflictError
