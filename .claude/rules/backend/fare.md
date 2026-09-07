---
description: Regras do Fare Engine (SPEC-001). Cálculo tarifário determinístico.
paths:
  - "apps/api/src/urbanopay/modules/fare/**"
  - "tests/**/fare/**"
  - "tests/**/*fare*"
---

# Regra — Fare Engine

**Documentos obrigatórios:** `docs/specs/SPEC-001-fare-engine.md`, ADR-004, ADR-005.

Leia a SPEC-001 antes de qualquer alteração neste módulo.

## Princípio

O LLM nunca é a fonte oficial do cálculo tarifário. O Fare Engine é
determinístico: mesma entrada e mesmas regras vigentes produzem sempre o mesmo
resultado.

## Tarifas

As tarifas de SPEC-001 §2 existem como **dados persistidos**, nunca
hard-coded na lógica. Um valor de tarifa escrito em código Python é defeito.

## Ordem de cálculo

Fonte: SPEC-001 §6. A ordem é normativa e não pode ser reorganizada:

1. validar request;
2. validar segmentos;
3. validar perfil;
4. consultar tarifas vigentes;
5. aplicar a tarifa do perfil em cada segmento;
6. calcular subtotal;
7. classificar a viagem;
8. consultar a regra vigente;
9. calcular o desconto;
10. calcular o total;
11. retornar o breakdown.

A tarifa `MEIA` é aplicada **por segmento**, antes do desconto de integração.
Inverter essa ordem produz valor errado.

## Classificação

| Tipo | Condição | Desconto |
|---|---|---|
| `SINGLE` | exatamente um segmento | 0% |
| `COMMON` | dois ou mais segmentos exclusivamente de ônibus | 0% |
| `INTEGRATION` | ao menos um ônibus e ao menos um metrô | regra vigente (15% inicial) |

Composição com dois ou mais segmentos exclusivamente de metrô →
`UNSUPPORTED_TRIP_COMPOSITION` (decisão A-04, **resolvida**: interpretação
conservadora aprovada — nunca classificar como COMMON, nunca inventar
categoria).

Decisões estruturais vigentes: METRO com `line_code` →
`INVALID_SEGMENT_STRUCTURE`; BUS sem linha → `BUS_LINE_REQUIRED`;
`FARE_LINE_NOT_FOUND` é específico de BUS — METRO sem tarifa vigente é sempre
`FARE_NOT_AVAILABLE`.

## Dinheiro

`Decimal` em Python, `NUMERIC` no PostgreSQL, duas casas decimais,
`ROUND_HALF_UP`, string decimal no contrato JSON.

## Vigência

Tarifa e regra possuem `valid_from` e `valid_until`. Alteração futura encerra a
vigência anterior; nunca sobrescreve histórico.

## Invariantes

Fonte: SPEC-001 §13.

- `total >= 0`;
- `desconto <= subtotal`;
- `COMMON` ⇒ desconto 0%;
- `INTEGRATION` ⇒ regra vigente;
- `MEIA` nunca usa tarifa integral;
- `INTEGRAL` nunca usa tarifa meia;
- mesma entrada + mesmas regras ⇒ mesmo resultado.

## Erros tipados

`INVALID_FARE_PROFILE`, `INVALID_TRANSPORT_MODE`, `INVALID_SEGMENT_STRUCTURE`,
`EMPTY_TRIP`, `BUS_LINE_REQUIRED`, `FARE_LINE_NOT_FOUND`, `FARE_NOT_AVAILABLE`,
`FARE_RULE_NOT_FOUND`, `UNSUPPORTED_TRIP_COMPOSITION`,
`FARE_SERVICE_UNAVAILABLE`.

**Nenhum erro autoriza fallback do LLM para tarifa estimada.** Erro é erro.

## Tools expostas ao agente

Apenas tool estreita, por exemplo `calculate_trip_fare`.

⚠️ `calculate_usage_cost` aparece em SPEC-004 §7 mas **não está especificada**
em SPEC-001. Ver A-06 em `docs/OPEN-QUESTIONS.md`.

## Testes

Os 16 casos obrigatórios de SPEC-001 §12 são unit tests e precisam de 100% de
acurácia. Não substitua nenhum deles por eval.
