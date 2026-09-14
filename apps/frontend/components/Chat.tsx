"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { PHASE_LABELS, TRACKING_PHASES, type MessageResponse, type Panel } from "@/lib/api";
import { JourneyPanel } from "@/components/JourneyPanel";

/**
 * A conversa (ADR-011).
 *
 * O que este componente **não** faz, e é o mais importante sobre ele:
 *
 * - não calcula valor, não soma dinheiro e não arredonda nada. Tudo o que
 *   aparece em reais vem da API como string decimal e é exibido como veio;
 * - não decide se um pedido pode ser confirmado, pago ou entregue. Ele mostra o
 *   status que o backend reportou;
 * - não afirma que um pagamento aconteceu. O botão de liquidar pede ao backend
 *   que o provider reporte um desfecho — quem aplica é o `PaymentService`.
 */

interface Entry {
  id: string;
  kind: "me" | "bot" | "note";
  text: string;
  meta?: string;
}

const EMPTY_PANEL: Panel = {
  order: null,
  pix: null,
  receipt: null,
  fulfillment_status: null,
};

/** Intervalo do acompanhamento assíncrono. Generoso, por ADR-007. */
const TRACKING_INTERVAL_MS = 4000;

let sequence = 0;
const nextId = () => `e${(sequence += 1)}`;

export function Chat({ demoTools }: { demoTools: boolean }) {
  const [entries, setEntries] = useState<Entry[]>([
    {
      id: nextId(),
      kind: "note",
      text:
        'Experimente: "quanto custa pegar a 101 e depois o metrô?" — depois, ' +
        '"quero recarregar meu cartão".',
    },
  ]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("DISCOVERY");
  const [panel, setPanel] = useState<Panel>(EMPTY_PANEL);

  const conversationId = useRef<string | null>(null);
  const sessionId = useRef<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [entries]);

  const append = useCallback((entry: Omit<Entry, "id">) => {
    setEntries((current) => [...current, { ...entry, id: nextId() }]);
  }, []);

  const apply = useCallback((data: MessageResponse) => {
    conversationId.current = data.conversation_id;
    sessionId.current = data.session_id;
    setPhase(data.phase);
    // O painel do turno substitui o anterior apenas no que ele traz: um turno
    // que só consulta o pagamento não deve apagar o pedido da tela.
    setPanel((current) => ({
      order: data.panel.order ?? current.order,
      pix: data.panel.pix ?? current.pix,
      receipt: data.panel.receipt ?? current.receipt,
      fulfillment_status: data.panel.fulfillment_status ?? current.fulfillment_status,
    }));
  }, []);

  const send = useCallback(
    async (text: string) => {
      setBusy(true);
      try {
        const response = await fetch("/api/agent/messages", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            conversation_id: conversationId.current,
            session_id: sessionId.current,
            // Deduplica retry de rede. Não substitui idempotência de negócio:
            // Order, confirmação e cobrança têm chaves próprias no backend.
            request_id: crypto.randomUUID(),
          }),
        });
        const data = (await response.json()) as MessageResponse | { error?: { code: string } };

        if (!response.ok) {
          const code = "error" in data && data.error ? data.error.code : "DESCONHECIDO";
          append({ kind: "note", text: `Não consegui concluir (${code}).` });
          return;
        }

        const turn = data as MessageResponse;
        apply(turn);
        append({
          kind: "bot",
          text: turn.message,
          meta: turn.next_action ? `próximo passo: ${turn.next_action}` : undefined,
        });
      } catch {
        append({ kind: "note", text: "Falha de rede ao falar com a API." });
      } finally {
        setBusy(false);
      }
    },
    [append, apply],
  );

  /**
   * Acompanhamento assíncrono do pedido (ADR-007).
   *
   * Só roda enquanto há pagamento ou entrega em curso, e **para** ao sair
   * dessas fases. Um Pix pode ser pago fora desta aba, e o cliente não deveria
   * precisar perguntar para descobrir — mas isso não justifica consultar sem
   * parar.
   */
  useEffect(() => {
    if (!TRACKING_PHASES.has(phase) || !conversationId.current) return;

    let cancelled = false;
    const timer = setInterval(() => {
      if (cancelled || busy) return;
      void send("qual a situação do meu pedido?");
    }, TRACKING_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [phase, busy, send]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    append({ kind: "me", text });
    setDraft("");
    void send(text);
  };

  const reset = () => {
    conversationId.current = null;
    sessionId.current = null;
    setPhase("DISCOVERY");
    setPanel(EMPTY_PANEL);
    setEntries([{ id: nextId(), kind: "note", text: "Conversa reiniciada." }]);
  };

  return (
    <div className="layout">
      <section className="panel" aria-label="Conversa">
        <div className="log" ref={logRef} role="log" aria-live="polite">
          {entries.map((entry) => (
            <div key={entry.id} className={`bubble bubble--${entry.kind}`}>
              {entry.text}
              {entry.meta ? <div className="bubble__meta">{entry.meta}</div> : null}
            </div>
          ))}
          {busy ? <div className="bubble bubble--note">consultando…</div> : null}
        </div>

        <form className="composer" onSubmit={submit}>
          <label className="sr-only" htmlFor="draft">
            Mensagem
          </label>
          <input
            id="draft"
            type="text"
            autoComplete="off"
            placeholder="Digite sua mensagem…"
            value={draft}
            disabled={busy}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button type="submit" disabled={busy || draft.trim() === ""}>
            Enviar
          </button>
        </form>
      </section>

      <aside className="aside">
        <div className="card">
          <p className="card__title">Etapa</p>
          <span className="status">
            <span className={`dot ${phase === "COMPLETED" ? "dot--ok" : ""}`} />
            {PHASE_LABELS[phase] ?? phase}
          </span>
        </div>

        <JourneyPanel
          panel={panel}
          conversationId={conversationId.current}
          demoTools={demoTools}
          onNote={(text) => append({ kind: "note", text })}
          onRefresh={() => void send("qual a situação do meu pedido?")}
        />

        <div className="card stack stack--row">
          {demoTools ? <OtpButton onNote={(text) => append({ kind: "note", text })} /> : null}
          <button className="ghost" type="button" onClick={reset}>
            Nova conversa
          </button>
        </div>
      </aside>
    </div>
  );
}

/**
 * Canal do OTP simulado (H-12).
 *
 * O código **nunca** chega aqui por outro caminho: ele não está na resposta da
 * conversa, não está em log e não está no estado. Este botão consulta um
 * endpoint que só existe em ambiente local.
 */
function OtpButton({ onNote }: { onNote: (text: string) => void }) {
  const [busy, setBusy] = useState(false);

  const reveal = async () => {
    setBusy(true);
    try {
      const response = await fetch("/api/dev/otp");
      if (!response.ok) {
        onNote("Nenhum código foi gerado ainda. Informe seu CPF primeiro.");
        return;
      }
      const { otp } = (await response.json()) as { otp: string };
      onNote(`Código de verificação (simulado): ${otp}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <button className="ghost" type="button" onClick={() => void reveal()} disabled={busy}>
      Ver código
    </button>
  );
}
