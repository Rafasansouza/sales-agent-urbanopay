# SPEC-004 — Sales Agent & Tools

**Projeto:** UrbanoPay Mobilidade  
**Dependências:** SPEC-001..003

## 1. Objetivo
Implementar o agente conversacional que compreende linguagem natural, preserva contexto, coleta dados faltantes, chama tools estreitas, recomenda, autentica, conduz Quote/Order/Payment e acompanha pós-venda sem possuir autoridade financeira.

## 2. Princípio
LLM: entende, pergunta, recomenda, explica e escolhe tool. Backend: valida, calcula, autentica, autoriza e altera estado.

## 3. ConversationState
Campos conceituais:
- `conversation_id`;
- `session_id`;
- `authenticated`;
- `current_intent`;
- customer context;
- perfil declarado/verificado;
- segmentos;
- tipo de viagem;
- frequência;
- produto/cartão selecionados;
- resultado tarifário;
- `quote_id`, `order_id`, `payment_id`;
- `current_stage`;
- `missing_fields`;
- último resultado de tool;
- flags de confirmação/aprovação;
- erro atual.

Stages:
`DISCOVERY`, `CALCULATION`, `RECOMMENDATION`, `AUTHENTICATION`, `CARD_SELECTION`, `QUOTE`, `ORDER_CONFIRMATION`, `APPROVAL`, `PAYMENT`, `FULFILLMENT`, `POST_SALE`, `COMPLETED`, `ERROR`.

### 3.1 Natureza do estado — cache de orquestração, nunca autoridade

Os campos da §3 são **referências de orquestração e valores de apresentação**,
nunca fonte de verdade de negócio. A lista acima descreve o que a conversa
precisa lembrar para não repetir perguntas — não o que o sistema considera
verdadeiro.

Regra normativa:

> **Antes de qualquer operação crítica, o backend relê o estado persistido.**

Nunca são autoridade no estado conversacional, e devem ser relidos do
PostgreSQL a cada uso: `Card.status`, saldo, `fare_profile` oficial,
`Order.status`, `Order.total`, `requires_approval`, `Payment.status`,
`Approval.status` e `Fulfillment.status`.

Quando um valor precisar ficar no estado apenas para compor a frase apresentada
ao cliente — por exemplo o total exibido em "você confirma R$ 100,00?" — ele é
marcado explicitamente como **não autoritativo** e jamais participa de decisão.

O estado mínimo efetivamente implementado é: `conversation_id`, `session_id`,
`phase`, `selected_card_id`, `current_quote_id`, `current_order_id`,
`current_payment_id`, `pending_confirmation` e contadores de orquestração.
`authenticated` e `customer_id` **não** são armazenados: são derivados da
sessão de `identity` a cada operação protegida, para que não exista uma segunda
autoridade de identidade.

CPF, OTP, hashes e segredos **nunca** entram no estado, em nenhuma fase.

## 4. Intents
- `DISCOVER_PRODUCT`;
- `CALCULATE_TRIP_COST`;
- `CALCULATE_RECHARGE_NEED`;
- `RECHARGE_CARD`;
- `BUY_TICKET`;
- `CHECK_BALANCE`;
- `CHECK_ORDER`;
- `CHECK_PAYMENT`;
- `CHECK_TICKET`;
- `GENERAL_TRANSPORT_HELP`.

## 5. Structured outputs
Usar schemas tipados para `IntentResult`, `TripExtractionResult`, `ConfirmationResult` etc. Resultado do modelo passa por Pydantic e validação do domínio.

## 6. Perguntas contextuais
Perguntar somente por campos ausentes. Não repetir informações que já estão no estado.

## 7. Tools permitidas
### Catálogo
- `search_products`;
- `get_product`.

### Fare
- `calculate_trip_fare`;
- `calculate_usage_cost`.

### Identity/Card
- `start_authentication`;
- `verify_otp`;
- `get_authentication_status`;
- `get_customer_cards`;
- `get_card_details`;
- `get_card_balance`.

