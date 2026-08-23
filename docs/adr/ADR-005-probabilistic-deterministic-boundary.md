# ADR-005 — Separação entre IA Probabilística e Domínio Determinístico

**Status:** Aceito  
**Data:** 2026-08-23

## Decisão
Separar explicitamente IA probabilística de regras determinísticas.

### LLM
Entende intenção, extrai contexto, pergunta, recomenda, explica e interpreta linguagem.

### Código
Autentica, autoriza, consulta tarifas/saldo, calcula, controla state machines, aprova políticas, define amount, confirma payment, executa fulfillment e persiste.

## Regras
- dado declarado é inferior a dado verificado;
- LLM nunca é fonte de preço/saldo/perfil/payment status;
- tools estreitas e tipadas;
- argumentos críticos são derivados server-side;
- prompt é orientação, não segurança;
- defense in depth: prompt -> schema -> service -> authorization -> state machine -> DB constraints.

## Testes
LLM behavior usa evals; regras determinísticas usam unit/integration tests.

## Princípio final
O modelo pode sugerir uma ação. O sistema decide se ela existe, é válida e pode ser executada.
