import { proxy } from "@/lib/proxy";

/** Dataset fictício de demonstração (A-12). Idempotente, e local-only. */
export async function POST(): Promise<Response> {
  return proxy("/api/v1/dev/seed", { method: "POST", body: "{}" });
}
