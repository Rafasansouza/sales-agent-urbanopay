import { proxy } from "@/lib/proxy";

/**
 * Liquidação da cobrança no sandbox.
 *
 * O frontend **não** estabelece status: ele pede ao backend que o provider
 * reporte um desfecho, e quem aplica é o `PaymentService`, sob lock e com
 * regras monotônicas (SPEC-003 §12).
 */
export async function POST(request: Request): Promise<Response> {
  const { conversation_id: conversationId, status } = (await request.json()) as {
    conversation_id?: string;
    status?: string;
  };
  if (!conversationId) {
    return Response.json(
      { error: { code: "MISSING_CONVERSATION", message: "conversation_id e obrigatorio." } },
      { status: 400 },
    );
  }
  return proxy(`/api/v1/dev/conversations/${encodeURIComponent(conversationId)}/settle`, {
    method: "POST",
    body: JSON.stringify({ status: status ?? "APPROVED" }),
  });
}
