"""Testes do helper de event loop para psycopg async em Windows.

Fonte: ADR-012, seção "Windows e o event loop".

Restrição de portabilidade: `asyncio.WindowsSelectorEventLoopPolicy` só existe
em Windows, e este arquivo é analisado pelo mypy também em Linux (CI). Nenhum
acesso estático a essa API é permitido aqui — o caminho win32 é exercitado com
`monkeypatch(..., raising=False)`, e a validação em Windows real resolve a
classe dinamicamente.
"""

from __future__ import annotations

import asyncio
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
        # SelectorEventLoop é o mecanismo que o psycopg async exige.
        assert isinstance(loop, asyncio.SelectorEventLoop)
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
def test_ensure_policy_aplica_selector_no_caminho_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O caminho win32 aplica a política de selector — testável em qualquer SO.

    `asyncio.WindowsSelectorEventLoopPolicy` não existe fora do Windows, então
    o teste simula a plataforma e a presença da classe com
    `monkeypatch(..., raising=False)`, sem nenhum acesso estático à API
    Windows-only — que reprovaria o mypy no runner Linux.
    """

    class FakeSelectorPolicy:
        """Substitui a classe Windows-only durante o teste."""

    applied: list[object] = []

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        asyncio, "WindowsSelectorEventLoopPolicy", FakeSelectorPolicy, raising=False
    )
    # Política vigente não é a de selector: a função deve trocá-la.
    monkeypatch.setattr(asyncio, "get_event_loop_policy", lambda: object())
    monkeypatch.setattr(asyncio, "set_event_loop_policy", applied.append)

    assert ensure_selector_event_loop_policy() is True
    assert len(applied) == 1
    assert isinstance(applied[0], FakeSelectorPolicy)


@pytest.mark.unit
def test_ensure_policy_e_idempotente_no_caminho_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Com a política de selector já vigente, nada é alterado."""

    class FakeSelectorPolicy:
        """Substitui a classe Windows-only durante o teste."""

    applied: list[object] = []

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        asyncio, "WindowsSelectorEventLoopPolicy", FakeSelectorPolicy, raising=False
    )
    monkeypatch.setattr(asyncio, "get_event_loop_policy", lambda: FakeSelectorPolicy())
    monkeypatch.setattr(asyncio, "set_event_loop_policy", applied.append)

    assert ensure_selector_event_loop_policy() is False
    assert applied == []


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "win32", reason="validação real apenas em Windows")
def test_ensure_policy_no_windows_real() -> None:
    """Em Windows de verdade, a política aplicada é a nativa de selector.

    A classe é resolvida dinamicamente (`getattr` com default), nunca por
    acesso estático — o corpo deste teste é analisado pelo mypy também em
    Linux, onde o atributo não existe no typeshed.
    """
    policy_cls: type[asyncio.AbstractEventLoopPolicy] | None = getattr(
        asyncio, "WindowsSelectorEventLoopPolicy", None
    )
    assert policy_cls is not None, "CPython em Windows sempre expõe a política de selector"

    original = asyncio.get_event_loop_policy()
    try:
        ensure_selector_event_loop_policy()
        assert isinstance(asyncio.get_event_loop_policy(), policy_cls)
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
