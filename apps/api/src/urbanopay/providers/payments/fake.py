"""`FakePaymentProvider` — provider determinístico para dev e testes.

Fonte: ADR-007, ADR-010. Nenhuma chamada de rede, nenhuma credencial,
nenhum dado real. É o único provider usado na CI: nenhum teste depende de rede
externa.

Determinismo por construção: o comportamento é programado pelo teste, nunca
sorteado. O objetivo é permitir exercitar exatamente os cenários que a SPEC-003
§17 exige — timeout, recusa determinística, aprovação, expiração — de forma
reprodutível.

Este dublê **não** decide regra de negócio: ele apenas simula o que um provider
externo responderia. Quem decide efeito é o `PaymentService`.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

from urbanopay.modules.payments.domain.entities import ProviderCharge
from urbanopay.modules.payments.domain.enums import PaymentStatus, ProviderName
from urbanopay.modules.payments.domain.errors import (
    PaymentCreationFailedError,
    PaymentProviderTimeoutError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from decimal import Decimal


class FakePaymentProvider:
    """Implementa o port `PaymentProvider` de forma programável.

    Modos de criação:

    - padrão: devolve `PENDING` com identificador externo determinístico;
    - `fail_with`: levanta a exceção informada na próxima criação, uma vez —
      é assim que se testa timeout sem tornar o provider inutilizável;
    - `create_status`: força o status devolvido na criação.

    As cobranças criadas ficam registradas em memória, e `get_charge` devolve o
    estado corrente — o que permite simular a confirmação do pagamento pelo
    provider com `settle`.
    """

    def __init__(
        self,
        *,
        create_status: PaymentStatus = PaymentStatus.PENDING,
        name: ProviderName = ProviderName.FAKE,
    ) -> None:
        self._name = name
        self._create_status = create_status
        self._charges: dict[str, PaymentStatus] = {}
        self._keys_to_ids: dict[str, str] = {}
        self._sequence: Iterator[int] = itertools.count(1)
        self._fail_once: Exception | None = None
        self._register_before_failing = False
        self.create_calls = 0
        self.lookup_calls = 0

    @property
    def name(self) -> ProviderName:
        return self._name

    # --- programação do dublê --------------------------------------------

    def fail_next_create(self, error: Exception) -> None:
        """Faz a próxima criação levantar `error`, uma única vez."""
        self._fail_once = error

    def fail_next_create_with_timeout(self) -> None:
        """Timeout **antes** de o provider registrar qualquer cobrança."""
        self.fail_next_create(PaymentProviderTimeoutError())

    def register_then_timeout_on_next_create(self) -> None:
        """Timeout **depois** de o provider registrar a cobrança.

        Este é o cenário perigoso da §9.1: existe cobrança no lado do
        provider, e o nosso lado não sabe. É o caso que uma retentativa cega
        transformaria em cobrança dupla, e o que a consulta por idempotency
        key precisa resolver.
        """
        self._register_before_failing = True
        self.fail_next_create(PaymentProviderTimeoutError())

    def fail_next_create_deterministically(self) -> None:
        """Atalho para recusa determinística de criação (§9)."""
        self.fail_next_create(PaymentCreationFailedError())

    def settle(self, provider_payment_id: str, status: PaymentStatus) -> None:
        """Define o estado que a consulta passará a reportar.

        Simula o provider confirmando, recusando ou expirando a cobrança. É o
        único caminho pelo qual um pagamento se torna `APPROVED` nos testes —
        exatamente como em produção, onde só o provider estabelece isso.
        """
        self._charges[provider_payment_id] = status

    def charge_id_for_key(self, idempotency_key: str) -> str | None:
        """Identificador externo associado a uma idempotency key, se existir."""
        return self._keys_to_ids.get(idempotency_key)

    # --- port -------------------------------------------------------------

    async def create_pix_charge(
        self,
        *,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
        external_reference: str,
    ) -> ProviderCharge:
        """Cria a cobrança, respeitando a idempotency key.

        A mesma key devolve a **mesma** cobrança, como um provider idempotente
        faria: é o que permite ao teste de retry técnico provar que nenhuma
        segunda cobrança nasce.
        """
        self.create_calls += 1
        del amount, currency, external_reference  # o dublê não valida valores.

        if self._fail_once is not None:
            error, self._fail_once = self._fail_once, None
            if self._register_before_failing:
                self._register_before_failing = False
                self._charge_for(idempotency_key)
            raise error

        provider_payment_id = self._charge_for(idempotency_key)
        return ProviderCharge(
            provider_payment_id=provider_payment_id,
            status=self._charges[provider_payment_id],
            qr_code=_qr_code_for(provider_payment_id),
        )

    def _charge_for(self, idempotency_key: str) -> str:
        """Cobrança associada à key, criando-a na primeira vez.

        A mesma key **sempre** devolve a mesma cobrança, como um provider
        idempotente faria.
        """
        existing_id = self._keys_to_ids.get(idempotency_key)
        if existing_id is not None:
            return existing_id
        provider_payment_id = f"fake-charge-{next(self._sequence)}"
        self._keys_to_ids[idempotency_key] = provider_payment_id
        self._charges[provider_payment_id] = self._create_status
        return provider_payment_id

    async def get_charge(
        self, *, provider_payment_id: str | None, idempotency_key: str
    ) -> ProviderCharge:
        """Consulta o estado corrente, por identificador externo ou por key.

        Aceitar a key é o que torna possível resolver o estado desconhecido da
        §9.1, em que o identificador externo pode nunca ter chegado.
        """
        self.lookup_calls += 1
        charge_id = provider_payment_id or self._keys_to_ids.get(idempotency_key)
        if charge_id is None or charge_id not in self._charges:
            # Nenhuma cobrança criada para esta key: o timeout ocorreu antes
            # de o provider registrar qualquer coisa.
            raise PaymentProviderTimeoutError
        return ProviderCharge(
            provider_payment_id=charge_id,
            status=self._charges[charge_id],
            qr_code=_qr_code_for(charge_id),
        )


def _qr_code_for(provider_payment_id: str) -> str:
    """Código Pix simulado. Não é credencial e nunca é persistido."""
    return f"00020126FAKE{provider_payment_id}5204000053039865802BR"
