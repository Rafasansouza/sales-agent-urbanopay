# infra — Infraestrutura local de desenvolvimento

**Documentos:** ADR-004 (PostgreSQL + pgvector), ADR-009 (Redis), ADR-008 (OTel)

## Serviços

| Serviço | Imagem | Porta | Papel |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg17` | 5432 | Source of truth transacional |
| `redis` | `redis:7-alpine` | 6379 | Estado efêmero apenas |
| `otel-collector` | `otel/opentelemetry-collector-contrib` | 4317, 4318 | Telemetria transversal |

## Usar

A partir da raiz do repositório:

```powershell
.\scripts\dev.ps1 up      # sobe os três serviços
.\scripts\dev.ps1 ps      # estado
.\scripts\dev.ps1 logs    # logs
.\scripts\dev.ps1 down    # derruba preservando os dados
```

```bash
make up
make down
```

Pré-requisito: um `.env` na raiz, criado a partir de `.env.example`. O
`POSTGRES_PASSWORD` é obrigatório — o compose falha explicitamente se ele não
estiver definido.

## Dados

O PostgreSQL usa o volume nomeado `urbanopay_postgres_data`.

- `docker compose down` **preserva** os dados.
- `docker compose down -v` os **apaga** e está bloqueado pelo harness
  (AGENT-HARNESS §9). Se você realmente precisa recriar o banco do zero, faça
  isso manualmente e de forma consciente.

## Inicialização do PostgreSQL

`postgres/init/01-extensions.sql` roda **apenas na primeira criação do volume**
e cria somente extensões:

- `vector` — pgvector, restrito a recuperação semântica;
- `pgcrypto` — geração de UUID para IDs opacos;
- `btree_gist` — necessário para constraints de exclusão que garantam
  invariantes financeiras.

Nenhuma tabela e nenhum seed. O esquema pertence a migrations versionadas, e a
ferramenta de migrations aguarda a aceitação do ADR-012.

## Papel de cada serviço

### PostgreSQL — autoritativo

Fonte da verdade para `Customer`, `Card`, saldo, `Fare`, `FareRule`, `Product`,
`Quote`, `Order`, `Approval`, `Payment`, `Fulfillment`, ledger, `Ticket` e
auditoria.

pgvector encontra o que **parece** relevante. O banco relacional determina os
**fatos**. Busca vetorial nunca é autoritativa para preço, saldo ou status de
pagamento.

### Redis — efêmero

Permitido: rate limiting, cache reconstruível, contadores com TTL, locks
temporários.

**Proibido como autoridade:** saldo, Order, Payment status, Fulfillment status,
ledger, idempotência financeira.

Perder este container pode custar velocidade. Não pode custar a verdade da
operação.

### OTel Collector

Recebe OTLP da API e imprime no log do container. Nenhum destino remoto: a
telemetria não sai da máquina local.

Para ativar o envio pela API, defina no `.env`:

```dotenv
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

A instrumentação da aplicação ainda não foi implementada nesta fase — a
configuração acima apenas registra a intenção em log.

## Langfuse

Não possui container aqui. O modo de implantação (self-hosted x cloud) segue em
aberto — ver H-04 em `docs/OPEN-QUESTIONS.md`. Self-host acrescentaria
ClickHouse, MinIO, um Redis adicional e a aplicação web.

A integração é configurada por `LANGFUSE_*` no `.env` e está desligada por
padrão.

## Ambientes reais

Este diretório cobre **apenas desenvolvimento local**. Produção está fora do
escopo do MVP (PRD §17: sem Kubernetes, sem microservices distribuídos), e
qualquer ação em produção não é delegada ao agente (AGENT-HARNESS §12).
