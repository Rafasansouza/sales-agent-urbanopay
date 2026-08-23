# tests — Suíte de testes

**Documentos:** CLAUDE.md, ADR-005, ADR-010, AGENT-HARNESS §5, testes
obrigatórios de cada SPEC.

A suíte fica na raiz do repositório conforme a estrutura de ADR-001.

## Camadas

| Diretório | Marcador | Alvo | Requer infra? |
|---|---|---|---|
| `unit/` | `unit` | Regra de domínio pura, sem I/O | Não |
| `integration/` | `integration` | Fronteira de banco e de provider | Sim |
| `e2e/` | `e2e` | Jornada completa de compra | Sim |
| `evals/` | `eval` | Comportamento probabilístico do agente | Não |

## Executar

```powershell
.\scripts\dev.ps1 test-unit
.\scripts\dev.ps1 test-integration    # requer `up`
.\scripts\dev.ps1 test-e2e            # requer `up`
.\scripts\dev.ps1 evals
```

```bash
make test-unit
make test-integration
make test-e2e
make evals
```

## Marcador é obrigatório

`--strict-markers` está ativo. Um teste sem marcador não é coletado pelos
alvos acima e é considerado defeito, não teste "genérico".

## Regras da suíte

- Mudança de comportamento exige teste.
- Correção de bug exige teste de regressão que falhe **antes** da correção.
- Nunca deletar, marcar como skip ou enfraquecer teste para fazer a CI passar.
- Nenhum teste depende de rede externa, de relógio real ou de ordem de
  execução.
- Nenhuma chamada real a provider de LLM ou de pagamento em CI: use
  `FakeLLMProvider` e `FakePaymentProvider`.
- Nenhum dado pessoal real, em nenhum ambiente.

## Escolha da camada

Regra determinística **nunca** é validada por eval. O cálculo tarifário exige
100% de acurácia (PRD §16), o que é incompatível com métrica probabilística.

Comportamento de LLM **nunca** é validado por asserção exata de string.

## Estado atual

Nesta fase do bootstrap, apenas `unit/` possui testes: um teste de fumaça do
health check.

`integration/`, `e2e/` e `evals/` estão vazios porque as SPEC-001 a SPEC-005
não foram implementadas. **Zero testes coletados nessas camadas é o resultado
esperado**, não uma falha.

## Cenários que nunca podem ficar sem cobertura

Quando as SPECs forem implementadas:

- usuário afirma "paguei" sem pagamento aprovado;
- webhook duplicado;
- concorrência na atualização de saldo;
- `Payment APPROVED` seguido de falha de fulfillment;
- acesso a recurso de outro cliente;
- prompt injection tentando ação crítica;
- transição de estado inválida;
- segunda tentativa de pagamento após rejeição.

Listas completas: SPEC-001 §12, SPEC-002 §14, SPEC-003 §17, SPEC-004 §17,
SPEC-005 §21.
