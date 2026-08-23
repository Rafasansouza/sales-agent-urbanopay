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

## 10. Recomendação
Fluxo: necessidade -> catálogo -> cálculo -> comparação -> recomendação. Prioridade: aderência, elegibilidade, custo e simplicidade.

## 11. Confirmação
`ConfirmationResult`: `CONFIRMED`, `REJECTED`, `AMBIGUOUS`. Mensagem ambígua nunca dispara pagamento.

## 12. Prompt injection
Segurança principal é arquitetural. Mesmo que o modelo seja manipulado, tools/serviços/authorization/state machine devem impedir efeitos inválidos.

Testar tentativas de alterar perfil, saldo, desconto, autenticação, acessar terceiros, marcar pagamento, ignorar aprovação, alterar tarifa e executar SQL.

## 13. Contexto e PII
Não reenviar histórico inteiro indefinidamente. Preferir structured state, resumo e mensagens recentes. Evitar OTP, CPF completo, número completo do cartão, secrets e tokens.

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
