# Cards — titularidade, masking e autoridade de perfil tarifário

**Fronteira de domínio:** ADR-001
**Documentos obrigatórios:** SPEC-002
**ADRs aplicáveis:** ADR-004, ADR-005, ADR-012
**Estado:** **implementado** (SPEC-002)

## Responsabilidade

Autoridade determinística sobre o cartão: titularidade server-side, saldo
somente leitura e o **perfil tarifário oficial** — que vem SEMPRE do cartão,
nunca da fala do usuário (§1, §16; PRD RN-02).

## Decisões vigentes (aprovadas no plano da SPEC-002)

- **Número completo do cartão não existe no sistema**: persiste-se apenas
  `card_last4`; apresentação `****4821` (§6); identidade oficial é o UUID.
- Ownership em **uma única query** `get_owned(customer_id, card_id)`:
  inexistente e alheio são indistinguíveis → `CARD_NOT_ACCESSIBLE` (§5,
  anti-enumeração). **Titularidade antes de status**, sempre.
- Perfil oficial: somente cartão `ACTIVE` é autoridade (`CARD_NOT_ACTIVE`,
  PRD RN-09). Leitura de saldo/detalhes do titular independe do status (§7).
- `FARE_PROFILE_CHANGED` é **sinal de resultado, não exceção** (A-11):
  `ProfileResolutionResult {official_profile, source=CARD, verified=true,
  declared_profile, signal}`. Recálculo/invalidação pertencem a SPEC-003/004.
- `FareProfile` é enum próprio (mesmos valores do fare, sem import entre
  módulos); a fronteira com o Fare Engine é o valor string.
- Saldo `NUMERIC(12,2)`/`Decimal`, `CHECK >= 0`; mutação/ledger = SPEC-005.
- Sem operações de mudança de status nesta SPEC — os 4 estados são dados.
- **`status` é a única autoridade operacional; `expires_at` é informativo.**
  A SPEC não define regra funcional para `expires_at` (todos os comportamentos
  referenciam status — §14.7, PRD RN-09); a materialização de `EXPIRED` a
  partir da data é operação administrativa futura. Sem dupla autoridade
  ambígua: mudar isso exige documento.

## Integração com o Fare Engine

```text
identity.require_authenticated → customer_id
cards.resolve_official_fare_profile → ProfileResolutionResult
composição (SPEC-004) → FareService.calculate_trip_fare(profile.value, ...)
```

`cards` não importa `fare` nem `identity`; ninguém importa `cards`.

## Tools que este módulo suportará (SPEC-004)

`get_customer_cards`, `get_card_details`, `get_card_balance`.

## Tools proibidas

`change_fare_profile`, `change_balance`, `link_card`, `set_balance` — nem sob
nome equivalente.
