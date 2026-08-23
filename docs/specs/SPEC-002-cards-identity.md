# SPEC-002 — Cards & Identity

**Projeto:** UrbanoPay Mobilidade  
**Status:** Proposta para implementação

## 1. Objetivo

Implementar identificação, autenticação simulada, sessões, cartões, titularidade, perfil tarifário oficial, saldo e proteção de PII.

Regra central:

> Durante uma transação, `card.fare_profile` é a fonte oficial do perfil tarifário.

## 2. Entidades

### Customer
Campos conceituais:
- `customer_id`;
- `name`;
- `cpf`;
- `email`;
- `phone`;
- `status`;
- timestamps.

Status: `ACTIVE`, `BLOCKED`, `INACTIVE`.

CPF deve ser normalizado e único. O sistema deve usar IDs internos nas integrações e traces sempre que possível.

### OTPChallenge
- `challenge_id`;
- `customer_id`;
- `otp_hash`;
- `expires_at`;
- `attempts`;
- `max_attempts`;
- `status`.

Status: `PENDING`, `VERIFIED`, `EXPIRED`, `BLOCKED`.

OTP nunca deve aparecer em logs/traces. Sugestão inicial: expiração 5 minutos, máximo 5 tentativas, configurável.

### Session
- `session_id`;
- `customer_id`;
- `authenticated`;
- `created_at`;
- `expires_at`.

Operação transacional exige `authenticated=true`. Sugestão inicial: 30 minutos de inatividade, configurável.

### Card
- `card_id`;
- `customer_id`;
- `card_number`;
- `fare_profile`;
- `balance`;
- `status`;
- `expires_at`;
- timestamps.

Perfis: `INTEGRAL`, `MEIA`.

Status: `ACTIVE`, `BLOCKED`, `EXPIRED`, `CANCELLED`.

## 3. Identificação

MVP por CPF/login conceitual:
1. normalizar;
2. validar formato;
3. procurar customer;
4. verificar status.

Resultados tipados:
- `CUSTOMER_FOUND`;
- `CUSTOMER_NOT_FOUND`;
- `INVALID_DOCUMENT`;
- `CUSTOMER_BLOCKED`.

## 4. OTP simulado

Mesmo sendo simulado, manter:
- hash;
- expiração;
- máximo de tentativas;
- uso único;
- nenhuma exposição em telemetry.

## 5. Titularidade

Para qualquer cartão protegido:

```text
card.customer_id == session.customer_id
```

Se não pertencer ao usuário, responder `CARD_NOT_ACCESSIBLE` sem revelar se o cartão existe.

## 6. Mascaramento

Nunca retornar número completo para o agente. Exemplo:

```text
****4821
```

Tools trabalham com `card_id` + `masked_number` quando necessário.

## 7. Saldo

Saldo usa `Decimal/NUMERIC`, nunca float. `get_card_balance` exige:
- sessão autenticada;
- titularidade;
- cartão acessível.

## 8. Perfil declarado vs oficial

Simulação anônima:
```json
{"fare_profile":"MEIA","source":"USER_DECLARED","verified":false}
```

Após autenticação:
```json
{"fare_profile":"INTEGRAL","source":"CARD","verified":true}
```

Se houver divergência, retornar evento/erro semântico `FARE_PROFILE_CHANGED` e recalcular antes de Quote/Order.

## 9. Matriz de autorização

| Ação | Anônimo | Autenticado |
|---|---:|---:|
| Consultar catálogo | Sim | Sim |
| Simular tarifa | Sim | Sim |
| Listar cartões | Não | Próprios |
| Consultar saldo | Não | Próprio |
| Usar perfil oficial | Não | Próprio |
| Criar Order | Não | Sim |
| Recarga | Não | Sim |
| Consultar pedidos | Não | Próprios |

## 10. Tools permitidas ao agente
- `start_authentication`;
- `verify_otp`;
- `get_authentication_status`;
- `get_customer_cards`;
- `get_card_details`;
- `get_card_balance`.

## 11. Tools proibidas
- `authenticate_as`;
- `change_customer`;
- `change_fare_profile`;
- `change_balance`;
- `link_card`.

## 12. PII
Considerar sensível:
- CPF;
- nome/e-mail/telefone;
- número completo do cartão;
- saldo e histórico;
- dados de pagamento.

Aplicar minimização, masking e exclusão de traces quando necessário.

## 13. Seed fictício sugerido
- Mariana — `****4821` — MEIA — ACTIVE — saldo 21.50;
- Lucas — `****1257` — INTEGRAL — ACTIVE — saldo 42.00;
- Camila — `****7934` — INTEGRAL — BLOCKED — saldo 10.00;
- Cliente 4 — dois cartões ACTIVE, um MEIA e um INTEGRAL.

## 14. Testes obrigatórios
1. autenticação válida;
2. OTP inválido;
3. OTP expirado;
4. máximo de tentativas;
5. cartão ACTIVE;
6. cartão BLOCKED;
7. cartão EXPIRED;
8. cartão de outro usuário;
9. usuário declara MEIA, cartão INTEGRAL;
10. usuário declara INTEGRAL, cartão MEIA;
11. prompt injection tentando acessar/alterar cartão;
12. sessão expirada.

## 15. Integração com Fare Engine

Fluxo oficial:

```text
perfil declarado
→ simulação
→ autenticação
→ Card Service
→ perfil oficial
→ Fare Engine novamente
→ Quote oficial
```

## 16. Hierarquia de confiança

```text
mensagem do usuário
< contexto da IA
< identidade da sessão
< dados oficiais do cartão
< regras determinísticas
```

## 17. Aceite
- autenticação simulada funcional;
- sessão protegida;
- titularidade server-side;
- perfil oficial não alterável pelo agente;
- saldo exato;
- masking;
- PII fora de telemetry;
- todos os testes críticos aprovados.
