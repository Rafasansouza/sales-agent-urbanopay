"""Enums do domínio de pagamentos (SPEC-003 §9, §12)."""

from __future__ import annotations

from enum import StrEnum


class PaymentStatus(StrEnum):
    """Os **sete** estados do Payment (SPEC-003 §9).

    Não existe `UNKNOWN`: o desconhecimento do estado externo é representado
    por `CREATED` somado ao erro `PAYMENT_STATUS_UNKNOWN` (§9.1). Criar um
    oitavo estado para "não sei" transformaria incerteza em fato persistido.

    - `CREATED` — existe tentativa local, mas ainda não existe confirmação
      suficiente do estado externo (inclui timeout na criação);
    - `PENDING` — o provider confirmou a cobrança e aguarda pagamento;
    - `APPROVED` — o provider confirmou o pagamento;
    - `REJECTED`, `CANCELLED`, `EXPIRED` — desfechos terminais informados
      pelo provider;
    - `FAILED` — falha determinística de criação informada pelo provider.
    """

    CREATED = "CREATED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class PaymentMethod(StrEnum):
    """Meios de pagamento. MVP: apenas Pix, em ambiente test/sandbox (§9)."""

    PIX = "PIX"


class ProviderName(StrEnum):
    """Provider que originou a cobrança (ADR-007).

    Enum de domínio, deliberadamente separado de
    `core.config.PaymentProviderName`: o domínio não importa configuração. O
    valor persistido descreve **o que aconteceu**, não o que está configurado
    agora — trocar a configuração não pode reescrever a história.
    """

    FAKE = "FAKE"
    MERCADOPAGO = "MERCADOPAGO"
