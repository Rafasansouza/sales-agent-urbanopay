# Identity — clientes, OTP e sessoes

**Fronteira de dominio:** ADR-001
**Documentos obrigatorios:** SPEC-002
**ADRs aplicaveis:** ADR-004, ADR-005
**Estado:** nao implementado

## Responsabilidade

Identificacao por CPF/login conceitual, autenticacao simulada por OTP e gestao de sessao.

## Entidades previstas

- `Customer`
- `OTPChallenge`
- `Session`

## Tools permitidas ao Sales Agent

- `start_authentication`
- `verify_otp`
- `get_authentication_status`

## Tools proibidas

- `authenticate_as`
- `change_customer`

Nenhuma delas pode ser criada sob nome equivalente ou disfarcada como tool
generica.

## Invariantes e bloqueios

- O valor do OTP nunca aparece em log, resposta, excecao ou trace.
- CPF completo nunca vai para log nem para o LLM.
- Operacao transacional exige authenticated=true.

## Estrutura esperada quando implementado

```text
identity/
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
