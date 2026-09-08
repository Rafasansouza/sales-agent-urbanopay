# SPEC-005 — Fulfillment & Post-Sale

**Projeto:** UrbanoPay Mobilidade  
**Dependências:** SPEC-001..004

## 1. Objetivo
Executar a entrega após pagamento aprovado: recarga, bilhete fictício, ledger, idempotência, reconciliação, comprovante e consultas de pós-venda.

### 1.1 Escopo do MVP

O único `fulfillment_type` implementável é **`RECHARGE`**. `TICKET_ISSUANCE` depende de catálogo de produtos sem especificação (A-05) e da validade de QR/bilhete, que o PRD §19 mantém pendente — permanece fora do escopo.

Consequências deste recorte, todas explícitas:

- o efeito de `RECHARGE` é **inteiramente local**: crédito, ledger, status e comprovante vivem no mesmo PostgreSQL. Não existe chamada externa, portanto não existe timeout nem resultado inconclusivo de provider neste fluxo;
- **não existe scheduler nem job em execução** nesta versão. Existe o comando `fulfill_order(order_id)` e consultas de recuperação para uso futuro da camada de composição;
- `Ticket` não é materializado (§9).

## 2. Princípio
`PAYMENT APPROVED` e `FULFILLMENT COMPLETED` são eventos distintos. Falha de fulfillment nunca cria nova cobrança automaticamente.

Texto do usuário — por exemplo "eu já paguei" — **nunca autoriza fulfillment**. A autoridade de entrada é o estado persistido do Order.

## 3. Tipos
- `RECHARGE`;
- `TICKET_ISSUANCE`.

## 4. Entidades

Entidades conceituais desta SPEC:

- `Fulfillment`;
- `RechargeTransaction`;
- `CardLedgerEntry`;
- `Ticket`;
- `Receipt`;
- `FulfillmentAttempt`;
- `ReconciliationRecord`.

### 4.1 Materialização no escopo `RECHARGE`

Nem toda entidade conceitual precisa de tabela própria neste recorte. A decisão está registrada em **A-16** e vale **somente para `RECHARGE`**; deve ser revista quando `TICKET_PURCHASE` ou qualquer efeito externo for implementado.

| Entidade | Materializada | Justificativa |
|---|---|---|
| `Fulfillment` | ✅ `fulfillments` | autoridade detalhada do processo |
| `CardLedgerEntry` | ✅ `card_ledger_entries` | prova física de crédito único |
| `Receipt` | ✅ `receipts` | exigido por §13 |
| `RechargeTransaction` | ❌ | **representada pelo `CardLedgerEntry` de tipo `RECHARGE_CREDIT`**: em `RECHARGE` são 1:1, e os campos que a distinguiriam (`balance_before`, `balance_after`, chave de idempotência) são naturais na entrada de ledger. Duas tabelas com o mesmo ciclo de vida criariam duas verdades a sincronizar |
| `FulfillmentAttempt` | ❌ | não existe laço de retentativa: o efeito é uma transação local que acontece por inteiro ou não acontece. Ganha consumidor quando existir etapa externa |
| `ReconciliationRecord` | ❌ | a reconciliação deste escopo é **detecção**, expressa como consulta sobre evidência persistida (§12), não como registro próprio |
| `Ticket` | ❌ | bloqueado por A-05 (§9) |

## 5. Estados do Fulfillment
- `PENDING`;
- `PROCESSING`;
- `COMPLETED`;
- `FAILED`;
- `RECONCILIATION_REQUIRED`.

Pré-condição: `Order PAID` e Payment aprovado.

### 5.1 Transições

```text
(inexistente) ──> PENDING                  (criação, sob Order PAID)
PENDING       ──> PROCESSING               (início da aplicação do efeito)
PROCESSING   ─┬─> COMPLETED                (efeito aplicado e comitado)
              ├─> FAILED                   (falha conhecida, sem efeito)
              └─> RECONCILIATION_REQUIRED  (evidência inconsistente, sem efeito)
FAILED                    ──> PROCESSING   (nova chamada EXPLÍCITA de fulfill_order)
RECONCILIATION_REQUIRED   ──> PROCESSING   (nova chamada EXPLÍCITA, após correção do dado)
COMPLETED                                  (terminal)
```

