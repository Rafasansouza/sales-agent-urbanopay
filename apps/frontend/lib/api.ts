/**
 * Contrato da API da UrbanoPay, visto pelo frontend (ADR-011).
 *
 * Regras que estes tipos materializam:
 *
 * - **valor monetário é `string`**, sempre. Nunca `number`. O contrato o
 *   transporta como string decimal (ADR-006), e convertê-lo para ponto
 *   flutuante em JavaScript é defeito mesmo quando o resultado coincide;
 * - **status é `string`**, e não union de literais. Ele chega do backend e é
 *   usado para **rotular**, nunca para decidir se algo pode acontecer — quem
 *   decide é a máquina de estados, do outro lado (ADR-005);
 * - **nenhum campo de PII existe aqui**, porque nenhum existe na API: a
 *   resposta não carrega CPF, OTP nem número de cartão.
 */

/** Pedido em curso. `total` é string decimal: exibir, nunca somar. */
export interface OrderPanel {
  order_id: string;
  status: string;
  total: string;
  currency: string;
  requires_approval: boolean;
}

/** Cobrança Pix do sandbox. `qr_code` é o payload copiável. */
export interface PixPanel {
  payment_id: string;
  status: string;
  amount: string;
  currency: string;
  qr_code: string | null;
}

/** Comprovante simulado. `document_kind` é sempre explícito. */
export interface ReceiptPanel {
  receipt_id: string;
  amount: string;
  currency: string;
  masked_card: string;
  document_kind: string;
  issued_at: string;
}

export interface Panel {
  order: OrderPanel | null;
  pix: PixPanel | null;
  receipt: ReceiptPanel | null;
  fulfillment_status: string | null;
}

export interface MessageResponse {
  conversation_id: string;
  session_id: string;
  phase: string;
  message: string;
  code: string | null;
  next_action: string | null;
  panel: Panel;
}

export interface MessageRequest {
  message: string;
  conversation_id?: string | null;
  session_id?: string | null;
  request_id?: string;
}

/** Erro da API. Trate sempre pelo `code`, nunca pela mensagem (ADR-006). */
export interface ApiError {
  error: { code: string; message?: string };
}

export const PHASE_LABELS: Record<string, string> = {
  DISCOVERY: "Início",
  CALCULATION: "Cálculo de tarifa",
  RECOMMENDATION: "Recomendação",
  AUTHENTICATION: "Identificação",
  AWAITING_DOCUMENT: "Aguardando CPF",
  AWAITING_OTP: "Aguardando código",
  CARD_SELECTION: "Escolha do cartão",
  QUOTE: "Orçamento",
  ORDER_CONFIRMATION: "Confirmação",
  APPROVAL: "Aprovação humana",
  PAYMENT: "Pagamento",
  FULFILLMENT: "Entrega",
  POST_SALE: "Pós-venda",
  COMPLETED: "Concluído",
  ERROR: "Erro",
};

/**
 * Fases em que vale acompanhar o estado de forma assíncrona.
 *
 * O acompanhamento **para** fora delas, e é isso que atende ADR-007: nada de
 * polling agressivo, nada de consulta que não tenha o que descobrir.
 */
export const TRACKING_PHASES = new Set(["PAYMENT", "FULFILLMENT"]);
