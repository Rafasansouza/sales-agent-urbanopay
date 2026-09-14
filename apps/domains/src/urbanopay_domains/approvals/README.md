# Approvals — aprovação humana

**Fronteira de domínio:** ADR-001
**Documentos obrigatórios:** SPEC-003 §7
**ADRs aplicáveis:** ADR-005, ADR-012
**Estado:** implementado (agregado e persistência)

## Responsabilidade

Representa a decisão humana sobre um Order. Guarda o agregado `Approval`, suas
transições e a trilha de auditoria — **ator e instante** em toda decisão.

A política do limiar (`order.total > R$ 200,00`, estritamente maior) vive em
`ApprovalPolicy`, no módulo `orders`, porque é lá que ela é aplicada e
congelada na criação do Order.

Os **comandos** `approve_order` e `reject_order` também vivem em `orders`: o
efeito primário deles é uma transição do Order, e manter a orquestração lá
evita dependência circular entre os módulos. Este módulo é deliberadamente
passivo — ele **nunca importa `orders`**.

## Entidades

- `Approval` — `PENDING → APPROVED | REJECTED`

## Tools permitidas ao Sales Agent

- `get_approval_status` (somente leitura)

## Tools proibidas

- `approve_order` pelo agente
- qualquer tool que aprove ou rejeite

Nenhuma delas pode ser criada sob nome equivalente ou disfarçada como tool
genérica.

## Invariantes

- A política fica encapsulada em `ApprovalPolicy`, nunca espalhada em `if`, e o
  valor do limiar não aparece fora dela — nem como `CHECK` de banco, para não
  criar uma segunda fonte da mesma regra.
- Estados terminais **não** retornam a `PENDING` e não são redecididos.
- Sem TTL e sem estado `CANCELLED` no MVP: a SPEC não define nenhum dos dois.
- Uma aprovação por Order (`uq_approvals_order_id`).
- `PENDING` não tem decisão registrada; todo terminal tem ator **e** instante
  (`ck_approvals_decision_audit_complete`).
- `decided_by` é identificador **opaco** de operador — nunca nome, e-mail ou
  CPF.

## Pendências que ainda afetam o módulo

⚠️ **A-07** — a interface administrativa pela qual um humano decide não está
especificada. O domínio, a persistência e os comandos existem e são testados;
sem essa superfície, um Order em `REQUIRES_APPROVAL` depende de acionamento
programático para seguir adiante.

## Estrutura

```text
approvals/
├── domain/          Approval, ApprovalStatus, erros, port do repository
└── infrastructure/  model ORM e repository
```

Não existe `application/`: este módulo não tem caso de uso próprio — quem
detém a transação é `orders`. Criar um serviço aqui só para delegar
adicionaria camada sem responsabilidade.

Direção de dependência: `domain` não importa `application` nem
`infrastructure`. Ver `.claude/rules/architecture.md`.
