"""Testes do helper de event loop para psycopg async em Windows.

Fonte: ADR-012, seção "Windows e o event loop".
"""

from __future__ import annotations

import asyncio
import selectors
import sys

import pytest

from urbanopay.core.event_loop import (
    ensure_selector_event_loop_policy,
    selector_loop_factory,
)


@pytest.mark.unit
def test_factory_produz_selector_event_loop() -> None:
    """A factory entrega um SelectorEventLoop, compatível com psycopg async."""
    loop = selector_loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
        # O seletor subjacente é o mecanismo que o psycopg exige.
        assert isinstance(loop._selector, selectors.BaseSelector)  # type: ignore[attr-defined]
    finally:
        loop.close()


@pytest.mark.unit
def test_loop_da_factory_executa_corrotina() -> None:
    """O loop produzido é funcional, não apenas do tipo certo."""

    async def probe() -> str:
        await asyncio.sleep(0)
        return "ok"

    loop = selector_loop_factory()
    try:
        assert loop.run_until_complete(probe()) == "ok"
    finally:
        loop.close()


@pytest.mark.unit
def test_ensure_policy_e_noop_fora_do_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Em plataformas não-Windows a função não toca a política global.

    O módulo lê `sys.platform` no momento da chamada; o monkeypatch cobre a
    verificação e é revertido automaticamente ao fim do teste.
    """
    monkeypatch.setattr(sys, "platform", "linux")

    applied_before = asyncio.get_event_loop_policy()
    assert ensure_selector_event_loop_policy() is False
    assert asyncio.get_event_loop_policy() is applied_before


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "win32", reason="comportamento específico de Windows")
def test_ensure_policy_aplica_selector_no_windows() -> None:
    """Em Windows, a política resultante é a de selector — e a chamada é idempotente."""
    original = asyncio.get_event_loop_policy()
    try:
        ensure_selector_event_loop_policy()
        assert isinstance(
            asyncio.get_event_loop_policy(),
            asyncio.WindowsSelectorEventLoopPolicy,
        )
        # Segunda chamada não tem nada a fazer.
        assert ensure_selector_event_loop_policy() is False
    finally:
        asyncio.set_event_loop_policy(original)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hook_do_pytest_asyncio_usa_selector_no_windows() -> None:
    """Prova fim a fim que os testes async rodam no loop compatível.

    Em Windows este teste só passa se o hook `pytest_asyncio_loop_factories`
    do conftest estiver fornecendo o SelectorEventLoop — é a validação real do
    mecanismo, não da intenção. Fora do Windows, o loop padrão já é selector.
    """
    loop = asyncio.get_running_loop()
    if sys.platform == "win32":
        assert isinstance(loop, asyncio.SelectorEventLoop), (
            "teste async rodando fora do SelectorEventLoop: o hook "
            "pytest_asyncio_loop_factories não está em efeito"
        )
    else:
        assert loop is not None
