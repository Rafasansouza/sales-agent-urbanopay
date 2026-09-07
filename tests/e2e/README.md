# tests/e2e — Testes ponta a ponta

**Marcador:** `e2e`
**Requer infraestrutura:** sim (`make up` / `.\scripts\dev.ps1 up`)

## Escopo

A jornada completa de compra, conforme o critério de aceite do PRD §18:

> Um passageiro descreve uma necessidade em linguagem natural, recebe cálculo e
> recomendação, autentica-se, seleciona cartão, confirma uma compra, gera Pix
> de teste, tem o pagamento confirmado pelo provider/backend e recebe recarga
> ou bilhete simulado, com rastreabilidade completa.

Etapas cobertas (PRD §8):

1. entrada anônima e simulação tarifária;
2. autenticação simulada;
3. seleção de cartão e validação de titularidade;
4. recálculo com o perfil oficial do cartão;
5. Quote e Order;
6. confirmação explícita do passageiro;
7. aprovação humana quando a recarga excede R$ 200,00;
8. criação de Pix sandbox;
9. confirmação de pagamento pelo provider ou backend;
10. fulfillment: recarga ou emissão de bilhete;
11. comprovante e pós-venda.

## Regras

- Pagamento sempre via `FakePaymentProvider`. Nenhum dinheiro real, nenhuma
  credencial real (PRD §17).
- LLM sempre via `FakeLLMProvider`, para que a jornada seja determinística.
  O comportamento probabilístico é medido em `tests/evals/`.
- A rastreabilidade faz parte da asserção: `conversation_id`, `trace_id` e os
  IDs de Quote, Order, Payment e Fulfillment precisam correlacionar
  (PRD RF-18).
- Meta de referência: E2E Successful Journey Rate ≥ 90% (PRD §16).

## Estado atual

Vazio. Depende da implementação de SPEC-001 a SPEC-005.

⚠️ A jornada `TICKET_PURCHASE` está bloqueada por **A-05**: não existe SPEC de
catálogo, e o PRD §19 mantém pendentes as regras de Passe Diário e de Pacote 10
Viagens. Somente `RECHARGE` é implementável a partir dos documentos aceitos.

⚠️ A jornada com aprovação humana tem domínio e state machine definidos
(C-01 resolvida), mas depende de **A-07** — a superfície pela qual um humano
decide ainda não existe.
