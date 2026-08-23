# PRD v1 — Assistente Inteligente de Vendas da UrbanoPay

**Projeto:** UrbanoPay Mobilidade  
**Versão:** 1.0  
**Status:** Discovery concluída / pré-implementação  
**Nome comercial do agente:** a definir

## 1. Visão do produto

A UrbanoPay Mobilidade é uma plataforma fictícia de mobilidade urbana voltada à venda digital de produtos tarifários, recarga de cartões e emissão de bilhetes simulados. O produto será um assistente conversacional de vendas capaz de compreender a necessidade do passageiro, recomendar o produto mais adequado, calcular custos de forma confiável, autenticar o cliente quando necessário, criar pedido, gerar pagamento Pix em ambiente de teste, acompanhar a confirmação do pagamento e concluir o fulfillment.

Princípio central:

> O modelo de linguagem decide o que dizer. O código decide o que pode ser feito.

A IA será responsável por interpretação, recomendação e comunicação. Tarifas, saldo, autenticação, estados transacionais, pagamentos, recargas e emissão de bilhetes serão controlados por código determinístico.

## 2. Cliente contratante fictício

**Ricardo Almeida — Diretor de Produtos Digitais da UrbanoPay Mobilidade.**

Objetivos do cliente:
- aumentar adoção e vendas digitais;
- reduzir abandono da jornada;
- permitir atendimento natural em vez de formulários rígidos;
- manter operação auditável e segura.

Principais preocupações:
- alucinação de tarifas;
- fraude ou manipulação de regras;
- ações financeiras acidentais;
- vazamento de dados;
- dificuldade de reconstruir uma falha;
- custo operacional da IA.

## 3. Personas

### 3.1 Passageiro recorrente
Usa transporte para trabalho/estudo com frequência, conhece recarga e quer estimativas semanais/mensais, saldo e conveniência.

### 3.2 Passageiro ocasional
Usa transporte eventualmente e precisa entender qual produto tem melhor custo-benefício.

### 3.3 Visitante
Não conhece o sistema tarifário e precisa de orientação de produto, trajeto e custo.

## 4. Problema

O passageiro precisa hoje conhecer previamente linhas, tarifas, produtos e regras. A proposta é permitir uma conversa natural, mantendo as decisões financeiras e transacionais fora do controle do LLM.

Exemplo:

```text
"Pego o 303 e depois metrô, tenho meia e vou trabalhar cinco dias indo e voltando. Quanto preciso carregar?"
```

O sistema deve transformar a necessidade em dados estruturados, consultar regras oficiais e retornar uma recomendação explicável.

## 5. Objetivos do MVP

O MVP deve demonstrar ponta a ponta:
1. atendimento em linguagem natural;
2. interpretação de intenção e trajeto;
3. cálculo tarifário determinístico;
4. recomendação comercial;
5. autenticação simulada;
6. consulta de cartões e saldo;
7. geração de Quote;
8. criação e confirmação de Order;
9. aprovação humana para recargas de alto valor;
10. Pix em ambiente sandbox/teste;
11. confirmação de pagamento pelo provider/backend;
12. recarga ou emissão de bilhete simulado;
13. comprovante simulado;
14. pós-venda;
15. observabilidade, testes e auditoria.

## 6. Escopo funcional

### 6.1 Modais e linhas
- ônibus 101: integral R$ 6,00 / meia R$ 3,00;
- ônibus 202: integral R$ 7,00 / meia R$ 3,50;
- ônibus 303: integral R$ 8,00 / meia R$ 4,00;
- ônibus 404: integral R$ 9,00 / meia R$ 4,50;
- ônibus 505: integral R$ 10,00 / meia R$ 5,00;
- metrô: integral R$ 10,00 / meia R$ 5,00.

### 6.2 Perfis tarifários
- `INTEGRAL`;
- `MEIA`.

O usuário pode declarar MEIA para uma simulação anônima, mas numa transação o perfil oficial do cartão prevalece.

### 6.3 Classificação de viagem
- `SINGLE`: exatamente um segmento suportado;
- `COMMON`: dois ou mais segmentos exclusivamente de ônibus, desconto 0%;
- `INTEGRATION`: pelo menos um ônibus e um metrô, desconto 15%.

