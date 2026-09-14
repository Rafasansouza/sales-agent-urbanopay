"use client";

import { useEffect, useState } from "react";

import type { Panel } from "@/lib/api";

/**
 * Painel da jornada: pedido, Pix e comprovante (ADR-011, requisito 2).
 *
 * Tudo o que aparece aqui veio da API. O componente **não** calcula, não
 * converte moeda e não deriva status — ele rotula. `total` e `amount` são
 * strings decimais e são exibidas como tal: transformá-las em `number` seria
 * defeito mesmo que o resultado coincidisse (ADR-006).
 */
export function JourneyPanel({
  panel,
  conversationId,
  demoTools,
  onNote,
  onRefresh,
}: {
  panel: Panel;
  conversationId: string | null;
  demoTools: boolean;
  onNote: (text: string) => void;
  onRefresh: () => void;
}) {
  const { order, pix, receipt, fulfillment_status: fulfillment } = panel;

  if (!order && !pix && !receipt) {
    return (
      <div className="card">
        <p className="card__title">Pedido</p>
        <p className="tagline">Nenhum pedido em curso.</p>
      </div>
    );
  }

  return (
    <>
      {order ? (
        <div className="card">
          <p className="card__title">Pedido</p>
          <p className="amount">
            {order.currency} {order.total}
          </p>
          <div className="row">
            <span className="row__label">Situação</span>
            <span className="row__value">{order.status}</span>
          </div>
          {order.requires_approval ? (
            <p className="disclaimer">
              Acima de R$ 200,00 este pedido depende de aprovação humana. A
              jornada para aqui até que alguém decida.
            </p>
          ) : null}
        </div>
      ) : null}

      {pix ? (
        <PixCard
          pix={pix}
          conversationId={conversationId}
          demoTools={demoTools}
          onNote={onNote}
          onRefresh={onRefresh}
        />
      ) : null}

      {fulfillment && !receipt ? (
        <div className="card">
          <p className="card__title">Entrega</p>
          <span className="status">
            <span className={`dot ${fulfillment === "COMPLETED" ? "dot--ok" : "dot--warn"}`} />
            {fulfillment}
          </span>
        </div>
      ) : null}

      {receipt ? (
        <div className="card">
          <p className="card__title">Comprovante</p>
          <p className="amount">
            {receipt.currency} {receipt.amount}
          </p>
          <div className="row">
            <span className="row__label">Cartão</span>
            <span className="row__value">{receipt.masked_card}</span>
          </div>
          <div className="row">
            <span className="row__label">Emitido em</span>
            <span className="row__value">{formatInstant(receipt.issued_at)}</span>
          </div>
          <p className="disclaimer">
            Documento <strong>{receipt.document_kind}</strong> — simulado e sem
            valor fiscal.
          </p>
        </div>
      ) : null}
    </>
  );
}

function PixCard({
  pix,
  conversationId,
  demoTools,
  onNote,
  onRefresh,
}: {
  pix: NonNullable<Panel["pix"]>;
  conversationId: string | null;
  demoTools: boolean;
  onNote: (text: string) => void;
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const settle = async () => {
    if (!conversationId) return;
    setBusy(true);
    try {
      const response = await fetch("/api/dev/settle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, status: "APPROVED" }),
      });
      const data = (await response.json()) as {
        payment_status?: string;
        fulfillment_status?: string | null;
        detail?: string;
      };
      onNote(
        response.ok
          ? `Pagamento ${data.payment_status} · entrega ${data.fulfillment_status ?? "—"}.`
          : `Não foi possível liquidar: ${data.detail ?? response.status}.`,
      );
      // O frontend não afirma que foi pago: ele pede ao backend o estado atual.
      onRefresh();
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!pix.qr_code) return;
    await navigator.clipboard.writeText(pix.qr_code);
    onNote("Código Pix copiado.");
  };

  return (
    <div className="card">
      <p className="card__title">Pix</p>
      <p className="amount">
        {pix.currency} {pix.amount}
      </p>
      <div className="row">
        <span className="row__label">Situação</span>
        <span className="row__value">
          <span className="status">
            <span className={`dot ${pix.status === "APPROVED" ? "dot--ok" : "dot--warn"}`} />
            {pix.status}
          </span>
        </span>
      </div>

      {pix.qr_code ? (
        <>
          <QrCode payload={pix.qr_code} />
          <p className="code">{pix.qr_code}</p>
          <div className="stack stack--row">
            <button className="ghost" type="button" onClick={() => void copy()}>
              Copiar código
            </button>
            {demoTools ? (
              <button type="button" onClick={() => void settle()} disabled={busy || !conversationId}>
                Simular pagamento
              </button>
            ) : null}
          </div>
          <p className="disclaimer">
            Cobrança em sandbox. O QR é um código simulado e não move dinheiro
            real.
          </p>
        </>
      ) : null}
    </div>
  );
}

/**
 * QR do payload Pix.
 *
 * Gerado no cliente por biblioteca comprovada, em vez de implementação própria:
 * um QR que renderiza mas não escaneia é um defeito silencioso, e correção
 * aqui vale mais que uma dependência a menos.
 */
function QrCode({ payload }: { payload: string }) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void import("qrcode").then(async (qrcode) => {
      const url = await qrcode.toDataURL(payload, { margin: 1, width: 440 });
      if (!cancelled) setSrc(url);
    });
    return () => {
      cancelled = true;
    };
  }, [payload]);

  if (!src) return <div className="qr">gerando…</div>;
  return (
    <div className="qr">
      {/* eslint-disable-next-line @next/next/no-img-element -- data URI local, sem otimização a fazer */}
      <img src={src} alt="QR Code do pagamento Pix simulado" />
    </div>
  );
}

/** Formata um instante ISO 8601 para exibição. Não interpreta, só apresenta. */
function formatInstant(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}