### Order
- `create_quote`;
- `create_order`;
- `confirm_order`;
- `get_order`.

### Approval
- `get_approval_status` somente leitura.

### Payment
- `create_payment(order_id)`;
- `get_payment_status(order_id)`.

### Pós-venda
- `get_fulfillment_status`;
- `get_ticket`;
- `get_receipt`.

### 7.1 Tool registrada ≠ tool visível ao modelo

**Estar no catálogo não significa estar no schema entregue ao LLM.** A §7 lista
as operações que o produto autoriza; a visibilidade define *quem* pode
invocá-las. São dimensões independentes, e confundi-las amplia a superfície de
prompt injection sem necessidade.

Quatro níveis, normativos:

| Nível | Significado | Aparece no schema do LLM? |
|---|---|---|
| `LLM_VISIBLE` | o modelo escolhe chamar, e a chamada é conversacionalmente útil | **sim** |
| `GRAPH_ONLY` | invocada por node determinístico da orquestração; o modelo pode indicar intenção, nunca executar | não |
| `SENSITIVE_INPUT` | recebe CPF ou OTP; a entrada é interceptada deterministicamente **antes** do modelo (§13.1) | não |
| `BACKEND_ONLY` | jamais alcançável pela camada conversacional, sob nome algum | não — **não é registrada** |

O catálogo entregue ao modelo contém **exclusivamente** `LLM_VISIBLE`. Nome não
registrado — incluindo todo `BACKEND_ONLY` — resolve para `TOOL_NOT_AUTHORIZED`
(§20), sem execução, sem *fallback* dinâmico e sem resolução por reflexão.

### 7.2 Catálogo efetivo e contagem

Os nomes abaixo são os efetivamente implementáveis contra serviços
determinísticos existentes. `create_quote` da §7 materializa-se como
**`create_recharge_quote`**: `RECHARGE` é o único `operation_type` do MVP
(SPEC-003 §1.1), e um nome genérico prometeria um contrato que não existe.

**16 contratos registrados**, assim distribuídos:

| Visibilidade | Qtd. | Tools |
|---|--:|---|
| `LLM_VISIBLE` | **9** | `calculate_trip_fare`, `get_customer_cards`, `get_card_details`, `get_card_balance`, `get_order`, `get_approval_status`, `get_payment_status`, `get_fulfillment_status`, `get_receipt` |
| `GRAPH_ONLY` | **5** | `get_authentication_status`, `create_recharge_quote`, `create_order`, `confirm_order`, `create_payment` |
| `SENSITIVE_INPUT` | **2** | `start_authentication`, `verify_otp` |

`get_authentication_status` é `GRAPH_ONLY` por decisão: quem decide se a
jornada precisa parar para autenticar é código (§14 do PRD, matriz de SPEC-002
§9), e o resultado — um booleano de sessão — não acrescenta nada que o modelo
precise formular. Expô-lo só ampliaria a superfície.

Exigência de sessão, conforme a matriz de SPEC-002 §9:

| Exigência | Qtd. | Tools |
|---|--:|---|
| autenticação obrigatória | **12** | todas as de cartão, Quote, Order, aprovação, pagamento e pós-venda |
| autenticação opcional | **1** | `calculate_trip_fare` |
| sessão anônima | **3** | `start_authentication`, `verify_otp`, `get_authentication_status` |

`calculate_trip_fare` é o único caso de autenticação **opcional**, e por um
motivo específico: a simulação é pública (PRD RF-05), mas, havendo cartão
selecionado numa sessão autenticada, o perfil oficial do cartão precisa
prevalecer sobre o declarado (SPEC-002 §8, §15).

### 7.3 Tools declaradas e indisponíveis

