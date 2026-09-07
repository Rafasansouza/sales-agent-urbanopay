# apps/api — Backend FastAPI

Backend do assistente inteligente de vendas da UrbanoPay Mobilidade.

**Documentos:** ADR-001 (monólito modular), ADR-006 (FastAPI), ADR-013 (toolchain)

## Estado atual

Esqueleto do bootstrap. **Nenhuma regra de negócio implementada.**

O que existe:

- fábrica da aplicação FastAPI;
- configuração por variáveis de ambiente;
- envelope de erro com `error.code` e `trace_id`;
- logging estruturado em JSON;
- ponto de acoplamento da telemetria, desligado;
- `GET /api/v1/health`;
- as 12 fronteiras de domínio de ADR-001, vazias e documentadas.

O que **não** existe: SPEC-001 a SPEC-005, persistência, tools do agente,
grafo LangGraph, integração de pagamento e seeds.

## Estrutura

```text
src/urbanopay/
├── main.py              fábrica da aplicação, sem regra de negócio
├── core/                configuração, erros, logging, telemetria
├── api/v1/              camada HTTP versionada, routers finos
├── db/                  persistência decidida (ADR-012); implementação futura
├── providers/           portas de LLM e de pagamento
│   ├── llm/             ADR-010
│   └── payments/        ADR-007
└── modules/             fronteiras de domínio de ADR-001
    ├── agent/           SPEC-004
    ├── catalog/         sem SPEC (ver A-05)
    ├── fare/            SPEC-001
    ├── identity/        SPEC-002
    ├── cards/           SPEC-002
    ├── orders/          SPEC-003
    ├── payments/        SPEC-003
    ├── approvals/       SPEC-003
    ├── fulfillment/     SPEC-005
    ├── tickets/         SPEC-005
    ├── postsale/        SPEC-005
    └── observability/   transversal, ADR-008
```

Cada módulo possui `README.md` com SPEC aplicável, tools permitidas, tools
proibidas e bloqueios conhecidos. **Leia-o antes de implementar.**

## Estratificação obrigatória

Quando um módulo for implementado, ele recebe:

```text
modules/<dominio>/
├── domain/          entidades, value objects, erros tipados, regras puras
├── application/     use cases e serviços
└── infrastructure/  repositórios e adaptadores
```

`domain` não importa `application` nem `infrastructure`. `api/` depende de
`application`, nunca de `infrastructure`. Ver `.claude/rules/architecture.md`.

Os subdiretórios não foram criados vazios de propósito: eles nascem junto com
a primeira implementação de cada módulo.

## Executar

A partir da **raiz do repositório**:

```powershell
.\scripts\dev.ps1 setup    # uv sync
.\scripts\dev.ps1 api      # uvicorn com reload
```

```bash
make setup
make api
```

Verificar:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Documentação interativa em `http://127.0.0.1:8000/docs`, disponível apenas
quando `APP_ENV=local`.

## Convenções de contrato

Fonte: ADR-006.

| Aspecto | Regra |
|---|---|
| Versionamento | `/api/v1` |
| Dinheiro | string decimal, nunca número de ponto flutuante |
| Timestamp | ISO 8601 |
| IDs | opacos, sem significado derivável |
| Erro | `error.code` estável + `trace_id` |
| Resposta de erro | sem stack trace, sem query, sem secret |
| `async` | apenas onde há I/O |
| Autorização | na fronteira da API **e** no domínio |
| Webhook de pagamento | entra direto no `PaymentService`, nunca no LLM |

## Dependências

Gerenciadas por `uv` a partir da raiz do workspace (ADR-013). O `uv.lock` fica
na raiz e é versionado.

Adicionar dependência:

```bash
uv add --package urbanopay <pacote>
```

Dependência estrutural exige ADR **antes** da instalação (CLAUDE.md).
