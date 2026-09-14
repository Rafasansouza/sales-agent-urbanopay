import { Chat } from "@/components/Chat";

/**
 * Página da conversa (ADR-011).
 *
 * Server Component: ela lê do ambiente **do servidor** se a superfície de
 * demonstração está habilitada e passa o resultado como prop. A variável não
 * tem prefixo `NEXT_PUBLIC_`, então nunca entra no bundle — o cliente recebe um
 * booleano, não a configuração.
 */
export default function Page() {
  const demoTools = process.env.URBANOPAY_DEMO_TOOLS !== "false";

  return (
    <main className="shell">
      <header className="topbar">
        <h1 className="brand">UrbanoPay Mobilidade</h1>
        <span className="badge">ambiente de teste</span>
        <p className="tagline">
          Descreva seu trajeto ou peça uma recarga. O valor, o saldo e o
          pagamento vêm sempre do backend.
        </p>
      </header>

      <Chat demoTools={demoTools} />

      <footer>
        Pagamento em sandbox: nenhum dinheiro real é movimentado, e o
        comprovante é explicitamente não fiscal.
      </footer>
    </main>
  );
}
