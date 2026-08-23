---
name: new-adr
description: Cria um Architecture Decision Record antes de introduzir nova infraestrutura, provider, dependência estrutural, mudança de state machine ou mudança de fronteira de domínio. Obrigatória sempre que uma decisão arquitetural for necessária.
---

# new-adr

Materializa a regra de CLAUDE.md e AGENT-HARNESS §7: decisão arquitetural
**precede** implementação e é registrada em documento.

## Quando esta skill é obrigatória

- Nova infraestrutura — banco, broker, cache, serviço externo.
- Novo provider — pagamento, LLM, e-mail, storage.
- Nova dependência estrutural, que molde como o código é escrito.
- Mudança de máquina de estados de domínio.
- Mudança de fronteira entre módulos.
- Mudança na fronteira entre IA probabilística e domínio determinístico.
- Alteração de política de segurança ou de idempotência.

Se você está em dúvida se algo exige ADR, exige.

## Quando não é necessária

Correção de bug sem mudança de decisão; implementação de SPEC já aceita dentro
das decisões vigentes; refatoração interna que preserva fronteiras e contratos;
dependência de desenvolvimento coberta por ADR-013.

## Procedimento

### 1. Verificar se a decisão já existe

Leia os ADRs vigentes antes de escrever um novo:

| ADR | Assunto | Status |
|---|---|---|
| 001 | Monólito modular em monorepo | Aceito |
| 002 | LangGraph como runtime do agente | Aceito |
| 003 | Agente único | Aceito |
| 004 | PostgreSQL autoritativo, pgvector restrito | Aceito |
| 005 | Fronteira probabilístico / determinístico | Aceito |
| 006 | FastAPI | Aceito |
| 007 | Mercado Pago sandbox, Pix, idempotência | Aceito |
| 008 | OpenTelemetry e Langfuse | Aceito |
| 009 | Redis restrito a estado efêmero | Aceito |
| 010 | Estratégia de LLM e abstração de provider | Aceito |
| 011 | Stack do frontend web | **Proposta** |
| 012 | Persistência, ORM e migrations | **Proposta** |
| 013 | Toolchain Python | Aceito |

Se a decisão contraria um ADR aceito, o novo ADR precisa **substituí-lo
explicitamente**, e o antigo passa a `Substituído por ADR-0NN`. Nunca edite um
ADR aceito para mudar a decisão que ele registra.

### 2. Numerar

Próximo número sequencial livre. Nome do arquivo:
`docs/adr/ADR-0NN-<slug-em-ingles>.md`.

### 3. Escrever

```markdown
# ADR-0NN — <Título>

**Status:** Proposta
**Data:** <AAAA-MM-DD>

## Contexto
Qual problema real força uma decisão agora. Cite PRD, SPEC e ADRs envolvidos.

## Requisitos que a escolha precisa atender
Lista derivada dos documentos aceitos, com referência a cada fonte.

## Alternativas em avaliação
Ao menos duas, cada uma com custo explícito. Uma alternativa sem custo
declarado é sinal de análise incompleta.

## Decisão
A escolha, em uma afirmação. Enquanto pendente, escreva "Pendente".

## Regras
Consequências operacionais concretas — o que passa a ser obrigatório e o que
passa a ser proibido.

## Alternativas rejeitadas
Com o motivo da rejeição.

## Consequências
Positivas e negativas. Negativas honestas.

## Regra para Claude Code
O que o agente deve e não deve fazer sob esta decisão.
```

### 4. Status

- `Proposta` — escrito, **não** aceito. Nenhuma implementação pode se apoiar
  nele. Nenhuma dependência pode ser instalada por causa dele.
- `Aceito` — decisão vigente. Somente o humano responsável promove um ADR de
  `Proposta` para `Aceito`.
- `Substituído por ADR-0NN` — histórico preservado.

**Nunca crie um ADR já com status `Aceito` por conta própria.** Aceitação é
decisão humana.

### 5. Registrar pendências

Se o ADR ficar como `Proposta`, adicione ou atualize a entrada correspondente
em `docs/OPEN-QUESTIONS.md`, indicando o que ele bloqueia.

## Ao terminar

Apresente o ADR e aguarde a decisão humana. Não implemente nada apoiado em um
ADR não aceito.
