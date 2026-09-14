import type { NextConfig } from "next";

/**
 * Configuração do Next (ADR-011, ADR-016).
 *
 * `output: "standalone"` é o que permite a imagem de runtime carregar só o
 * necessário, sem `node_modules` inteiro.
 */
const nextConfig: NextConfig = {
  output: "standalone",
  // A URL da API é variável **de servidor**: ela nunca vai para o bundle, e é
  // por isso que não tem prefixo `NEXT_PUBLIC_`. O browser fala com o Next; o
  // Next fala com a API.
  env: {},
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
