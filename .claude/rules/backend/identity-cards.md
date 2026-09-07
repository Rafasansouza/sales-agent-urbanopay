---
description: Regras de identidade, autenticação simulada, sessões e cartões (SPEC-002).
paths:
  - "apps/api/src/urbanopay/modules/identity/**"
  - "apps/api/src/urbanopay/modules/cards/**"
  - "tests/**/identity/**"
  - "tests/**/cards/**"
  - "tests/**/*card*"
  - "tests/**/*auth*"
---

# Regra — Identity & Cards

**Documentos obrigatórios:** `docs/specs/SPEC-002-cards-identity.md`, ADR-004, ADR-005.

Leia a SPEC-002 antes de qualquer alteração nestes módulos.

## Regra central

Durante uma transação, `card.fare_profile` é a **fonte oficial** do perfil
tarifário. O perfil declarado pelo usuário serve apenas para simulação
anônima.

```json
{"fare_profile": "MEIA",     "source": "USER_DECLARED", "verified": false}
{"fare_profile": "INTEGRAL", "source": "CARD",          "verified": true}
```

Havendo divergência, o valor precisa ser recalculado antes de Quote e Order.

`FARE_PROFILE_CHANGED` é **sinal de resultado, não exceção** (A-11 resolvida):
`ProfileResolutionResult.signal` o carrega quando declarado ≠ oficial. O
recálculo e a invalidação de Quote pertencem às SPEC-003/004.

## Titularidade

Toda operação sobre cartão protegido valida:

```text
card.customer_id == session.customer_id
```

Se não pertencer ao cliente autenticado, responda `CARD_NOT_ACCESSIBLE`
**sem revelar se o cartão existe**.

## OTP simulado

Mesmo simulado, mantenha: hash, expiração, máximo de tentativas, uso único e
nenhuma exposição em telemetria.

**O valor do OTP nunca é logado, nunca é retornado em resposta e nunca entra
em trace ou span.**

Sugestões iniciais da SPEC: 5 minutos de expiração, 5 tentativas — ambas
configuráveis.

## Masking

Nunca retorne o número completo do cartão ao agente. Formato: `****4821`.
Tools operam com `card_id` e, quando necessário, `masked_number`.

## Saldo

`Decimal`/`NUMERIC`, nunca float. `get_card_balance` exige sessão autenticada,
titularidade validada e cartão acessível.

## Matriz de autorização

Fonte: SPEC-002 §9.

| Ação | Anônimo | Autenticado |
|---|---|---|
| Consultar catálogo | Sim | Sim |
| Simular tarifa | Sim | Sim |
| Listar cartões | Não | Próprios |
| Consultar saldo | Não | Próprio |
| Usar perfil oficial | Não | Próprio |
| Criar Order | Não | Sim |
| Recarga | Não | Sim |
| Consultar pedidos | Não | Próprios |

## Tools permitidas

`start_authentication`, `verify_otp`, `get_authentication_status`,
`get_customer_cards`, `get_card_details`, `get_card_balance`.

## Tools proibidas

`authenticate_as`, `change_customer`, `change_fare_profile`, `change_balance`,
`link_card`. Não crie nenhuma delas, sob nenhum nome equivalente.

## Hierarquia de confiança

```text
mensagem do usuário < contexto da IA < identidade da sessão
  < dados oficiais do cartão < regras determinísticas
```

## Testes

Os 12 cenários obrigatórios de SPEC-002 §14 incluem OTP inválido, OTP
expirado, máximo de tentativas, cartão `BLOCKED`, cartão `EXPIRED`, cartão de
outro usuário, divergência de perfil nos dois sentidos, prompt injection e
sessão expirada.

A-12 resolvida: o dataset de §13 vive como **fixture de teste** (sem seed em
migration), acrescido do cartão `EXPIRED` e do cenário cross-user que os
testes de §14 exigem.