A MEIA e o desconto de integração são cumulativos: primeiro aplica-se o perfil em cada segmento, soma-se o subtotal e depois aplica-se 15% quando houver integração.

### 6.4 Produtos do MVP
- Bilhete Unitário QR;
- Passe Diário;
- Pacote 10 Viagens;
- Recarga Livre.

Passe Mensal fica para versão futura. Integração é regra tarifária, não produto.

## 7. Autenticação e cartões

A conversa pode começar anonimamente. Operações transacionais exigem autenticação.

MVP de autenticação:
- identificação conceitual por CPF/login;
- OTP simulado;
- nenhuma dependência de SMS/WhatsApp real.

Status de cartão:
- `ACTIVE`;
- `BLOCKED`;
- `EXPIRED`;
- `CANCELLED`.

Dados sensíveis devem ser mascarados e não devem aparecer em logs/traces.

## 8. Jornada ponta a ponta

1. Entrada anônima.
2. Usuário descreve necessidade.
3. Agente identifica intent e extrai segmentos.
4. Usuário pode declarar perfil para simulação.
5. Sistema consulta catálogo/tarifas oficiais.
6. Fare Engine calcula.
7. Agente explica e recomenda.
8. Usuário demonstra intenção de compra/recarga.
9. Autenticação.
10. Consulta e seleção de cartão.
11. Validação de titularidade, status e perfil oficial.
12. Recalculo com perfil oficial.
13. Geração de Quote final.
14. Criação de Order em `DRAFT`.
15. Confirmação explícita do passageiro.
16. Se recarga > R$ 200,00, aprovação humana obrigatória.
17. Criação de Pix sandbox.
18. `PAYMENT_PENDING`.
19. Provider/backend confirma `APPROVED`.
20. Fulfillment: recarga ou bilhete.
21. Comprovante simulado.
22. Pós-venda.

## 9. Intents principais

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

## 10. Requisitos funcionais

### RF-01 — Conversação natural
Aceitar solicitações livres em português e preservar contexto relevante entre turnos.

### RF-02 — Extração de trajeto
Transformar linguagem natural em segmentos estruturados.

### RF-03 — Cálculo tarifário
Toda tarifa oficial deve vir do Fare Engine.

### RF-04 — Recomendação
Recomendar apenas produtos existentes e elegíveis, utilizando fatos oficiais.

### RF-05 — Simulação anônima
Permitir simular tarifas antes da autenticação.

### RF-06 — Autenticação
Exigir autenticação antes de transações e consultas protegidas.

### RF-07 — Cartões
Listar somente cartões pertencentes ao cliente autenticado.

### RF-08 — Perfil oficial
O perfil do cartão prevalece sobre o perfil declarado pelo usuário.

### RF-09 — Saldo
Consultar saldo oficial antes de afirmar saldo atual.

### RF-10 — Quote
Criar Quote com snapshot dos valores utilizados.

### RF-11 — Order
Criar Order a partir de Quote válida.

### RF-12 — Confirmação explícita
Nenhum pagamento pode ser iniciado sem confirmação clara do passageiro.

### RF-13 — Pix sandbox
Gerar pagamento Pix somente em ambiente de teste.

### RF-14 — Confirmação de pagamento
Mensagem do usuário não altera status financeiro.

### RF-15 — Fulfillment
Somente pagamento aprovado permite fulfillment.

### RF-16 — Pós-venda
Permitir consultar saldo, pedido, pagamento, ticket e comprovante quando aplicável.

### RF-17 — Aprovação humana
Recarga acima de R$ 200,00 exige aprovação operacional.

### RF-18 — Rastreabilidade
Toda jornada crítica deve ser correlacionável por IDs técnicos e de domínio.

## 11. Regras de negócio

