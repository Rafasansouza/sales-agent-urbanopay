import { proxy } from "@/lib/proxy";

/**
 * Canal do OTP simulado (H-12).
 *
 * Existe apenas enquanto a API estiver em `APP_ENV=local`; fora disso ela
 * responde 404, e o proxy repassa o 404 sem inventar comportamento.
 */
export async function GET(): Promise<Response> {
  return proxy("/api/v1/dev/otp");
}
