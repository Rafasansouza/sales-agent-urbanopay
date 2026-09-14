# ADR-011 — Stack do Frontend Web

**Status:** Aceito
**Data da proposta:** 2026-08-23
**Data da aceitação:** 2026-09-13
**Resolve:** A-08

## Contexto

ADR-001 estabelece `apps/web` como parte da estrutura inicial do monorepo e o
Agent Harness prevê uma regra específica em `.claude/rules/frontend/web.md`.
Entretanto, **nenhum documento aceito definia a stack do frontend**.

O `.gitignore` do repositório já ignora `.next/` e `node_modules/`, o que
sugeria Next.js, mas indício de configuração não é decisão arquitetural.

CLAUDE.md determina que dependências majoritárias exigem ADR antes da
implementação. Por isso o bootstrap criou apenas um `README.md` em `apps/web/`,
e a demonstração do MVP foi feita por uma página dev-only servida pela própria
API — ferramenta de desenvolvimento, não produto.

## Requisitos que a escolha precisa atender

Derivados do PRD e das SPECs já aceitas:

1. Interface conversacional com streaming de respostas do agente
   (PRD §5, §18; latência conversacional P95 ≤ 3 s em PRD §16).
2. Exibição de Pix sandbox, incluindo QR code e cópia de código
   (PRD §8, passos 17–18).
3. Acompanhamento de estado assíncrono: `PAYMENT_PENDING` → `PAID` →
   `FULFILLING` → `COMPLETED`, sem polling agressivo (ADR-007).
4. Nenhum segredo no cliente. `MERCADOPAGO_ACCESS_TOKEN` é exclusivamente
   backend (ADR-007).
5. Nenhuma regra de negócio no frontend. Tarifa, desconto, total e status vêm
   sempre da API (ADR-005).
6. Masking preservado: o frontend nunca recebe CPF completo, número completo
   de cartão nem OTP (SPEC-002 §6, §12).
7. Suporte à interface administrativa de aprovação humana — cujo escopo ainda
   é pendência aberta (PRD §19; ver A-07 em `docs/OPEN-QUESTIONS.md`).

## Alternativas em avaliação

### A. Next.js (App Router) + TypeScript
Ecossistema maduro para streaming de UI, roteamento e renderização no
servidor. Consistente com o `.gitignore` existente. Custo: introduz uma
segunda camada de servidor no monorepo, o que exige disciplina para não
migrar regra de negócio para o BFF, violando ADR-005 e ADR-006.

### B. SPA com Vite + React + TypeScript
Fronteira mais limpa: o frontend é estritamente cliente da API FastAPI, o que
reduz o risco de vazamento de regra de negócio para o servidor web. Custo:
sem renderização no servidor, exige mais trabalho manual em streaming.

### C. Templates server-side no FastAPI
Menor superfície e nenhuma dependência JS relevante. Custo: experiência
conversacional pobre; conflita com a expectativa de produto de portfólio do
PRD.

## Decisão

**Alternativa A — Next.js (App Router) + TypeScript.**

O que pesou: o App Router entrega Server Components, streaming de UI e uma
fronteira servidor/cliente explícita sem trabalho manual; e o `.gitignore` já
antecipava essa direção, de modo que a escolha não contraria nenhuma
expectativa existente do repositório.

O custo é real e está nomeado na própria alternativa: **um segundo servidor no
monorepo é um lugar tentador para regra de negócio**. A decisão só é aceitável
acompanhada da disciplina abaixo, que é parte dela e não recomendação.

### O BFF é um proxy burro

O servidor Next existe para **renderizar e transportar**. Nenhuma rota dele
pode calcular, decidir ou reinterpretar estado de negócio.

```text
Browser → Next (route handler = proxy) → UrbanoPay API → Domain → PostgreSQL
```

Regras, verificáveis:

- um route handler **repassa** requisição e resposta; ele não lê, não
  transforma e não deriva campo de dinheiro, status ou elegibilidade;
- **nenhum enum de domínio é reimplementado** no frontend com semântica
  própria. `OrderStatus` e `PaymentStatus` chegam como string da API e são
  usados para **rotular**, nunca para decidir se algo pode acontecer;