Quatro nomes desta §7 **não possuem backend determinístico** e não podem ser
implementados sem inventar regra de negócio. Eles permanecem declarados,
resolvem para `TOOL_UNAVAILABLE` (§20) com o bloqueio nomeado, e **nunca** são
substituídos por comportamento fictício:

| Tool | Bloqueio |
|---|---|
| `search_products` | A-05 — módulo `catalog` sem SPEC |
| `get_product` | A-05 |
| `calculate_usage_cost` | A-06 — contrato de projeção de uso sem especificação |
| `get_ticket` | A-05 — `Ticket` não é materializado (SPEC-005 §9) |

Consequências operacionais, enquanto A-05 e A-06 estiverem abertas:

- `TICKET_PURCHASE` **não é jornada disponível**; o agente informa a
  indisponibilidade em vez de simular produto;
- o agente **não recomenda valor de recarga**. O valor é informado pelo
  cliente e validado pelo domínio (`INVALID_RECHARGE_AMOUNT`);
- a recomendação de produto de §10 fica restrita ao que existe: no MVP,
  "Recarga Livre".

### 7.4 Nomes que não são criados

Nenhuma tool é criada fora desta §7. Em particular, `fulfill_order`,
`reconcile_payment`, `approve_order`, `reject_order`, `process_payment_webhook`
e os comandos de recuperação da SPEC-005 §20.1 são `BACKEND_ONLY`: existem no
backend, e **não** são alcançáveis pela camada conversacional. `cancel_order`
existe no domínio (SPEC-003 §14, somente em `DRAFT`) e **não** é exposto,
porque não consta desta §7 — ampliar o catálogo é decisão de produto, não de
implementação.

## 8. Tools proibidas
- SQL arbitrário;
- shell;
- HTTP arbitrário;
- `set_balance`;
- `set_fare`;
- `set_fare_profile`;
- `set_order_status`;
- `set_payment_status`;
- `approve_payment`;
- `mark_payment_as_paid`;
- `apply_discount`;
- `override_rule`;
- `apply_recharge`;
- `issue_ticket`.

## 9. Mínimo privilégio
Preferir resource IDs e derivar dados críticos server-side. Ex.: `create_payment(order_id)` e não `create_payment(amount, customer, discount...)`.

### 9.1 Identificadores críticos não são escolhidos pelo modelo

Reduzir o argumento a um `order_id` não basta: se o modelo escolhe *qual*
`order_id`, ele ainda decide sobre dinheiro. Quando existe contexto confiável,
o identificador de uma operação crítica é **derivado**, não recebido.

| Operação | Origem do identificador | Ausência de contexto |
|---|---|---|
| `confirm_order` | `pending_confirmation.order_id` | `NO_PENDING_CONFIRMATION` |
| `create_payment` | `current_order_id` do contexto comercial já confirmado | `NO_PENDING_CONFIRMATION` |

Se a invocação tentar vincular um recurso diferente do que o contexto guarda, o
resultado é `CONFIRMATION_CONTEXT_MISMATCH` e **nenhum serviço é chamado**.

Nunca são aceitos como argumento, de nenhuma tool: `status`, `amount` de
pagamento, `balance`, `fare_profile` oficial, `payment_id`, `customer_id`,
`requires_approval` e **idempotency key**. O valor da recarga é a única
grandeza monetária que entra pela conversa — por ser escolha do cliente
(SPEC-003 §1.1) — e passa por schema **e** por validação de domínio.

`customer_id` é sempre derivado da sessão autenticada; a titularidade é
verificada no backend, em consulta única, independentemente do que o modelo
tenha proposto.

## 10. Recomendação
Fluxo: necessidade -> catálogo -> cálculo -> comparação -> recomendação. Prioridade: aderência, elegibilidade, custo e simplicidade.

## 11. Confirmação
`ConfirmationResult`: `CONFIRMED`, `REJECTED`, `AMBIGUOUS`. Mensagem ambígua nunca dispara pagamento.

