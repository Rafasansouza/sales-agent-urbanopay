"""Dataset de demonstração — **somente `APP_ENV=local`** (A-12).

A-12 decidiu que identidades e cartões **não** têm seed em migration: diferente
das tarifas, não são dados de referência obrigatórios. E registrou que "um seed
demonstrativo oficial reproduzível poderá ser criado quando existir a jornada
E2E real (SPEC-004) — decisão adiada, não esquecida".

A jornada existe agora. Este é esse seed, com três restrições:

- **fora de migration**, preservando a decisão de A-12: o schema não carrega
  cliente algum, e um ambiente que não seja `local` nasce vazio;
- **somente dados fictícios**, conforme o dataset sugerido em SPEC-002 §13.
  Nenhum CPF, nome ou telefone real, em nenhum ambiente;
- **idempotente**: rodar duas vezes não duplica nada, porque a unicidade do
  CPF normalizado é constraint de banco.

O saldo aqui é escrito **diretamente**, e isso é legítimo exatamente porque não
é uma operação de negócio: é a condição inicial de um ambiente de demonstração,
equivalente a um cliente que já tinha saldo antes de o sistema existir. Toda
mudança de saldo **depois** disso passa pelo ledger, em transação atômica.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, NamedTuple

import sqlalchemy as sa

from urbanopay_domains.cards.infrastructure.models import CardModel
from urbanopay_domains.identity.infrastructure.models import CustomerModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from urbanopay_domains.identity.domain.value_objects import IdentityHasher


class DemoCard(NamedTuple):
    last4: str
    fare_profile: str
    status: str
    balance: str


class DemoCustomer(NamedTuple):
    name: str
    cpf: str
    cards: tuple[DemoCard, ...]


# Dataset de SPEC-002 §13. CPFs fictícios, **deliberadamente distintos** dos
# usados pelas fixtures de teste: o seed de demonstração e os testes convivem
# no mesmo banco local, e a unicidade do CPF normalizado é constraint — dados
# de demo colidindo com dados de teste quebrariam a suíte sem nada a ver com o
# comportamento sob teste. Nenhum destes corresponde a pessoa real.
DEMO_DATASET: Final[tuple[DemoCustomer, ...]] = (
    DemoCustomer(
        name="Mariana Souza",
        cpf="70011122233",
        cards=(DemoCard("4821", "MEIA", "ACTIVE", "21.50"),),
    ),
    DemoCustomer(
        name="Lucas Pereira",
        cpf="70044455566",
        cards=(DemoCard("1257", "INTEGRAL", "ACTIVE", "42.00"),),
    ),
    DemoCustomer(
        name="Camila Rocha",
        cpf="70077788899",
        cards=(DemoCard("7934", "INTEGRAL", "BLOCKED", "10.00"),),
    ),
)


async def seed_demo_dataset(
    session_factory: async_sessionmaker[AsyncSession], *, hasher: IdentityHasher
) -> int:
    """Insere o dataset, pulando o que já existe. Devolve quantos clientes nasceram."""
    now = datetime.now(UTC)
    created = 0
    async with session_factory() as session:
        for customer in DEMO_DATASET:
            if await _insert_customer(session, customer, hasher=hasher, now=now):
                created += 1
        await session.commit()
    return created


async def _insert_customer(
    session: AsyncSession,
    customer: DemoCustomer,
    *,
    hasher: IdentityHasher,
    now: datetime,
) -> bool:
    """Insere um cliente e seus cartões, se ele ainda não existir.

    A verificação é por `cpf_hash`, que é o identificador de lookup — o CPF em
    si não é persistido em lugar algum (SPEC-002 §2).
    """
    cpf_hash = hasher.hash_cpf(customer.cpf)
    existing = (
        await session.execute(sa.select(CustomerModel.id).where(CustomerModel.cpf_hash == cpf_hash))
    ).scalar_one_or_none()
    if existing is not None:
        return False

    customer_id = uuid.uuid4()
    session.add(
        CustomerModel(
            id=customer_id,
            name=customer.name,
            cpf_hash=cpf_hash,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
    )
    # Flush explícito antes dos cartões: sem relationship declarada entre
    # `CardModel` e `CustomerModel` — os models não se conhecem, por decisão de
    # ADR-012 — a unidade de trabalho não tem como inferir a ordem de inserção,
    # e a chave estrangeira falharia.
    await session.flush()

    for card in customer.cards:
        session.add(
            CardModel(
                id=uuid.uuid4(),
                customer_id=customer_id,
                card_last4=card.last4,
                fare_profile=card.fare_profile,
                balance=Decimal(card.balance),
                status=card.status,
                expires_at=now + timedelta(days=730),
                created_at=now,
                updated_at=now,
            )
        )
    return True