- **nenhuma aritmética monetária no cliente.** Valor monetário é string
  decimal, exibido como veio. Somar, arredondar ou comparar dinheiro em
  JavaScript é defeito, mesmo quando o resultado coincide;
- o frontend **nunca afirma** que um pagamento foi concluído a partir de ação
  do usuário. Um botão "já paguei" pode, no máximo, disparar uma consulta.

### Fronteira da credencial

Nenhuma variável `NEXT_PUBLIC_*` carrega segredo — por construção, tudo com
esse prefixo vai para o bundle. `OPENAI_API_KEY`, `MERCADOPAGO_ACCESS_TOKEN` e
equivalentes permanecem exclusivamente no backend Python (ADR-007, ADR-015). O
servidor Next **não** precisa delas e **não** as recebe.

A URL interna da API (`http://api:8000`) é variável de servidor, não pública:
o browser fala com o Next, e o Next fala com a API.

## Escopo aceito, e o que fica de fora

| Requisito | Estado |
|---|---|
| 2 — Pix com QR e cópia de código | ✅ implementado |
| 3 — acompanhamento de estado sem polling agressivo | ✅ polling só enquanto há pagamento em curso; para em estado terminal |
| 4 — nenhum segredo no cliente | ✅ |
| 5 — nenhuma regra de negócio no cliente | ✅ |
| 6 — masking preservado | ✅ o frontend nunca recebe CPF, cartão completo ou OTP |
| 1 — **streaming de tokens** | ⚠️ **adiado**, com motivo |
| 7 — superfície de aprovação humana | ❌ bloqueado por **A-07** |

**Sobre o streaming (requisito 1).** Ele não é entregue agora, e o motivo é de
contrato, não de esforço: a resposta do agente é composta por
`LLMProvider.compose_reply`, que devolve **structured output** validado
(`ModelResponse`) — um contrato que existe justamente para que a resposta não
seja texto livre. Streamear tokens exigiria um segundo caminho de composição,
não estruturado, e uma decisão sobre o que fazer quando o texto parcial
contradiz o objeto final.

O que o frontend entrega no lugar, e que endereça a **latência percebida** que
o requisito persegue: estado de envio explícito por turno e acompanhamento
assíncrono do pedido. Streaming real de tokens exige decisão própria — e, se
vier, começa por um ADR sobre o contrato do provider, não pelo frontend.

**Sobre a aprovação humana (requisito 7).** A-07 segue aberta: não existe
decisão sobre quem aprova, por qual superfície e com qual autorização.
Construir uma tela de aprovação agora seria inventar política administrativa.
O frontend **exibe** que o pedido aguarda aprovação e para ali.

## Consequências

**Positivas:** existe um frontend de produto, e `apps/frontend` — renomeado de
`apps/web` na mesma mudança, ver ADR-001 — deixa de ser placeholder; A-08
fecha; o critério de aceite do PRD §18 passa a ser
demonstrável por interface, e não apenas por API; a fronteira
servidor/cliente do App Router mantém a chave fora do bundle por construção.

**Negativas:** o monorepo passa a ter duas toolchains — `uv` para Python e
`npm` para o frontend — e a CI ganha um job próprio; o servidor Next é
superfície nova de manutenção e de atualização de segurança; e a disciplina
contra regra de negócio no BFF é processo, não ferramenta, o que a torna
dependente de revisão.

**Substituída:** a página `/dev/chat` servida pela API continua existindo como
ferramenta de desenvolvimento e é útil para depurar a API sem subir o
frontend. Ela **não** é o produto, e nada novo deve ser construído nela.

## Regra para Claude Code

Nenhuma regra de negócio no frontend: tarifa, total, elegibilidade e status vêm
da API e são exibidos como vieram. Nenhum cálculo monetário em JavaScript.
Nenhum segredo em `NEXT_PUBLIC_*`. Route handler do Next é proxy: se você
estiver escrevendo `if` sobre status de pagamento dentro dele, a regra está no
lugar errado.
