# Fare — motor tarifário determinístico

**Fronteira de domínio:** ADR-001
**Documentos obrigatórios:** SPEC-001
**ADRs aplicáveis:** ADR-004, ADR-005, ADR-012
**Estado:** **implementado** (SPEC-001)

## Responsabilidade

Única autoridade de cálculo tarifário: valida trajetos, consulta tarifas
vigentes persistidas, aplica o perfil por segmento, classifica a viagem,
aplica o desconto da regra vigente e retorna o breakdown completo e auditável.
O LLM nunca é fonte do cálculo e nenhum erro admite fallback estimado.

## Estrutura

```text
fare/
├── domain/
│   ├── enums.py           TransportMode, FareProfile, TripType
│   ├── entities.py        Fare, FareRule (puras)
│   ├── value_objects.py   Segment, FareLookupKey, FareCalculation,
│   │                      to_money (único ponto de ROUND_HALF_UP)
│   ├── errors.py          os 10 erros tipados de SPEC-001 §11 (puros,
│   │                      sem AppError/HTTP)
│   ├── services.py        TripClassifier, FareCalculator (matemática pura)
│   └── ports.py           FareRepository, FareRuleRepository (Protocol)
├── application/
│   └── services.py        FareService.calculate_trip_fare — ordem de §6
└── infrastructure/
    ├── models.py          FareModel, FareRuleModel (constraints + EXCLUDE)
    └── repositories.py    implementações SQLAlchemy 2.0
```

Migrations: `fare0001` (schema) e `fare0002` (12 tarifas oficiais + regra de
INTEGRATION 15%, vigência fictícia aprovada 2026-01-01Z).

## Decisões vigentes

- Metrô-só multi-segmento → `UNSUPPORTED_TRIP_COMPOSITION` (A-04 resolvida).
- METRO com `line_code` → `INVALID_SEGMENT_STRUCTURE`; BUS sem linha →
  `BUS_LINE_REQUIRED`.
- `FARE_LINE_NOT_FOUND` só para BUS; METRO sem vigência →
  `FARE_NOT_AVAILABLE`.
- Vigência `[valid_from, valid_until)` em TIMESTAMPTZ/UTC; não-sobreposição
  garantida por EXCLUDE constraint.
- Instante de referência resolvido uma única vez por operação e presente no
  resultado auditável.
- MEIA aplicada por segmento **antes** do desconto; único arredondamento é o
  do desconto (`ROUND_HALF_UP`).
- `FARE_SERVICE_UNAVAILABLE` só para falha de conectividade do banco — bugs
  propagam.

## Tools que este módulo suportará (SPEC-004)

- `calculate_trip_fare` → `FareService.calculate_trip_fare`.

⚠️ `calculate_usage_cost` segue **não especificada** (A-06 em
`docs/OPEN-QUESTIONS.md`) e não foi implementada.

## Tools proibidas

- `set_fare`
- `apply_discount`
- `override_rule`

Nenhuma delas pode ser criada sob nome equivalente ou disfarçada como tool
genérica.

## Alteração de tarifas

Nunca sobrescreva histórico: alteração encerra a vigência anterior
(`valid_until = novo valid_from`) e cria registro novo (SPEC-001 §8). O seed
inicial vive em migration por ser o conjunto de referência obrigatório do MVP;
alterações operacionais futuras terão fluxo administrativo próprio.

## Testes

- Unit: `tests/unit/fare/` — 16 casos obrigatórios de §12, classificação,
  validação, `ROUND_HALF_UP`, invariantes do resultado, determinismo e prova
  AST de ausência de float.
- Integração: `tests/integration/fare/` — constraints violadas de propósito,
  repositories por vigência contra o seed real, serviço fim a fim no
  PostgreSQL, ciclo completo de migrations.
