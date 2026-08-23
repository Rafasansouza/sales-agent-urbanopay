# ADR-002 — LangGraph como Runtime de Orquestração do Agente

**Status:** Aceito  
**Data:** 2026-08-23

## Decisão
Adotar LangGraph para estado conversacional, roteamento, tools, interrupts, resume e human-in-the-loop.

## Princípios
- LangGraph orquestra, não implementa regra de negócio;
- estado do grafo não é source of truth de saldo, tarifa, order ou payment;
- checkpoints devem ser duráveis; preferência por PostgreSQL;
- nodes podem ser LLM, code ou tool;
- side effects precisam ser idempotentes porque nodes podem ser retomados/reexecutados;
- confirmação do passageiro e aprovação humana podem usar interrupt/resume;
- webhook financeiro não passa pelo grafo.

## Alternativas
Loop manual, agent abstraction de alto nível, OpenAI Agents SDK e workflow tradicional foram considerados. LangGraph foi escolhido pelo controle explícito stateful/interruptible.

## Princípio final
LangGraph sabe onde estamos; Domain Services sabem o que é permitido; PostgreSQL sabe o que aconteceu.