Em `RECHARGE`, `PENDING → PROCESSING → COMPLETED` ocorre **dentro da mesma transação PostgreSQL** e portanto não é externamente observável. Isso é deliberado: criar commits intermediários apenas para tornar os estados visíveis introduziria janelas de estado financeiro parcial. Os estados existem com transição válida no domínio e passam a ser observáveis quando o fulfillment tiver etapa externa.

Reentrada a partir de `FAILED` ou `RECONCILIATION_REQUIRED` acontece **somente por comando explícito**, nunca por retentativa automática.

`COMPLETED` é terminal. A detecção de inconsistência sobre um fulfillment já `COMPLETED` (§12) **reporta** o achado; não o transiciona, porque `Order COMPLETED` também é terminal em SPEC-003 §14 e regredir estado terminal contradiz a máquina de estados aceita.

### 5.2 Relação com o estado do Order

`Fulfillment` é a autoridade **detalhada** do processo; o Order mantém o estado **coarse-grained** da jornada. O mapeamento é normativo:

| Fulfillment | Order |
|---|---|
| `PENDING` | `FULFILLING` |
| `PROCESSING` | `FULFILLING` |
| `COMPLETED` | `COMPLETED` |
| `FAILED` | `FULFILLMENT_FAILED` |
| `RECONCILIATION_REQUIRED` | `FULFILLMENT_FAILED` |

Os caminhos correspondentes existem na máquina de estados do Order (SPEC-003 §14): `PAID → FULFILLING → COMPLETED | FULFILLMENT_FAILED`.

A reentrada de §5.1 exigiu **uma** aresta nova no Order, acrescentada à SPEC-003 §14 na mesma data: `FULFILLMENT_FAILED → FULFILLING`. Sem ela, o mapeamento acima deixaria o Order em estado terminal e um cartão reativado nunca poderia receber o crédito de um Order já pago. A reentrada é sempre por comando explícito e não gera nova cobrança.

A jornada do Order termina em `COMPLETED`, após `Fulfillment COMPLETED`.

## 6. Recarga
Fluxo: Order PAID -> validar cartão -> RechargeTransaction -> ledger -> atualizar saldo -> COMPLETED.

`RechargeTransaction`: IDs, amount, balance_before, balance_after, status, idempotency_key, timestamps.

### 6.1 Autoridade de entrada

O comando é `fulfill_order(order_id)`. Ele **não recebe** `card_id`, `amount`, `payment_id`, perfil tarifário nem qualquer estado informado pelo usuário: tudo é derivado do estado persistido.

- `card_id` vem de `order.card_id` — o cartão congelado no Order, nunca outro;
- `amount` é exatamente `order.total` — a tarifa **não** é recalculada e nenhum valor externo é aceito;
- `payment_id` vem do `Payment APPROVED` associado ao Order.

### 6.2 Transação

O sucesso é local e atômico (§7). Sequência:

```text
BEGIN
  lock Order                      -> valida PAID
  verificar ledger RECHARGE_CREDIT existente
    -> se existe: replay seguro, devolve o resultado persistido, nenhum novo crédito
  obter Payment APPROVED do Order -> payment_id para auditoria (leitura)
  lock Card                       -> valida ACTIVE, lê saldo
  obter/criar Fulfillment         -> PENDING, sob lock
  Fulfillment PENDING -> PROCESSING
  amount = order.total
  INSERT CardLedgerEntry RECHARGE_CREDIT
  UPDATE cards.balance
  Fulfillment -> COMPLETED
  Order       -> COMPLETED
  INSERT Receipt
COMMIT
```

Qualquer falha antes do commit desfaz **tudo** junto: ledger, saldo, fulfillment, Order e comprovante. Nenhum estado financeiro parcial sobrevive.

### 6.3 Ordem de lock