## 12. Prompt injection
Segurança principal é arquitetural. Mesmo que o modelo seja manipulado, tools/serviços/authorization/state machine devem impedir efeitos inválidos.

Testar tentativas de alterar perfil, saldo, desconto, autenticação, acessar terceiros, marcar pagamento, ignorar aprovação, alterar tarifa e executar SQL.

## 13. Contexto e PII
Não reenviar histórico inteiro indefinidamente. Preferir structured state, resumo e mensagens recentes. Evitar OTP, CPF completo, número completo do cartão, secrets e tokens.

### 13.1 Entrada sensível é interceptada antes do modelo

"Evitar" não é contrato suficiente para CPF e OTP: numa autenticação
conversacional, o cliente **digita** esses valores. A defesa é de fluxo, não de
prompt.

Quando a fase da conversa indicar `AWAITING_DOCUMENT` ou `AWAITING_OTP`, a
mensagem do cliente é tratada por um **handler determinístico de entrada
sensível**, antes de qualquer chamada ao provider de LLM:

```text
mensagem sensível do usuário
  → handler determinístico (código)
    → tool SENSITIVE_INPUT → serviço de identity
      → histórico/estado redigido
        → somente então, se necessário, o LLM
```

No histórico e no estado destinados ao modelo, o valor é substituído pelos
marcadores `[DOCUMENT_REDACTED]` e `[OTP_REDACTED]`. Nunca trafegam para o
provider, e nunca são persistidos: CPF cru, OTP cru, hash de CPF, hash de OTP,
segredo ou token.

Não existe, e não pode ser criada, nenhuma operação que revele um OTP —
`get_otp` é proibida sob qualquer nome. A exposição controlada do OTP simulado
para a demonstração humana permanece **aberta em H-12** e não é resolvida por
esta SPEC.

## 14. Limites
Configurar:
- `max_turns_per_session`;
- `max_llm_calls_per_turn`;
- `max_tool_calls_per_turn`;
- `max_input_tokens`;
- `max_output_tokens`;
- `max_session_cost`.

Sugestão inicial: até 5 tool calls por turno. Meta média de <=10 LLM calls por venda concluída.

## 15. Observabilidade
Registrar model/provider, tokens, custo, latência, tools, erros, stage e intent, sempre com sanitização.

## 16. Evals
Dataset inicial sugerido:
- 50 intents;
- 50 extrações de trajeto;
- 30 recomendações;
- 30 confirmações;
- 50 adversariais.

Total inicial: 210 casos.

Metas: Intent >=95%, Trip Extraction >=98%, Recommendation >=90%, Critical Hallucination 0%.

## 17. Testes obrigatórios
Cobrir intents, extração, campos ausentes, contexto completo sem pergunta redundante, linha inválida, tarifa meia, divergência de perfil, cartão bloqueado, confirmação clara/ambígua, usuário dizendo “paguei”, prompt injection, cross-user, serviço tarifário indisponível, loop de tool, recomendação e pós-venda.

## 18. Autonomia
Alta: entender/perguntar/explicar. Média: recomendar/selecionar tool. Controlada: criar Quote/Order. Restrita: confirmar/criar payment. Nenhuma: alterar payment, saldo ou perfil.

## 19. Aceite
Agente usa tools oficiais, não repete perguntas, não inventa dados críticos, não possui capabilities genéricas, e nenhum teste adversarial permite ação crítica não autorizada.

## 20. Códigos de guarda da orquestração

Estes códigos pertencem à **camada de orquestração**, não ao domínio. Eles
descrevem por que uma invocação foi recusada antes de qualquer serviço ser
chamado. São distintos dos erros tipados de SPEC-001 §11, SPEC-002 §3,
SPEC-003 §16 e SPEC-005 §11.3, e **nenhum deles cria, altera ou encerra estado
financeiro**. Nenhum status HTTP é definido aqui.

