# `urbanopay-frontend` — interface conversacional

Next.js (App Router) + TypeScript, decidido em
[ADR-011](../../docs/adr/ADR-011-web-frontend-stack.md).

```bash
npm ci
npm run dev        # http://localhost:3000
```

Requer a API no ar. Por padrão ela é procurada em `http://localhost:8000`; no
Compose, `URBANOPAY_API_URL` aponta para `http://api:8000`.

## Como o dado chega aqui

```text
Browser → Next (route handler = proxy) → UrbanoPay API → Domain → PostgreSQL
```

O servidor Next **renderiza e transporta**. Ele não calcula, não decide e não
reinterpreta estado de negócio — `lib/proxy.ts` nem lê o corpo da resposta:
repassa status e bytes como vieram.

## Invariantes

Valem qualquer que seja a tela, e estão em ADR-011 e em
`.claude/rules/frontend/web.md`:

- **nenhuma regra de negócio aqui.** Tarifa, desconto, total, elegibilidade e
  status vêm da API. A interface exibe; não recalcula;
- **nenhuma aritmética monetária.** Valor é `string` decimal (ADR-006). Somar,
  arredondar ou comparar dinheiro em JavaScript é defeito, mesmo quando o
  resultado coincide;
- **nenhum segredo.** Nada com prefixo `NEXT_PUBLIC_` carrega credencial —
  tudo com esse prefixo vai para o bundle. `OPENAI_API_KEY` e equivalentes
  vivem só no backend Python, e a CI verifica que não vazaram;
- **nenhuma PII.** O frontend nunca recebe CPF, número completo de cartão nem
  OTP. Cartão aparece mascarado, como a API o entrega;
- **o estado financeiro é do backend.** A interface nunca afirma que um
  pagamento foi concluído por ação do usuário. O botão de simular pagamento
  pede ao backend que o provider reporte um desfecho — quem aplica é o
  `PaymentService`, sob lock e com regras monotônicas;
- **acompanhamento sem polling agressivo** (ADR-007): a consulta assíncrona só
  roda enquanto há pagamento ou entrega em curso, e para em estado terminal.

## Estrutura

```text
app/
├── page.tsx              Server Component: lê o ambiente e monta a conversa
├── layout.tsx
├── globals.css
└── api/                  route handlers — proxies burros para a API
components/
├── Chat.tsx              conversa, fases e acompanhamento
└── JourneyPanel.tsx      pedido, Pix com QR e comprovante
lib/
├── api.ts                contratos tipados da API
└── proxy.ts              o ÚNICO ponto que fala com o backend
```

## Variáveis

| Variável | Papel |
|---|---|
| `URBANOPAY_API_URL` | URL interna da API. **De servidor** — nunca vai para o bundle |
| `URBANOPAY_DEMO_TOOLS` | `false` esconde o painel de demonstração (código de verificação e simulação de pagamento) |

## O que não está aqui

**Superfície de aprovação humana** — bloqueada por **A-07**: não existe decisão
sobre quem aprova, por qual superfície e com qual autorização. A interface
exibe que o pedido aguarda aprovação e para ali.

**Streaming de tokens** — adiado com motivo em ADR-011: a resposta do agente é
structured output validado, e streamear exigiria um segundo caminho de
composição, não estruturado.