A ordem global fica `Order → Approval → Payment → Card → Fulfillment`, estendendo a de SPEC-003. No fluxo de recarga: **`lock Order` → `lock Card` → `lock Fulfillment`**. O Payment é leitura, porque `APPROVED` é terminal e imutável.

O `Card` precede o `Fulfillment` por **necessidade técnica**, não por preferência: `fulfillments.card_id` e `card_ledger_entries.card_id` são chaves estrangeiras, e o PostgreSQL adquire `FOR KEY SHARE` na linha do cartão no momento do `INSERT`. Travar o cartão depois desses inserts deixa duas transações concorrentes sobre o mesmo cartão com lock compartilhado, ambas tentando elevá-lo a exclusivo — **deadlock**, observado em teste de integração com a ordem inversa.

Nenhuma transação da SPEC-003 trava `Card` ou `Fulfillment`, então a extensão é compatível com o código existente.

## 7. Ledger
Toda alteração de saldo gera `CardLedgerEntry`. MVP usa `RECHARGE_CREDIT`. Atualização do ledger, saldo e status deve ocorrer na mesma transação de banco.

Concorrência deve utilizar lock/transação apropriados. Dinheiro usa Decimal/NUMERIC.

### 7.1 Campos e invariantes

Campos: `id`, `fulfillment_id`, `order_id`, `card_id`, `entry_type`, `amount`, `currency`, `balance_before`, `balance_after`, `created_at`.

O ledger é **imutável**: existe `INSERT`, não existe `UPDATE` nem `DELETE`. Invariantes, materializadas como constraint sempre que praticável:

- `amount > 0`;
- `currency = 'BRL'`;
- `balance_before >= 0` e `balance_after >= 0`;
- `balance_after = balance_before + amount`;
- **no máximo um `RECHARGE_CREDIT` por `order_id`**.

## 8. Idempotência
Chave conceitual `recharge:{order_id}`. Reprocessar mesmo Order retorna resultado existente; nunca duplica crédito.

### 8.1 Chave natural, sem registro transversal

A idempotência deste fluxo **não** usa a tabela `idempotency_records` da SPEC-003 §11. A chave é natural e forte — o próprio Order —, e a garantia é física: índice único parcial de `RECHARGE_CREDIT` por `order_id`. Manter um segundo mecanismo para o mesmo fato criaria duas verdades a sincronizar, exatamente o problema registrado em A-15.

- **replay legítimo** — mesmo Order já concluído: não credita, não emite novo comprovante, devolve o resultado anterior;
- **conflito** — efeito divergente para o mesmo Order: `EFFECT_CONFLICT`, sem nenhum efeito novo.

## 9. Ticket
Campos: `ticket_id`, `order_id`, `customer_id`, `product_id`, `status`, `issued_at`, `valid_from`, `valid_until`, `qr_token`.

Status: `ACTIVE`, `USED`, `EXPIRED`, `CANCELLED`. QR é fictício e deve conter token opaco, nunca PII.

Emissão também é idempotente, respeitando `quantity` do OrderItem.

⚠️ **Não materializado** (§1.1, §4.1). `product_id` exige o catálogo bloqueado por **A-05**, e `valid_from`/`valid_until` dependem da validade de bilhete que o PRD §19 mantém pendente. Nenhuma tabela `tickets` é criada enquanto não houver consumidor real: `TICKET_ISSUANCE` é recusado explicitamente com `UNSUPPORTED_FULFILLMENT_TYPE`, nunca tratado com comportamento fictício.

A idempotência por `quantity` do OrderItem também fica pendente: `RECHARGE` tem exatamente um efeito por Order, enquanto bilhete admite N — a modelagem de "um Fulfillment por Order" (§19) precisará ser revista nesse momento.

## 10. Independência do agente
Fulfillment é iniciado pelo backend após pagamento; continua mesmo se usuário fechar o navegador ou LLM ficar indisponível.

### 10.1 Quem invoca `fulfill_order` — seam pós-pagamento

A §10 exigia "iniciado pelo backend" sem nomear o iniciador, e a §1.1 removeu
scheduler e job desta versão. O resultado era um vão: `Order PAID` existia e
nada chamava `fulfill_order`. A política abaixo fecha esse vão (**A-19**).

