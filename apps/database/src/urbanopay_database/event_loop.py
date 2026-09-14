"""Compatibilidade de event loop para psycopg assíncrono em Windows.

Fonte: ADR-012, seção "Windows e o event loop".

O psycopg em modo assíncrono não funciona sobre o `ProactorEventLoop`, que é o
event loop padrão do Python em Windows. Este módulo é o **único** ponto do
projeto que conhece esse detalhe de sistema operacional.

Pontos de uso:

- testes: `tests/conftest.py` implementa o hook `pytest_asyncio_loop_factories`
  (somente em Windows) usando `selector_loop_factory`;
- runtime futuro: quando a API passar a consumir o banco, o boot deve chamar
  `ensure_selector_event_loop_policy()` antes de criar o event loop.

⚠️ Nota de compatibilidade: esta solução é específica do **Python 3.13**. As
APIs de event loop policy (`get/set_event_loop_policy`) estão em processo de
depreciação e este módulo deve ser revisto antes de uma futura migração para
Python 3.14+ — a direção do ecossistema é `loop_factory` (como em
`asyncio.Runner`), que `selector_loop_factory` já atende.

Regras deste módulo:

- nenhuma política é aplicada em import de módulo;
- nenhum efeito em plataformas que não sejam Windows;
- nenhuma chamada a `set_event_loop_policy` fora daqui.
"""

from __future__ import annotations

import asyncio
import sys


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """Cria um `SelectorEventLoop`, compatível com psycopg async.

    Existe em todas as plataformas; em Linux e macOS o selector já é o
    comportamento padrão, então usá-lo não altera nada.
    """
    return asyncio.SelectorEventLoop()


def _windows_selector_policy() -> type[asyncio.AbstractEventLoopPolicy] | None:
    """Resolve dinamicamente a classe de política exclusiva de Windows.

    `asyncio.WindowsSelectorEventLoopPolicy` só existe em Windows. A resolução
    via `getattr` — encapsulada aqui, e somente aqui — evita qualquer acesso
    estático a API Windows-only, que reprovaria o mypy analisando o projeto em
    Linux e impediria os testes de exercitarem este caminho em outras
    plataformas.
    """
    policy: type[asyncio.AbstractEventLoopPolicy] | None = getattr(
        asyncio, "WindowsSelectorEventLoopPolicy", None
    )
    return policy


def ensure_selector_event_loop_policy() -> bool:
    """Aplica a política de selector em Windows, se ainda não aplicada.

    Devolve `True` quando a política foi alterada por esta chamada e `False`
    quando nada foi feito — plataforma não-Windows, política já compatível ou
    classe indisponível.

    Deve ser chamada **antes** da criação do event loop (por exemplo, antes de
    `asyncio.run` ou do boot do servidor ASGI), nunca dentro de um loop em
    execução.
    """
    if sys.platform != "win32":
        return False

    policy_cls = _windows_selector_policy()
    if policy_cls is None:  # pragma: no cover - impossível em CPython/Windows
        return False

    if isinstance(asyncio.get_event_loop_policy(), policy_cls):
        return False

    asyncio.set_event_loop_policy(policy_cls())
    return True
