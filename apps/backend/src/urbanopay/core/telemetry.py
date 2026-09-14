"""Ponto de entrada da telemetria.

Fonte: ADR-008 — OpenTelemetry é o padrão transversal; Langfuse é
especializado em observabilidade de LLM e agente.

Estado atual: **nenhuma instrumentação foi implementada**. As dependências de
OpenTelemetry e Langfuse não foram adicionadas ao projeto, porque a
instrumentação acompanha a implementação das SPECs e o modo de implantação do
Langfuse permanece em aberto (ver H-04 em docs/OPEN-QUESTIONS.md).

Este módulo existe para tornar explícito o ponto de acoplamento e as regras
que valerão quando a instrumentação chegar:

- instrumentar FastAPI, services, chamadas externas e nodes relevantes do
  agente; não criar span para cada função trivial;
- generations de LLM registram provider, model, tokens, custo e latência;
- tool calls registram nome, duração e resultado, sem PII;
- OTP nunca é registrado; CPF, cartão e secrets são mascarados ou removidos;
- traces não são fonte de verdade financeira;
- outage de observabilidade não derruba o fluxo de negócio;
- se a sanitização falhar, preferir não exportar.
"""

from __future__ import annotations

import logging

from urbanopay.core.config import Settings

logger = logging.getLogger(__name__)


def configure_telemetry(settings: Settings) -> None:
    """Inicializa a telemetria conforme a configuração.

    Nesta fase apenas registra a intenção. A ativação real exige as
    dependências de OpenTelemetry, que ainda não foram adicionadas.
    """
    if settings.otel_enabled:
        logger.warning(
            "otel_enabled=true, mas a instrumentacao OpenTelemetry ainda nao "
            "foi implementada nesta fase do bootstrap",
            extra={"otel_service_name": settings.otel_service_name},
        )

    if settings.langfuse_enabled:
        logger.warning(
            "langfuse_enabled=true, mas a integracao Langfuse ainda nao foi "
            "implementada nesta fase do bootstrap"
        )