**Todo caminho de backend que faça o estado convergir para `Payment APPROVED`
⇒ `Order PAID` deve, depois do commit financeiro, entregar o `order_id` a uma
camada de composição `BACKEND_ONLY`, responsável por chamar
`fulfill_order(order_id)`.**

Vale igualmente para os caminhos que aplicam `APPROVED`: o webhook do provider,
a consulta ativa de reconciliação, e qualquer outro caminho de backend
autorizado que venha a existir.

Restrições que a política preserva:

- **o Sales Agent não chama `fulfill_order`** — não é tool em nível algum
  (SPEC-004 §7.4);
- **`payments` não importa `fulfillment`.** Inverter isso criaria ciclo:
  `fulfillment` já lê `payments` para validar `Payment APPROVED` (§11.1). O
  coordenador vive **acima** dos dois módulos, e nenhum dos dois conhece o
  outro nessa direção;
- o disparo acontece **após** o commit financeiro, nunca dentro da transação
  que aprova o pagamento: entrega e cobrança são eventos distintos (§2);
- o disparo **não** é retentativa automática. Se o fulfillment não puder ser
  executado, o caso não se perde: a capacidade de recuperação da §20.1 localiza
  `Order PAID` sem `Fulfillment COMPLETED`, e a reentrada continua sendo por
  comando explícito (§5.1).

```text
provider  → webhook / consulta ativa
            → PaymentService  (Payment APPROVED, Order PAID, commit)
                → coordenador de composição (BACKEND_ONLY)
                    → FulfillmentService.fulfill_order(order_id)
```

**Estado:** decisão registrada; **implementação pendente**. O coordenador não
existe nesta versão — hoje `fulfill_order` só é alcançado por chamada explícita
de backend, que é o que os testes fazem.

**Forma do coordenador.** Composição **em processo** é suficiente e é o que
esta política prescreve: uma função que, depois do commit financeiro, chama
`fulfill_order(order_id)`. Isso não cria fronteira arquitetural nova — é a
comunicação interna que ADR-001 já prevê — e portanto não exige ADR.

Exige ADR próprio, **antes** da implementação, apenas se for introduzida
fronteira real: fila ou broker, worker ou processo separado, scheduler, ou
qualquer mecanismo assíncrono **persistente** (outbox, tabela de jobs). Cada um
desses acrescenta infraestrutura, estado durável e modo de falha próprio — e a
§1.1 desta SPEC declara explicitamente que nenhum deles existe nesta versão.

## 11. Falhas
- falha conhecida antes de efeito => `FAILED`;
- falha na transação local => rollback;
- resultado externo desconhecido => `RECONCILIATION_REQUIRED`;
- nunca retry cego em outcome desconhecido.

Classificar erros: `RETRYABLE`, `NON_RETRYABLE`, `UNKNOWN_OUTCOME`.

Sugestão inicial: máximo 3 retries automáticos para erros comprovadamente retryable; depois revisão manual.

⚠️ Em `RECHARGE` **não existe retentativa automática**: o efeito é uma transação local que acontece por inteiro ou não acontece, e não há resultado externo a interpretar. O limite de três retentativas permanece como orientação para quando existir etapa externa.

### 11.1 Order `PAID` sem `Payment APPROVED`

`Order PAID` é a pré-condição de entrada, mas o Payment `APPROVED` associado é lido para validar a invariante da SPEC-003 (`Order PAID ⇔ existe Payment APPROVED`) e para obter `payment_id` de auditoria.

Se o Order está `PAID` e **não** existe Payment `APPROVED`, isso é inconsistência de dados, não caso de negócio. Resultado obrigatório:

- **zero crédito**, zero ledger financeiro, zero comprovante;
- `Fulfillment → RECONCILIATION_REQUIRED`;
- `Order → FULFILLMENT_FAILED`.

Essa situação **nunca** é "corrigida" aplicando crédito às cegas.

### 11.2 Cartão não `ACTIVE` depois do pagamento

