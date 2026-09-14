"""Superfície de desenvolvimento e demonstração — **somente `APP_ENV=local`**.

Nada aqui é registrado fora de `local`: o `create_app` só inclui este router
quando `settings.is_local`. Em qualquer outro ambiente as rotas simplesmente
não existem — não é uma checagem em tempo de request que alguém possa
contornar por configuração.

Três recursos, e cada um tem um motivo nomeado:

- **OTP sink** (H-12) — o OTP simulado é criptograficamente aleatório e nunca
  aparece em log, trace ou resultado de serviço, o que deixava a demonstração
  humana sem canal para conhecê-lo. Este endpoint é esse canal, e **não é tool
  do LLM** sob nome algum (`get_otp` é proibida, SPEC-004 §7.4);
- **liquidação do sandbox** — o `FakePaymentProvider` é o sandbox do MVP
  (ADR-007). Liquidar reusa o caminho de **reconciliação** do
  `PaymentService`: o estado oficial continua vindo do provider, e o LLM não
  controla o resultado;
- **página de chat** — a superfície humana da demo. Ela chama exclusivamente
  esta API e **não possui campo de API key**: a credencial vive só no backend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from urbanopay.api.container import AppContainer
from urbanopay.api.dev.seed import DEMO_DATASET, seed_demo_dataset
from urbanopay.api.v1.agent import get_container
from urbanopay.modules.payments.domain.enums import PaymentStatus

router = APIRouter(tags=["dev"])

_CHAT_PAGE = Path(__file__).parent / "chat.html"


class OtpResponse(BaseModel):
    """Último OTP gerado nesta instância."""

    model_config = ConfigDict(extra="forbid")

    otp: str


class SettleRequest(BaseModel):
    """Desfecho que o sandbox passará a reportar."""

    model_config = ConfigDict(extra="forbid")

    status: PaymentStatus = PaymentStatus.APPROVED


class SettleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_status: str
    fulfillment_status: str | None = None


@router.get("/api/v1/dev/otp", response_model=OtpResponse, summary="OTP simulado (local)")
async def latest_otp(container: Annotated[AppContainer, Depends(get_container)]) -> OtpResponse:
    """Devolve o último OTP gerado.

    Em memória e sem persistência: reiniciar o processo apaga o valor. O código
    continua aleatório — não existe OTP fixo por configuração, o que criaria um
    caminho permanente de autenticação conhecido.
    """
    sink = container.otp_sink
    otp = sink.latest() if sink is not None else None
    if otp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum OTP foi gerado ainda nesta instancia.",
        )
    return OtpResponse(otp=otp)


@router.post(
    "/api/v1/dev/conversations/{conversation_id}/settle",
    response_model=SettleResponse,
    summary="Liquida a cobranca em curso no sandbox (local)",
)
async def settle_payment(
    conversation_id: UUID,
    payload: SettleRequest,
    container: Annotated[AppContainer, Depends(get_container)],
) -> SettleResponse:
    """Faz o sandbox reportar um desfecho para a cobrança da conversa.

    O identificador entra como `conversation_id`, e não como `payment_id`, por
    uma razão de demonstração: quem opera a demo tem a conversa à mão, não o
    identificador interno do Payment — que, aliás, a API de conversa não expõe.
    O `payment_id` é lido do estado conversacional, que é **referência**, e
    revalidado contra o backend na linha seguinte.

    O caminho é o mesmo de produção: o provider passa a reportar o estado, e o
    `PaymentService.reconcile_payment` o aplica sob lock, com regras
    monotônicas. **Nenhum status é escrito diretamente** — nem por este
    endpoint, nem por ninguém. Terminal não regride, e o LLM não participa.

    Depois do commit, o coordenador pós-pagamento dispara a entrega (A-19).
    """
    stored = await container.conversation_repository.get(conversation_id)
    payment_id = stored.state.current_payment_id if stored is not None else None
    if payment_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma cobranca em curso nesta conversa.",
        )

    payment = await container.payments.get_payment(payment_id=payment_id)
    provider = container.payment_provider
    settle = getattr(provider, "settle", None)
    if settle is None or payment.provider_payment_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider ativo nao suporta liquidacao simulada.",
        )
    settle(payment.provider_payment_id, payload.status)

    reconciled = await container.payments.reconcile_payment(payment_id=payment_id)
    delivered = await container.coordinator.on_payment_settled(
        order_id=reconciled.order_id, payment_status=reconciled.status
    )
    return SettleResponse(
        payment_status=reconciled.status.value,
        fulfillment_status=delivered.fulfillment.status.value if delivered else None,
    )


class SeedResponse(BaseModel):
    """Quantos clientes fictícios nasceram nesta execução."""

    model_config = ConfigDict(extra="forbid")

    created: int
    documents: list[str]


@router.post(
    "/api/v1/dev/seed", response_model=SeedResponse, summary="Semeia dados ficticios (local)"
)
async def seed(container: Annotated[AppContainer, Depends(get_container)]) -> SeedResponse:
    """Cria o dataset de demonstração de SPEC-002 §13 (A-12).

    Idempotente: a unicidade do CPF normalizado é constraint de banco, e rodar
    de novo não duplica nada. Somente dados fictícios, em nenhum ambiente que
    não seja `local`.

    Os CPFs são devolvidos porque são **fictícios e públicos por desenho** —
    é como a pessoa que demonstra sabe com qual conta entrar. Nenhum dado real
    passa por aqui.
    """
    created = await seed_demo_dataset(container.session_factory, hasher=container.hasher)
    return SeedResponse(created=created, documents=[c.cpf for c in DEMO_DATASET])


@router.get("/dev/chat", response_class=HTMLResponse, summary="Chat de demonstracao (local)")
async def chat_page() -> HTMLResponse:
    """Página de demonstração.

    Estática e sem build. Ela conversa **apenas** com esta API — nunca com o
    provider de LLM diretamente —, e por isso a credencial jamais chega ao
    browser:

    ```text
    Browser → UrbanoPay API → OpenAILLMProvider → OpenAI
    ```
    """
    return HTMLResponse(_CHAT_PAGE.read_text(encoding="utf-8"))
