# Fare — motor tarifario deterministico

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-001
**ADRs aplicaveis:** ADR-004, ADR-005
**Estado:** nao implementado

## Responsabilidade

Valida trajetos, consulta tarifas vigentes, aplica perfil tarifario, classifica a viagem, aplica desconto e retorna o breakdown completo. O LLM nunca e a fonte oficial do calculo.

## Entidades previstas

- `Fare`
- `FareRule`

## Tools permitidas ao Sales Agent

- `calculate_trip_fare`
- `calculate_usage_cost (nao especificada, ver A-06)`

## Tools proibidas

- `set_fare`
- `apply_discount`
- `override_rule`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- Tarifas sao dados persistidos, nunca hard-coded (SPEC-001 §2).
- MEIA e aplicada por segmento antes do desconto de integracao.
- Composicao exclusivamente de metro nao esta definida: ver A-04.
- calculate_usage_cost nao esta especificada: ver A-06.

## Estrutura esperada quando implementado

```text
fare/
├── domain/          entidades, value objects, erros tipados, regras puras
├── application/     use cases e servicos
└── infrastructure/  repositorios e adaptadores
```

Direcao de dependencia: `domain` nao importa `application` nem
`infrastructure`. Ver `.claude/rules/architecture.md`.

## Antes de implementar

1. Leia a SPEC correspondente por inteiro, nao de memoria.
2. Leia `docs/OPEN-QUESTIONS.md` e confirme que nenhuma pendencia bloqueia a
   tarefa.
3. Confirme que os ADRs necessarios estao com status Aceito.
4. Use a skill `prepare-task` antes de escrever codigo.