O cartão do Order pode não estar mais `ACTIVE` quando o fulfillment executa. Política desta versão:

- **zero crédito**, zero ledger financeiro, zero comprovante;
- `Fulfillment → RECONCILIATION_REQUIRED`;
- `Order → FULFILLMENT_FAILED`;
- **nenhuma** retentativa automática, **nenhuma** troca automática de cartão, **nenhum** estorno, **nenhuma** nova cobrança.

O estado é `RECONCILIATION_REQUIRED`, e não `FAILED`, deliberadamente: os documentos aceitos não sustentam que `BLOCKED`, `EXPIRED` e `CANCELLED` sejam todos irreversíveis, então classificar a falha como definitiva seria decidir regra de negócio sem requisito. Um cartão reativado permite reentrada por comando explícito.

⚠️ A superfície administrativa que resolve esse caso — inclusive a decisão sobre estorno — **não existe** e está registrada em **A-18**. É a situação em que o dinheiro entrou e a entrega é impossível.

### 11.3 Erros tipados

Esta SPEC não trazia lista de códigos, ao contrário da SPEC-003 §16. Os códigos abaixo foram aprovados e estão registrados em **A-17**. Nenhum status HTTP é definido aqui.

| Código | Situação |
|---|---|
| `ORDER_NOT_PAID` | Order não está `PAID`: zero efeito |
| `FULFILLMENT_NOT_FOUND` | consulta de fulfillment inexistente |
| `EFFECT_CONFLICT` | efeito divergente para o mesmo Order |
| `RECONCILIATION_REQUIRED` | evidência inconsistente; exige análise humana |
| `RECEIPT_NOT_AVAILABLE` | comprovante consultado antes de `COMPLETED` |
| `UNSUPPORTED_FULFILLMENT_TYPE` | tipo fora do escopo do MVP (§1.1) |

Reutilizados de SPECs anteriores, sem código novo: **`CARD_NOT_ACTIVE`** (SPEC-002) para cartão inutilizável, e `ORDER_NOT_ACCESSIBLE` nas consultas de pós-venda feitas pelo cliente.

`CARD_NOT_ACCESSIBLE` **não** é fluxo normal do fulfillment: o `card_id` é derivado do Order, nunca recebido do usuário, portanto não existe superfície de enumeração a proteger neste comando.

## 12. Reconciliação
`ReconciliationRecord`: id, fulfillment, reason, status, attempts, last_checked_at, resolved_at, resolution.

Status: `PENDING`, `RESOLVED`, `MANUAL_REVIEW`, `FAILED`.

No MVP local, job pode procurar `Order PAID` sem fulfillment conhecido e comparar RechargeTransaction/Ledger.

### 12.1 Detecção, nunca reparo financeiro automático

Nesta versão a reconciliação é **detecção** sobre evidência persistida, sem tabela própria (§4.1) e sem job em execução (§1.1). **Nenhuma reconciliação cria crédito novo apenas porque "parece faltar".**

| Evidência | Encaminhamento |
|---|---|
| `Order PAID` sem fulfillment `COMPLETED` | elegível para nova chamada de `fulfill_order` |
| `Fulfillment COMPLETED` com ledger **ausente** | inconsistência grave; **reporta** o achado; não credita e não regride o estado terminal (§5.1) |
| Ledger existente com fulfillment **não** `COMPLETED` | fecha o estado a partir da evidência persistida; **nunca** executa segundo crédito |
| `Order PAID` sem `Payment APPROVED` | `RECONCILIATION_REQUIRED`, zero efeito (§11.1) |
| Cartão não `ACTIVE` após pagamento | `RECONCILIATION_REQUIRED`, zero efeito (§11.2) |

## 13. Comprovante
Gerar somente após `COMPLETED`, com indicação clara de documento simulado/sem validade fiscal ou como bilhete real.

### 13.1 Campos e privacidade

Um comprovante por Order, emitido **apenas** no sucesso atômico do fulfillment. Campos: `receipt_id`, `order_id`, `payment_id`, `fulfillment_id`, `card_last4`, `amount`, `currency`, `operation_type`, `document_kind`, `disclaimer_version`, `issued_at`.

