"""Agent — Sales Agent conversacional.

Fronteira de dominio declarada em ADR-001.

Agente conversacional unico que compreende linguagem natural, preserva
contexto, coleta dados faltantes, chama tools estreitas, recomenda e conduz a
jornada. Nao possui autoridade financeira.

Documentos obrigatorios: SPEC-004; ADR-002, ADR-003, ADR-005, ADR-010.

Estado: **Etapa 1 implementada** (SPEC-004 §22) — camada deterministica de
tools: catalogo fechado, visibilidade, autorizacao, envelopes, presenters,
guardas de contexto, politica de idempotencia e composition root.

Fora desta etapa, por decisao registrada: LangGraph, provider de LLM, prompt,
evals, limites de token/custo e persistencia conversacional (Etapa 2, bloqueada
pelo ADR-014 / H-11); transporte HTTP, webhook e coordenador pos-pagamento
(Etapa 3, SPEC-005 §10.1 / A-19).

Ver o README deste diretorio antes de escrever qualquer codigo aqui.
"""
