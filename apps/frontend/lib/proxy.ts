/**
 * Proxy para a API da UrbanoPay (ADR-011, "o BFF é um proxy burro").
 *
 * Esta é a **única** função do servidor Next que fala com o backend, e ela não
 * lê o corpo da resposta: repassa status e bytes como vieram.
 *
 * Isso é regra, não estilo. Um BFF que interpreta a resposta é um BFF que
 * começa a decidir, e a decisão migraria para o lugar errado — violando
 * ADR-005. Se você sentir vontade de escrever um `if` sobre status de pagamento
 * aqui, a regra está no lugar errado.
 *
 * A URL da API é variável **de servidor**: sem prefixo `NEXT_PUBLIC_`, ela
 * nunca entra no bundle. O browser fala com o Next; o Next fala com a API.
 */
const API_URL = process.env.URBANOPAY_API_URL ?? "http://localhost:8000";

export async function proxy(path: string, init?: RequestInit): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    // A mensagem original nunca é ecoada: ela poderia conter a URL interna da
    // API, que não é assunto do browser.
    return Response.json(
      { error: { code: "UPSTREAM_UNAVAILABLE", message: "A API nao respondeu." } },
      { status: 502 },
    );
  }

  const body = await upstream.text();
  return new Response(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
