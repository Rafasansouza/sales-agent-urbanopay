# =============================================================================
# Imagem do frontend — UrbanoPay Mobilidade
# =============================================================================
# Fonte: ADR-011 (Next.js App Router), ADR-016 (empacotamento).
#
# Regras que este arquivo materializa:
#
#   - dependências instaladas a partir do `package-lock.json` com `npm ci`:
#     a mesma garantia de reprodutibilidade que o `uv.lock` dá ao backend;
#   - **nenhum secret** entra aqui. Sem `ARG` de credencial, sem `COPY .env`.
#     O frontend não precisa de credencial: quem fala com a OpenAI é a API
#     Python, e a chave nunca sai de lá (ADR-011, ADR-015);
#   - usuário não-root;
#   - `output: standalone` no `next.config.ts` é o que permite a imagem de
#     runtime carregar só o necessário, sem `node_modules` inteiro.
# =============================================================================

# --- Estágio 1: dependências -------------------------------------------------
FROM node:22-alpine AS deps

WORKDIR /app
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund


# --- Estágio 2: build --------------------------------------------------------
FROM node:22-alpine AS builder

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/frontend/ ./

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build


# --- Estágio 3: runtime ------------------------------------------------------
FROM node:22-alpine AS runtime

RUN apk add --no-cache curl \
    && addgroup --system --gid 1001 urbanopay \
    && adduser --system --uid 1001 --ingroup urbanopay urbanopay

WORKDIR /app

# `standalone` traz o servidor mínimo; `static` e `public` continuam sendo
# servidos do disco.
COPY --from=builder --chown=urbanopay:urbanopay /app/.next/standalone ./
COPY --from=builder --chown=urbanopay:urbanopay /app/.next/static ./.next/static

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

USER urbanopay

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD curl --fail --silent http://localhost:3000/ >/dev/null || exit 1

CMD ["node", "server.js"]