| Código | Situação | Efeito |
|---|---|---|
| `TOOL_NOT_AUTHORIZED` | nome não registrado, ou registrado em nível não permitido ao chamador | nenhuma execução |
| `TOOL_UNAVAILABLE` | tool declarada na §7 e bloqueada por questão aberta (§7.3) | nenhuma execução; o bloqueio é nomeado |
| `TOOL_LIMIT_EXCEEDED` | excedido o teto de tool calls do turno (§14) | nenhuma execução |
| `NO_PENDING_CONFIRMATION` | o contexto de orquestração exigido pelo comando não existe (§9.1) | nenhuma execução |
| `CONFIRMATION_CONTEXT_MISMATCH` | a invocação tentou vincular recurso diferente do que o contexto guarda | nenhuma execução |
| `INTERNAL_ERROR` | exceção não mapeada | resultado de falha, sanitizado |

`NO_PENDING_CONFIRMATION` cobre os dois comandos com exigência de contexto:
`confirm_order` sem Order aguardando confirmação, e `create_payment` sem Order
confirmado no contexto comercial.

Falha estrutural de argumento **não** ganha código próprio: cada tool declara
para qual código semântico já existente ela traduz um argumento inválido ou
ausente — `CARD_NOT_ACCESSIBLE`, `ORDER_NOT_ACCESSIBLE`,
`INVALID_RECHARGE_AMOUNT`, `INVALID_FARE_PROFILE`, `EMPTY_TRIP`,
`INVALID_DOCUMENT`. Para identificadores, essa tradução é também a resposta
correta de anti-enumeração: um `card_id` malformado e um cartão de terceiro
são indistinguíveis para quem chama.

**Exceção desconhecida nunca vira sucesso.** Ela produz `ok = false`,
`INTERNAL_ERROR`, `next_action = STOP` e log sanitizado — sem stack trace na
resposta e sem argumento cru no log.

## 21. Envelope de resultado de tool

Toda tool devolve o mesmo envelope tipado. Resultado nunca é string solta
quando a aplicação possui semântica estruturada.

| Campo | Conteúdo |
|---|---|
| `ok` | booleano — a operação produziu o efeito pretendido |
| `result_type` | classe do resultado (ex.: `ORDER`, `PAYMENT`, `FARE_CALCULATION`, `ERROR`) |
| `code` | `OK`, ou código semântico de domínio, ou código de guarda (§20) |
| `data` | fatos estruturados, mínimos e já sanitizados |
| `next_action` | próximo passo determinístico sugerido à orquestração |

Regras de serialização: valor monetário como **string decimal**; timestamp em
ISO 8601; identificador como string opaca. Nunca atravessam o envelope: objeto
ORM, entidade de domínio inteira, CPF, OTP, hash, idempotency key, payload de
provider, credencial, `decided_by` de aprovação ou stack trace.

O envelope **não** carrega texto pronto para o usuário: o modelo transforma
fatos estruturados em linguagem. Prosa no envelope devolveria ao resultado a
ambiguidade que ele existe para eliminar.

## 22. Faseamento da implementação

A SPEC-004 é entregue em três etapas, para que a fronteira determinística não
fique refém de decisões arquiteturais ainda abertas.

| Etapa | Escopo | Pré-requisito |
|---|---|---|
| **1** | catálogo fechado, visibilidade, autorização, envelopes, presenters, guardas de contexto, vínculo de confirmação, política de idempotência, composition root, testes unit e de integração | nenhum |
| **2** | LangGraph, `LLMProvider`/`FakeLLMProvider`, prompt, limites de §14, evals de §16, persistência conversacional | **ADR-014** (ver H-11) |
| **3** | transporte HTTP de conversa, webhook HTTP, coordenador pós-pagamento (SPEC-005 §10.1), E2E, canal de OTP de demonstração | A-07 e H-12 para a demonstração humana |

Os limites de §14 e a configuração de provider pertencem à Etapa 2: fixá-los
antes de existir consumidor produziria configuração sem efeito.
