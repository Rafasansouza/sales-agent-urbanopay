# ADR-010 — Estratégia de LLM, Model Routing e Abstração de Provider

**Status:** Aceito  
**Data:** 2026-08-23

## Decisão
Criar abstração `LLMProvider`/Model Router. Baseline inicial do Sales Agent: Claude Sonnet 5, configurável. Não implementar três providers no MVP; usar FakeLLMProvider para testes.

## Regras
- nodes não instanciam SDK de provider diretamente;
- contratos internos tipados (`IntentResult`, `TripExtractionResult`, `ConfirmationResult`, `ModelResponse`);
- structured outputs + Pydantic + domain validation;
- strict tools quando disponível;
- schema válido não implica regra válida;
- provider não executa business rule;
- começar com modelo único e só introduzir FAST_MODEL após evals;
- troca de modelo exige regression suite;
- confirmação crítica precisa false-positive rate 0 no dataset crítico;
- cost target <= US$0.05 por venda concluída;
- contexto usa structured state + turnos recentes + tool results relevantes;
- prompt caching é otimização, não requisito;
- fallback automático entre providers não entra no MVP;
- outage do LLM não deve parar webhook/payment/fulfillment já persistidos;
- minimizar PII enviada ao provider.

## Princípio final
O modelo é uma dependência substituível; os contratos e regras do produto não são.
