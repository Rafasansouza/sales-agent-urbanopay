"""Fábrica de sessões assíncronas.

Fonte: ADR-012.

Regras:

- `expire_on_commit=False`: objetos não disparam SELECT após o commit;
- a sessão **não** é singleton: uma sessão por unidade de trabalho;
- uma `AsyncSession` nunca é compartilhada entre tasks concorrentes;
- a sessão é entregue ao Unit of Work, nunca a routers nem ao domínio;
- nenhum commit automático: a fronteira transacional é da camada de
  aplicação, via `UnitOfWork`.

A dependência FastAPI "uma sessão por request" prevista no ADR-012 será
materializada quando o primeiro endpoint consumir o banco — hoje nenhum
consome.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Cria a fábrica de sessões ligada ao engine.

    A fábrica é barata e segura de compartilhar; as **sessões** produzidas por
    ela não são.
    """
    return async_sessionmaker(bind=engine, expire_on_commit=False)