- RN-01: tarifa oficial nunca vem da memória do modelo.
- RN-02: perfil oficial vem do cartão autenticado.
- RN-03: `COMMON` possui desconto 0%.
- RN-04: `INTEGRATION` possui desconto vigente inicial de 15%.
- RN-05: o LLM não altera estados transacionais diretamente.
- RN-06: dizer “paguei” não altera o pagamento.
- RN-07: somente `PaymentStatus.APPROVED` permite `Order PAID`.
- RN-08: operações financeiras e de fulfillment são idempotentes.
- RN-09: cartão não `ACTIVE` bloqueia operação correspondente.
- RN-10: recarga > R$ 200,00 entra em aprovação humana.
- RN-11: dados sensíveis são minimizados e mascarados.
- RN-12: falha de fulfillment depois do pagamento nunca cria nova cobrança automaticamente.

## 12. Estados principais do Order

Fluxo principal:

```text
DRAFT
→ CONFIRMED
→ PAYMENT_PENDING
→ PAID
→ FULFILLING
→ COMPLETED
```

Estados adicionais:
- `REQUIRES_APPROVAL`;
- `APPROVED` (aprovação administrativa, em enum separado do Payment);
- `FAILED`;
- `CANCELLED`;
- `EXPIRED`;
- `FULFILLMENT_FAILED`.

## 13. Segurança e guardrails

- nenhuma tool SQL genérica para o Sales Agent;
- nenhuma tool HTTP arbitrária;
- nenhuma alteração direta de saldo;
- nenhuma alteração direta de perfil;
- nenhuma alteração direta de status de pagamento;
- autenticação e autorização sempre server-side;
- PII mínima no contexto do LLM;
- secrets fora do código e fora dos prompts;
- testes adversariais de prompt injection;
- rate limiting em endpoints sensíveis;
- idempotência em operações críticas.

## 14. Observabilidade

Registrar, sem PII desnecessária:
- `conversation_id`;
- `trace_id`;
- execução do agente;
- model/provider;
- tokens;
- custo estimado;
- latência;
- tool calls;
- erros;
- correlação com Quote/Order/Payment/Fulfillment.

## 15. Tratamento de falhas

Toda falha deve terminar em estado conhecido e auditável.

Cenário crítico:

```text
Payment APPROVED
→ Fulfillment timeout/failure
```

Resultado esperado:
- pagamento permanece aprovado;
- não gerar nova cobrança;
- entrar em `FULFILLMENT_FAILED` ou reconciliação;
- operação deve ser idempotente.

## 16. Métricas de sucesso

- Intent Accuracy >= 95%;
- Trip Extraction Accuracy >= 98%;
- Fare Calculation Accuracy = 100%;
- Critical Hallucination Rate = 0%;
- Recommendation Accuracy >= 90%;
- E2E Successful Journey Rate >= 90%;
- latência conversacional P95 <= 3 s;
- operações determinísticas P95 <= 500 ms;
- AI Cost per Completed Sale <= US$ 0.05;
- média de LLM calls por venda concluída <= 10;
- Tool Success Rate >= 99%;
- Unauthorized Critical Actions = 0;
- ausência de PII em logs/traces críticos;
- duplicidade de efeito financeiro = 0.

## 17. Fora de escopo do MVP

- aplicativo móvel nativo;
- WhatsApp/SMS/OTP real;
- cartão de crédito/débito;
- dinheiro real;
- documento fiscal real;
- integração real com operadores de transporte;
- GPS, roteirização ou ETA;
- tarifa dinâmica por horário;
- gratuidade;
- vale-transporte corporativo;
- reembolso real;
- antifraude avançado;
- modelo próprio/fine-tuning;
- arquitetura multiagente complexa;
- Kubernetes;
- microservices distribuídos.

## 18. Critério E2E de aceite

Uma demonstração deve permitir que um passageiro descreva uma necessidade em linguagem natural, receba cálculo/recomendação, autentique-se, selecione cartão, confirme uma compra, gere Pix de teste, tenha pagamento confirmado pelo provider/backend e receba recarga ou bilhete simulado com rastreabilidade completa.

## 19. Decisões ainda pendentes

- nome comercial final do agente;
- identidade visual;
- regras detalhadas do Passe Diário;
- regras detalhadas do Pacote 10 Viagens;
- validade exata do QR/bilhete;
- TTL definitivo de Quote/Order;
- detalhes finais da interface administrativa de aprovação.

Essas lacunas não devem ser preenchidas silenciosamente pela implementação.
