import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "UrbanoPay Mobilidade",
  description:
    "Assistente de vendas da UrbanoPay: tarifas, recarga de cartão e pagamento Pix em ambiente de teste.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
