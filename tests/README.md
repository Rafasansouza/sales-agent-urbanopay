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

- `unit/` — fumaça do health check, arquitetura (domínio não importa
  persistência), event loop de Windows e o **domínio do Fare Engine**
  (`unit/fare/`): 16 casos obrigatórios de SPEC-001 §12, classificação,
  `ROUND_HALF_UP`, invariantes e prova AST de ausência de float.
- `integration/` — persistence foundation (conexão, Decimal, UoW, naming
  convention) e **Fare Engine** (`integration/fare/`): constraints violadas de
  propósito, repositories por vigência, serviço fim a fim e ciclo completo de
  migrations. **Coleta vazia reprova** nesta camada (H-07).
- `e2e/` e `evals/` — vazios porque as SPECs não foram implementadas; nessas
  duas camadas, zero testes coletados ainda é o resultado esperado.

Testes assíncronos usam `@pytest.mark.asyncio` (pytest-asyncio em modo
strict). Em Windows, o hook `pytest_asyncio_loop_factories` do `conftest.py`
fornece um `SelectorEventLoop`, exigido pelo psycopg async.

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