`document_kind` é `SIMULATED_NON_FISCAL`. O texto do aviso é renderizado a partir de constante versionada, e `disclaimer_version` fica persistida para que o documento histórico continue explicitamente não fiscal mesmo se a redação mudar.

Nunca persistir CPF, OTP, nome desnecessário, número completo de cartão ou payload de provider. `card_last4` é snapshot suficiente para apresentação mascarada — o número completo não existe no sistema (SPEC-002).

## 14. Pós-venda
Permitir, autenticado e autorizado:
- saldo;
- pedido;
- payment status;
- fulfillment status;
- ticket;
- receipt.

## 15. Tools permitidas ao Sales Agent
- `get_fulfillment_status`;
- `get_ticket`;
- `get_receipt`;
- `get_card_balance`.

Todas somente leitura e todas filtradas por titularidade.

⚠️ **`get_ticket` está declarada e indisponível.** `Ticket` não é materializado
(§9, §4.1) enquanto **A-05** estiver aberta, então a tool não pode ter backend:
ela resolve para `TOOL_UNAVAILABLE` com o bloqueio nomeado (SPEC-004 §7.3), e
**nunca** é substituída por comportamento fictício. Permitir a tool sem a
entidade era contradição entre esta §15 e a §9; o registro acima a elimina sem
inventar produto.

`fulfill_order` **não** aparece nesta lista e não é tool do agente em nível
algum: o disparo é responsabilidade da camada de composição de backend
(§10.1).

## 16. Tools proibidas
- `apply_recharge`;
- `issue_ticket`;
- `retry_fulfillment`;
- `reconcile_fulfillment`;
- `set_ticket_status`;
- `set_balance`.

## 17. Observabilidade
Correlacionar `conversation_id`, `trace_id`, customer/card/order/payment/fulfillment/recharge/ticket/receipt IDs. Não registrar CPF completo, cartão completo, OTP ou QR token sensível.

## 18. Métricas
- fulfillments started/completed/failed;
- recharges completed;
- tickets issued;
- retry count;
- reconciliation count/success;
- fulfillment latency;
- `duplicate_fulfillment_effects = 0`;
- `paid_orders_without_known_fulfillment_state = 0`.

## 19. Invariantes
1. nenhum fulfillment sem Order PAID;
2. nenhuma recarga sem Payment APPROVED;
3. um Order de recarga produz no máximo um efeito financeiro;
4. saldo corresponde ao ledger;
5. ticket não excede quantidade comprada;
6. failure não gera nova cobrança;
7. comprovante de sucesso somente após COMPLETED;
8. LLM nunca altera saldo.

## 20. Recuperação
Estados críticos ficam persistidos. Após restart, localizar `PAID`, `FULFILLING` e `RECONCILIATION_REQUIRED`. Job conceitual `find_stale_fulfillments` pode recuperar operações paradas.

### 20.1 Sem scheduler nesta versão

`find_stale_fulfillments` permanece **conceitual**: não existe scheduler nem job em execução (§1.1). O que existe é a **capacidade de consulta** — localizar `Order PAID` sem `Fulfillment COMPLETED` — exposta como port de recuperação para uso futuro da camada de composição.

A consulta é cross-aggregate e por isso **não** vive no repository de nenhum agregado: um repository que consultasse Orders para decidir sobre fulfillments misturaria responsabilidades. Ela é um port próprio de recuperação.

## 21. Testes obrigatórios
Cobrir recarga normal, sem pagamento, cartão bloqueado, duplicidade, concorrência, rollback, failure depois de payment, retry seguro, unknown outcome, ticket, ticket duplicado, cross-user, consulta saldo, prompt injection, valor adulterado, receipt, reconciliação positiva/negativa e restart.

## 22. Aceite
Somente Orders pagos são entregues, saldo/ledger são atômicos e idempotentes, tickets não duplicam, falhas são conhecidas/reconciliáveis e pós-venda usa fontes oficiais.
