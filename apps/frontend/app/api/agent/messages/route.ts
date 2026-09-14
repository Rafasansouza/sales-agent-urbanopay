import { proxy } from "@/lib/proxy";

/** Encaminha um turno de conversa. Repassa; não interpreta. */
export async function POST(request: Request): Promise<Response> {
  return proxy("/api/v1/agent/messages", { method: "POST", body: await request.text() });
}
