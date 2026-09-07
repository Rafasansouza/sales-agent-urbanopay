"""Ports do domínio de cartões (ADR-012, SPEC-002 §5, SPEC-005 §7).

Contratos comuns: entidades de domínio na saída, nunca ORM; sem commit;
nenhuma PII em exceção.

O módulo nasceu somente-leitura na SPEC-002 e não tem UoW próprio. A SPEC-005
§7 exige alterar o saldo, e a mutação vive **aqui**, sua casa natural: o
`CardBalanceRepository` é o port público por onde `fulfillment` credita, sem
nunca escrever na tabela `cards` pela própria infraestrutura. A dependência é
unidirecional — `cards` **nunca** importa `fulfillment` (ADR-001).

Não há conflito com a SPEC-002: ela tornou somente-leitura as *tools* daquele
escopo (§7), não a coluna. Nenhuma tool exposta ao agente credita saldo, e
`set_balance` segue proibida.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

    from urbanopay.modules.cards.domain.entities import Card


class CardRepository(Protocol):
    """Consulta de cartões, sempre escopada pelo cliente autenticado."""

    async def list_for_customer(self, customer_id: UUID) -> list[Card]: ...

    async def get_owned(self, customer_id: UUID, card_id: UUID) -> Card | None:
        """Cartão do cliente, em UMA única query com os dois filtros.

        `None` cobre indistintamente "não existe" e "pertence a outro
        cliente" — a aplicação traduz para `CARD_NOT_ACCESSIBLE` sem qualquer
        consulta prévia por `card_id` isolado (anti-enumeração, §5).
        """
        ...


class CardBalanceRepository(Protocol):
    """Mutação de saldo, restrita ao que a SPEC-005 §7 exige.

    Port deliberadamente **estreito**: trava, lê e credita. Não expõe
    atribuição arbitrária de saldo — não existe `set_balance`, nem aqui nem
    em lugar algum (SPEC-002 §16, SPEC-005 §16).

    Sem filtro de titularidade por decisão: quem chama é o fulfillment, e o
    `card_id` vem de `order.card_id`, já validado na criação do Order. Um
    filtro por `customer_id` aqui sugeriria que este port atende pedido de
    cliente, o que não é o caso.
    """

    async def get_for_update(self, card_id: UUID) -> Card | None:
        """Cartão com lock de linha (`SELECT ... FOR UPDATE`).

        Ordem global de lock: `Order → Approval → Payment → Card →
        Fulfillment`. O lock precisa ser adquirido **antes** de qualquer
        `INSERT` que referencie o cartão, porque uma chave estrangeira para
        `cards` faz o PostgreSQL travar a linha em `FOR KEY SHARE` — e elevar
        esse lock compartilhado a exclusivo, em duas transações concorrentes
        sobre o mesmo cartão, é deadlock.
        """
        ...

    async def apply_credit(self, *, card_id: UUID, new_balance: Decimal, at: datetime) -> None:
        """Persiste o novo saldo, já calculado pelo domínio.

        Recebe o saldo **resultante**, não um delta: o cálculo e suas
        invariantes (`balance_after = balance_before + amount`) pertencem ao
        domínio de fulfillment, que o registra no ledger na mesma transação.
        A persistência apenas grava — nunca arredonda, nunca soma.

        Exige que o chamador já tenha o lock de `get_for_update`.
        """
        ...
