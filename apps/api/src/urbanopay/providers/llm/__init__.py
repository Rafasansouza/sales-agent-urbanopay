"""Abstração de provider de LLM.

Fonte: ADR-010.

Estado: não implementado. A porta `LLMProvider`, o Model Router, os contratos
tipados (`IntentResult`, `TripExtractionResult`, `ConfirmationResult`,
`ModelResponse`) e o `FakeLLMProvider` nascem com a implementação da SPEC-004.

Regra permanente: nodes nunca instanciam SDK de provider diretamente.
"""
