"""Observability — correlacao de dominio.

Fronteira de dominio declarada em ADR-001.

Fronteira declarada em ADR-001. A instrumentacao transversal (logging JSON e
bootstrap de telemetria) vive em urbanopay.core; este modulo reserva o espaco
para helpers de correlacao especificos de dominio, como enriquecimento de span
com IDs de Order e Payment.

Documentos obrigatorios: transversal; ADR-008.

Estado: nao implementado. Ver o README deste diretorio antes de escrever
qualquer codigo aqui.
"""
