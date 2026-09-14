"""Logging estruturado em JSON.

Fonte: ADR-008 — "logs JSON estruturados correlacionados por trace_id".

Restrições que valem para todo log da aplicação:

- nunca registrar valor de OTP;
- nunca registrar CPF completo nem número completo de cartão;
- nunca registrar `qr_token`, secret ou token de provider;
- se a sanitização de um campo não for possível, não registrar o campo.

A implementação usa apenas a biblioteca padrão: nenhuma dependência de
logging foi adicionada, porque nenhuma SPEC ou ADR a exige.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

# Atributos internos do LogRecord que não devem ser copiados para o payload.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """Formata registros de log como uma única linha JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Campos extras passados via `logger.info(..., extra={...})`.
        # A responsabilidade de sanitizar o conteúdo é de quem registra.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            # Somente o tipo da exceção: stack trace não vai para o log
            # estruturado nem, em nenhuma hipótese, para a resposta HTTP.
            exc_type = record.exc_info[0]
            payload["exception_type"] = exc_type.__name__ if exc_type else None

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configura o logging raiz para saída JSON em stdout.

    Idempotente: chamadas repetidas não acumulam handlers.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
