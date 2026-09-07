"""Serviço de aplicação de pagamentos (SPEC-003 §9, §11, §12, §13).

É a superfície mais próxima do dinheiro, e por isso a de menor autonomia
automática. Três contratos governam tudo aqui:

1. **Somente o provider ou o backend estabelece `APPROVED`.** Nenhum caminho
   deste módulo aceita status vindo de texto de usuário. "eu paguei" não é
   evento de domínio e não chega a nenhuma função daqui.
2. **Nenhuma transação de banco permanece aberta durante a chamada ao
   provider** (§11.2). A criação usa duas fases explícitas.
3. **Ordem de lock `Order` → `Payment`**, subconjunto da ordem global
   `Order → Approval → Payment → Card → Fulfillment`. Toda escrita que toque os
   dois agregados adquire os locks nessa ordem, sem exceção — inclusive no
   caminho do webhook, onde é tentador travar primeiro o Payment que o evento
   identificou.

Estado externo desconhecido nunca é convertido em falha: timeout e resposta
inconclusiva mantêm `Payment CREATED`, `Order PAYMENT_PENDING` e
`Idempotency IN_PROGRESS`, e resultam em `PAYMENT_STATUS_UNKNOWN` (§9.1). A
resolução é consulta ao provider com a mesma key — nunca um novo POST.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from urbanopay.core.idempotency import (
    IdempotencyStatus,
    ensure_same_request,
    request_fingerprint,
)
from urbanopay.modules.orders.domain.errors import (
    OrderNotAccessibleError,
    OrderNotFoundError,
)
from urbanopay.modules.orders.domain.state_machine import (
    mark_paid,
    release_for_new_attempt,
    start_payment,
)
from urbanopay.modules.payments.domain.entities import (
    TERMINAL_PAYMENT_STATUSES,
    Payment,
    PaymentEvent,
    redact_event_payload,
)
from urbanopay.modules.payments.domain.enums import PaymentMethod, PaymentStatus
from urbanopay.modules.payments.domain.errors import (
    PaymentAlreadyApprovedError,
    PaymentCreationFailedError,
    PaymentNotFoundError,
    PaymentProviderError,
    PaymentProviderTimeoutError,
    PaymentStatusUnknownError,
)
from urbanopay.modules.payments.domain.results import (
    PaymentCreationResult,
    WebhookProcessingResult,
)
from urbanopay.modules.payments.domain.state_machine import apply_provider_status

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from urbanopay.modules.payments.domain.enums import ProviderName
    from urbanopay.modules.payments.domain.ports import PaymentProvider, PaymentsUnitOfWork
    from urbanopay.modules.payments.domain.state_machine import StatusApplication

# Nome de operação do escopo de idempotência `(operation, key)` (§11).
OPERATION_CREATE_PAYMENT = "create_payment"


def _now(at: datetime | None) -> datetime:
    reference = at if at is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        raise ValueError("O instante de referência deve ser timezone-aware.")
    return reference


def _lookup_event_id(payment_id: uuid.UUID, status: PaymentStatus) -> str:
    """Identificador determinístico de um evento obtido por consulta ativa.

    Consulta não traz `provider_event_id`. Derivar o identificador do par
    (payment, status lido) faz com que reconciliações repetidas que leiam o
    mesmo estado não sejam contadas como eventos distintos.
    """
    return f"lookup:{payment_id}:{status.value}"


@dataclass(frozen=True, slots=True)
class _PhaseOne:
    """Resultado interno da fase 1 da criação de pagamento.

    `short_circuit` preenchido significa que não há chamada ao provider a
    fazer: replay de key concluída, ou tentativa ativa já existente.
    """

    payment: Payment | None
    short_circuit: PaymentCreationResult | None


class PaymentService:
    """Criação, webhook e reconciliação de pagamentos."""

    def __init__(self, uow: PaymentsUnitOfWork, provider: PaymentProvider) -> None:
        self._uow = uow
        self._provider = provider

    # --- criação: duas fases (§11.2) --------------------------------------

    async def create_payment(
        self,
        *,
        customer_id: uuid.UUID,
        order_id: uuid.UUID,
        idempotency_key: str,
        at: datetime | None = None,
    ) -> PaymentCreationResult:
        """Cria a cobrança Pix de um Order `CONFIRMED` (§9, §10, §11.2).

        O valor é **derivado do Order** (`payment.amount == order.total`) e
        jamais recebido como parâmetro: é o que impede que a superfície de
        chamada — inclusive uma tool do agente — influencie quanto se cobra.
        """
        now = _now(at)
        payload = {"customer_id": str(customer_id), "order_id": str(order_id)}

        phase_one = await self._create_local_attempt(
            customer_id=customer_id,
            order_id=order_id,
            idempotency_key=idempotency_key,
            payload=payload,
            now=now,
        )
        if phase_one.short_circuit is not None:
            return phase_one.short_circuit

        payment = phase_one.payment
        if payment is None:  # pragma: no cover - garantido pelo fluxo acima
            raise PaymentStatusUnknownError

        # --- fora de transação: chamada ao provider ---
        try:
            charge = await self._provider.create_pix_charge(
                idempotency_key=idempotency_key,
                amount=payment.amount,
                currency=payment.currency,
                external_reference=str(order_id),
            )
        except PaymentCreationFailedError:
            # Recusa determinística: é o único caso em que a operação vira
            # `FAILED`. Repetir a mesma requisição produziria o mesmo
            # resultado, então o replay deve reproduzi-lo.
            await self._record_deterministic_failure(
                payment_id=payment.id, idempotency_key=idempotency_key, at=now
            )
            raise
        except (PaymentProviderTimeoutError, PaymentProviderError) as exc:
            # Estado desconhecido, nunca falha definitiva. Nada é escrito: o
            # Payment segue `CREATED`, o Order segue `PAYMENT_PENDING` e a key
            # segue `IN_PROGRESS`, exatamente como a §9.1 determina.
            raise PaymentStatusUnknownError from exc

        # --- TX2: aplica a resposta externa ---
        async with self._uow:
            application = await self._apply_reported_status(
                payment_id=payment.id,
                reported_status=charge.status,
                provider_payment_id=charge.provider_payment_id,
                now=now,
            )
            await self._uow.idempotency.complete(
                operation=OPERATION_CREATE_PAYMENT,
                key=idempotency_key,
                resource_id=payment.id,
                response_reference=charge.provider_payment_id,
                at=now,
            )
            await self._uow.commit()

        return PaymentCreationResult(payment=application.payment, qr_code=charge.qr_code)

    async def _create_local_attempt(
        self,
        *,
        customer_id: uuid.UUID,
        order_id: uuid.UUID,
        idempotency_key: str,
        payload: dict[str, str],
        now: datetime,
    ) -> _PhaseOne:
        """TX1: reivindica a key, cria o Payment local e move o Order.

        Comita antes de qualquer I/O externo.
        """
        fingerprint = request_fingerprint(payload)
        async with self._uow:
            claim = await self._uow.idempotency.claim(
                operation=OPERATION_CREATE_PAYMENT,
                key=idempotency_key,
                fingerprint=fingerprint,
                at=now,
            )
            if not claim.acquired:
                existing = claim.existing
                if existing is None:  # pragma: no cover - garantido pelo port
                    raise PaymentStatusUnknownError
                ensure_same_request(existing, fingerprint)

                if existing.status is IdempotencyStatus.IN_PROGRESS:
                    # §11.3: nenhum novo POST, nenhuma apropriação por tempo.
                    raise PaymentStatusUnknownError
                if existing.status is IdempotencyStatus.FAILED:
                    raise PaymentCreationFailedError
                if existing.resource_id is None:  # pragma: no cover - defensivo
                    raise PaymentStatusUnknownError
                replayed = await self._uow.payments.get(existing.resource_id)
                if replayed is None:  # pragma: no cover - defensivo
                    raise PaymentNotFoundError
                return _PhaseOne(
                    payment=None,
                    short_circuit=PaymentCreationResult(
                        payment=replayed, qr_code=None, already_existed=True
                    ),
                )

            # Ordem global de lock: Order é o primeiro elo. É este lock que
            # serializa dois `create_payment` concorrentes sobre o mesmo Order.
            order = await self._uow.orders.get_owned_for_update(
                customer_id=customer_id, order_id=order_id
            )
            if order is None:
                raise OrderNotAccessibleError

            if await self._uow.payments.get_approved_for_order(order.id) is not None:
                raise PaymentAlreadyApprovedError

            active = await self._uow.payments.get_active_for_order(order.id)
            if active is not None:
                if active.status is PaymentStatus.CREATED:
                    # Tentativa cujo estado externo é desconhecido: reconciliar
                    # antes de qualquer nova cobrança (§9.1).
                    raise PaymentStatusUnknownError
                # Já existe cobrança confirmada pelo provider: devolve-se a
                # existente. Criar outra seria segunda cobrança do mesmo Order.
                await self._uow.idempotency.complete(
                    operation=OPERATION_CREATE_PAYMENT,
                    key=idempotency_key,
                    resource_id=active.id,
                    response_reference=active.provider_payment_id,
                    at=now,
                )
                await self._uow.commit()
                return _PhaseOne(
                    payment=None,
                    short_circuit=PaymentCreationResult(
                        payment=active, qr_code=None, already_existed=True
                    ),
                )

            # `start_payment` recusa qualquer estado que não seja CONFIRMED.
            await self._uow.orders.update(start_payment(order, now))

            payment = Payment(
                id=uuid.uuid4(),
                order_id=order.id,
                provider=self._provider.name,
                provider_payment_id=None,
                method=PaymentMethod.PIX,
                amount=order.total,
                currency=order.currency,
                status=PaymentStatus.CREATED,
                idempotency_key=idempotency_key,
                created_at=now,
                updated_at=now,
            )
            await self._uow.payments.add(payment)
            await self._uow.commit()

        return _PhaseOne(payment=payment, short_circuit=None)

    async def _record_deterministic_failure(
        self, *, payment_id: uuid.UUID, idempotency_key: str, at: datetime
    ) -> None:
        """Marca `Payment FAILED`, devolve o Order a `CONFIRMED` e falha a key."""
        async with self._uow:
            await self._apply_reported_status(
                payment_id=payment_id,
                reported_status=PaymentStatus.FAILED,
                provider_payment_id=None,
                now=at,
            )
            await self._uow.idempotency.fail(
                operation=OPERATION_CREATE_PAYMENT,
                key=idempotency_key,
                response_reference=PaymentCreationFailedError.code,
                at=at,
            )
            await self._uow.commit()

    # --- ponto único de convergência (§12) --------------------------------

    async def _apply_reported_status(
        self,
        *,
        payment_id: uuid.UUID,
        reported_status: PaymentStatus,
        provider_payment_id: str | None,
        now: datetime,
    ) -> StatusApplication:
        """Aplica um estado externo e propaga o efeito ao Order.

        **Webhook e consulta ativa passam exatamente por aqui**, o que torna
        impossível que os dois caminhos divirjam.

        A leitura sem lock existe apenas para descobrir `order_id`: o Order é
        travado primeiro, o Payment depois, e é a releitura **sob lock** que
        vale para a decisão.
        """
        unlocked = await self._uow.payments.get(payment_id)
        if unlocked is None:
            raise PaymentNotFoundError

        order = await self._uow.orders.get_for_update(unlocked.order_id)
        if order is None:  # pragma: no cover - FK garante a existência
            raise OrderNotFoundError

        payment = await self._uow.payments.get_for_update(payment_id)
        if payment is None:  # pragma: no cover - lido acima
            raise PaymentNotFoundError

        application = apply_provider_status(
            payment, reported_status, now, provider_payment_id=provider_payment_id
        )
        if not application.changed:
            return application

        await self._uow.payments.update(application.payment)

        status = application.payment.status
        if status is PaymentStatus.APPROVED:
            await self._uow.orders.update(mark_paid(order, now))
        elif status in TERMINAL_PAYMENT_STATUSES:
            # Terminal não aprovado devolve o Order a CONFIRMED, habilitando
            # nova tentativa comercial (§13.2).
            await self._uow.orders.update(release_for_new_attempt(order, now))
        # `PENDING` não move o Order: ele segue em PAYMENT_PENDING.

        return application

    async def process_webhook(
        self,
        *,
        provider: ProviderName,
        provider_event_id: str,
        provider_payment_id: str,
        reported_status: PaymentStatus,
        payload: Mapping[str, Any],
        at: datetime | None = None,
    ) -> WebhookProcessingResult:
        """Processa um evento de provider (§12).

        A idempotência do webhook é a unicidade `(provider,
        provider_event_id)` de `payment_events`, garantida por constraint de
        banco: evento repetido é registrado uma única vez e **nenhum efeito é
        reaplicado**. Não existe `IdempotencyRecord` separado para este
        caminho — a §11 exige idempotência, e é este o mecanismo que a
        entrega, sem um segundo registro que precisaria ser mantido coerente.

        Entra direto aqui, nunca no grafo do agente e nunca no LLM.
        """
        now = _now(at)
        async with self._uow:
            payment = await self._uow.payments.find_by_provider_payment_id(
                provider=provider, provider_payment_id=provider_payment_id
            )
            if payment is None:
                raise PaymentNotFoundError

            is_new = await self._uow.payment_events.record(
                PaymentEvent(
                    id=uuid.uuid4(),
                    payment_id=payment.id,
                    provider=provider,
                    provider_event_id=provider_event_id,
                    reported_status=reported_status,
                    payload=redact_event_payload(payload),
                    received_at=now,
                )
            )
            if not is_new:
                await self._uow.commit()
                return WebhookProcessingResult(
                    duplicate=True,
                    applied=False,
                    requires_reconciliation=False,
                    payment=payment,
                )

            application = await self._apply_reported_status(
                payment_id=payment.id,
                reported_status=reported_status,
                provider_payment_id=provider_payment_id,
                now=now,
            )
            await self._uow.commit()

        return WebhookProcessingResult(
            duplicate=False,
            applied=application.changed,
            requires_reconciliation=application.requires_reconciliation,
            payment=application.payment,
        )

    async def reconcile_payment(
        self, *, payment_id: uuid.UUID, at: datetime | None = None
    ) -> Payment:
        """Consulta o provider e aplica o estado oficial — retry técnico (§13.1).

        Mesmo `payment_id`, mesma idempotency key, **nenhum Payment novo,
        nenhum novo POST**. É o único caminho que resolve o estado externo
        desconhecido da §9.1.
        """
        now = _now(at)
        async with self._uow:
            payment = await self._uow.payments.get(payment_id)
        if payment is None:
            raise PaymentNotFoundError

        charge = await self._provider.get_charge(
            provider_payment_id=payment.provider_payment_id,
            idempotency_key=payment.idempotency_key,
        )

        async with self._uow:
            await self._uow.payment_events.record(
                PaymentEvent(
                    id=uuid.uuid4(),
                    payment_id=payment.id,
                    provider=payment.provider,
                    provider_event_id=_lookup_event_id(payment.id, charge.status),
                    reported_status=charge.status,
                    payload=redact_event_payload(charge.raw_payload or {}),
                    received_at=now,
                )
            )
            application = await self._apply_reported_status(
                payment_id=payment.id,
                reported_status=charge.status,
                provider_payment_id=charge.provider_payment_id,
                now=now,
            )
            # O resultado passou a ser conhecido: a key deixa de estar
            # `IN_PROGRESS`. `COMPLETED` inclui desfecho não aprovado (§11.1).
            await self._uow.idempotency.complete(
                operation=OPERATION_CREATE_PAYMENT,
                key=payment.idempotency_key,
                resource_id=payment.id,
                response_reference=charge.provider_payment_id,
                at=now,
            )
            await self._uow.commit()

        return application.payment

    async def get_payment(self, *, payment_id: uuid.UUID) -> Payment:
        """Consulta de leitura. Não altera estado nem consulta o provider."""
        async with self._uow:
            payment = await self._uow.payments.get(payment_id)
        if payment is None:
            raise PaymentNotFoundError
        return payment
