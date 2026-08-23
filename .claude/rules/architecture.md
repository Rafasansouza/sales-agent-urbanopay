# Regra — Arquitetura

Fonte: ADR-001, ADR-002, ADR-003, ADR-005, ADR-006.

## Hierarquia documental

`PRD → SPEC → ADR → Agent Harness → Implementação`.

Código não contradiz documento aceito. Em caso de divergência entre código,
SPEC, PRD e ADR, **reporte o conflito antes de alterar comportamento**.

## Monólito modular

Fronteiras declaradas em ADR-001: `agent`, `catalog`, `fare`, `identity`,
`cards`, `orders`, `payments`, `approvals`, `fulfillment`, `tickets`,
`postsale`, `observability`.

- Um módulo não acessa internals nem tabelas de outro módulo livremente.
- A comunicação entre módulos usa a interface pública do módulo de destino.
- Dependências circulares entre módulos são defeito.
- Eventos internos podem existir sem broker externo.
- Extração de serviço só por necessidade real, e sempre via ADR.

## Estratificação obrigatória de cada módulo

```text
modules/<dominio>/
├── domain/          entidades, value objects, erros tipados, regras puras
├── application/     use cases e serviços que orquestram o domínio
└── infrastructure/  repositórios, adaptadores, integrações
```

Regras de direção de dependência:

- `domain` não importa `application` nem `infrastructure`.
- `application` não importa detalhes de `infrastructure`; depende de portas.
- `infrastructure` implementa portas definidas em `domain` ou `application`.
- A camada HTTP (`api/`) depende de `application`, nunca de `infrastructure`
  diretamente.

## Camada HTTP

Fonte: ADR-006.

- Routers finos: validar entrada, delegar, formatar saída. Sem regra de negócio.
- Versionamento em `/api/v1`.
- Schemas HTTP não precisam ser os mesmos objetos de domínio ou de ORM.
- `async` somente onde existe I/O.
- Injeção de dependência explícita.
- Autenticação na fronteira da API **e** autorização também no domínio.
- Erros expõem `error.code` estável e `trace_id`.
- Nunca stack trace nem secret em resposta.
- Valor monetário em string decimal; timestamp em ISO 8601; IDs opacos.
- O webhook de pagamento entra direto no `PaymentService`, nunca no LLM.

## Agent não é domínio

Fonte: ADR-002, ADR-003, ADR-005.

- Existe **um** Sales Agent conversacional em runtime. Domínios são serviços
  determinísticos, não agentes adicionais.
- LangGraph orquestra; não implementa regra de negócio.
- O estado do grafo não é source of truth de saldo, tarifa, Order ou Payment.
- Nodes podem ser retomados ou reexecutados: todo side effect é idempotente.
- O agente nunca executa SQL direto.
- Nenhuma regra de negócio determinística vai para prompt.

## Mudança arquitetural

Exige ADR **antes** da implementação: nova infraestrutura, novo provider,
dependência estrutural, mudança de state machine ou mudança de fronteira de
domínio. Não introduza decisão arquitetural silenciosamente.
