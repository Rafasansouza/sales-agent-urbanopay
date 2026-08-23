# Regra — Testes

Fonte: CLAUDE.md, ADR-005, ADR-010, AGENT-HARNESS §5, SPEC-001..005.

## Obrigatoriedade

- Mudança de comportamento exige teste.
- Correção de bug exige teste de regressão que falhe antes da correção.
- Mudança de schema exige migration **e** teste de integração.
- Troca de modelo de LLM exige execução da suíte de regressão (ADR-010).

## Proibições

- Nunca deletar, marcar como skip ou enfraquecer um teste apenas para fazer a
  CI passar.
- Nunca reduzir assertividade de teste crítico para acomodar implementação.
- Nunca contornar a CI removendo check.

Se um teste falha, a hipótese padrão é que **o código está errado**.

## Camadas

| Camada | Diretório | Alvo | Marcador |
|---|---|---|---|
| Unit | `tests/unit/` | Regra de domínio pura, sem I/O | `unit` |
| Integração | `tests/integration/` | Fronteira de banco e de provider | `integration` |
| E2E | `tests/e2e/` | Jornada completa de compra | `e2e` |
| Evals | `tests/evals/` | Comportamento probabilístico do agente | `eval` |

Todo teste precisa de marcador. Teste sem marcador não é coletado pelos alvos
de `make`/`dev.ps1` e é considerado defeito.

## O que vai em cada camada

**Unit** — cálculo tarifário, classificação de viagem, arredondamento
`ROUND_HALF_UP`, `ApprovalPolicy`, transições de state machine, masking,
validação de documento, erros tipados.

**Integração** — repositórios, migrations, constraints de banco, transação
atômica de ledger e saldo, lock de concorrência, idempotência, webhook de
pagamento, `FakePaymentProvider`.

**E2E** — o critério de aceite do PRD §18: descrição em linguagem natural →
cálculo → recomendação → autenticação → seleção de cartão → confirmação → Pix
de teste → confirmação de pagamento → recarga ou bilhete → rastreabilidade.

**Evals** — dataset de SPEC-004 §16: 50 intents, 50 extrações de trajeto, 30
recomendações, 30 confirmações e 50 adversariais (210 casos).

## Determinismo

- Regra determinística **nunca** é testada com eval. Use unit test.
- Comportamento de LLM **nunca** é testado com asserção exata de string. Use
  eval com métrica.
- Testes usam `FakeLLMProvider` e `FakePaymentProvider`; nenhuma chamada real a
  provider em CI (ADR-007, ADR-010).
- Nenhum teste depende de rede externa.

## Metas quantitativas

Fonte: PRD §16 e SPEC-004 §16.

| Métrica | Meta |
|---|---|
| Fare Calculation Accuracy | 100% |
| Critical Hallucination Rate | 0% |
| Unauthorized Critical Actions | 0 |
| Duplicidade de efeito financeiro | 0 |
| Intent Accuracy | ≥ 95% |
| Trip Extraction Accuracy | ≥ 98% |
| Recommendation Accuracy | ≥ 90% |
| E2E Successful Journey Rate | ≥ 90% |

Confirmação crítica exige taxa de falso positivo **zero** no dataset crítico
(ADR-010).

## Cenários que nunca podem ficar sem cobertura

- Usuário afirma "paguei" sem pagamento aprovado.
- Webhook duplicado.
- Concorrência em atualização de saldo.
- `Payment APPROVED` seguido de falha de fulfillment.
- Acesso a recurso de outro cliente.
- Prompt injection tentando ação crítica.
- Transição de estado inválida.
