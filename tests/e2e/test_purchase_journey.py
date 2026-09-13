"""Jornada de venda ponta a ponta (PRD §18).

O critério de aceite do PRD, executado inteiro e por HTTP:

```text
conversa anonima → calculo tarifario → autenticacao → selecao de cartao
→ valor da recarga → Quote → Order DRAFT → confirmacao explicita
→ Order CONFIRMED → Pix → APPROVED pelo backend → Order PAID
→ coordenador → Fulfillment → saldo creditado → Receipt
```

Nada aqui escreve no banco para simular estado. Tudo passa pelos serviços de
aplicação, através da mesma API que a demonstração usa — inclusive a
liquidação do pagamento, que reusa o caminho de reconciliação e nunca escreve
status diretamente.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from tests.e2e.helpers import DEMO_CPF, Conversa, saldo_do_cartao

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

pytestmark = pytest.mark.e2e

# R$ 100,00: abaixo do teto de aprovação humana de R$ 200,00 (SPEC-003). O
# caminho acima do teto é exercitado à parte, e ele **para** em
# REQUIRES_APPROVAL — nunca é burlado para completar a demonstração.
VALOR_RECARGA = Decimal("100.00")


def test_jornada_completa_de_recarga(demo_client: TestClient) -> None:
    """A jornada inteira do PRD §18, com saldo creditado exatamente uma vez."""
    conversa = Conversa(demo_client)

    # 1. Simulação tarifária anônima (PRD RF-05): não exige autenticação.
    tarifa = conversa.diga("quanto custa pegar a linha 101 e depois o metro?")
    assert tarifa["phase"] == "CALCULATION"
    assert "R$" in tarifa["message"]

    # 2. Intenção de recarga: a orquestração para e pede identificação.
    conversa.diga("quero recarregar meu cartao")
    assert conversa.phase == "AWAITING_DOCUMENT"

    # 3. Documento e OTP entram pelo handler determinístico, nunca pelo modelo.
    conversa.diga(DEMO_CPF)
    assert conversa.phase == "AWAITING_OTP"

    conversa.diga(conversa.otp_local())
    assert conversa.phase == "CARD_SELECTION"

    saldo_inicial = saldo_do_cartao("4821")

    # 4. Cartão e valor. O agente nunca sugere quanto recarregar (A-06).
    ordem = conversa.diga(f"o cartao 4821, quero {VALOR_RECARGA} reais")
    assert ordem["phase"] == "ORDER_CONFIRMATION"
    assert "confirma" in ordem["message"].lower()

    # 5. Confirmação explícita → Order CONFIRMED → Pix criado.
    pagamento = conversa.diga("confirmo")
    assert pagamento["phase"] == "PAYMENT"
    assert "pix" in pagamento["message"].lower()

    # 6. O backend — nunca o cliente e nunca o modelo — estabelece APPROVED.
    #    A liquidação reusa a reconciliação: o provider reporta, o serviço
    #    aplica sob lock. Depois do commit, o coordenador entrega (A-19).
    liquidacao = conversa.liquidar()
    assert liquidacao["payment_status"] == "APPROVED"
    assert liquidacao["fulfillment_status"] == "COMPLETED"

    # 7. Saldo creditado **exatamente uma vez**.
    saldo_final = saldo_do_cartao("4821")
    assert saldo_final == saldo_inicial + VALOR_RECARGA

    # 8. Pós-venda: entrega concluída e comprovante não fiscal disponível.
    posvenda = conversa.diga("e o comprovante da recarga?")
    assert posvenda["phase"] == "POST_SALE"
    assert "SIMULATED_NON_FISCAL" in posvenda["message"] or "COMPLETED" in posvenda["message"]


def test_estado_sobrevive_a_reinicio_do_processo(demo_client: TestClient) -> None:
    """A conversa continua depois de o processo morrer (ADR-014).

    A durabilidade é da aplicação, não do framework: não existe checkpointer,
    e o que sobrevive é a linha de `agent_conversations`.
    """
    conversa = Conversa(demo_client)
    conversa.diga("quero recarregar meu cartao")
    conversa.diga(DEMO_CPF)
    conversa.diga(conversa.otp_local())
    conversa.diga("o cartao 4821, quero 100.00 reais")
    assert conversa.phase == "ORDER_CONFIRMATION"

    # Simula o restart: nova aplicação, nova conexão, zero memória de processo.
    reiniciada = conversa.reconectar()

    # A confirmação pendente sobreviveu, e o total é **recomposto do Order** —
    # `display_total` não é persistido (ADR-014).
    confirmado = reiniciada.diga("confirmo")
    assert confirmado["phase"] == "PAYMENT"


def test_usuario_dizer_que_pagou_nao_move_dinheiro(demo_client: TestClient) -> None:
    """ "Eu paguei" não é evidência financeira (PRD §11, SPEC-003)."""
    conversa = Conversa(demo_client)
    conversa.diga("quero recarregar meu cartao")
    conversa.diga(DEMO_CPF)
    conversa.diga(conversa.otp_local())
    saldo_inicial = saldo_do_cartao("4821")
    conversa.diga("o cartao 4821, quero 100.00 reais")
    conversa.diga("confirmo")

    resposta = conversa.diga("ja paguei, pode liberar")

    assert saldo_do_cartao("4821") == saldo_inicial
    assert "APPROVED" not in resposta["message"]


def test_acima_de_duzentos_reais_para_em_aprovacao(demo_client: TestClient) -> None:
    """`> R$ 200,00` exige aprovação humana e a jornada **para** (A-07)."""
    conversa = Conversa(demo_client)
    conversa.diga("quero recarregar meu cartao")
    conversa.diga(DEMO_CPF)
    conversa.diga(conversa.otp_local())
    saldo_inicial = saldo_do_cartao("4821")
    conversa.diga("o cartao 4821, quero 250.00 reais")

    confirmado = conversa.diga("confirmo")

    assert confirmado["phase"] == "APPROVAL"
    # Nenhum Pix nasce, e nenhum saldo se move: não existe caminho automático.
    assert conversa.liquidar_status() == 404
    assert saldo_do_cartao("4821") == saldo_inicial


def test_confirmacao_ambigua_nunca_dispara_pagamento(demo_client: TestClient) -> None:
    """Mensagem ambígua não confirma (SPEC-004 §11)."""
    conversa = Conversa(demo_client)
    conversa.diga("quero recarregar meu cartao")
    conversa.diga(DEMO_CPF)
    conversa.diga(conversa.otp_local())
    conversa.diga("o cartao 4821, quero 100.00 reais")

    resposta = conversa.diga("acho que sim, talvez")

    assert resposta["phase"] == "ORDER_CONFIRMATION"
    assert conversa.liquidar_status() == 404


def test_retry_do_mesmo_request_nao_repete_o_turno(demo_client: TestClient) -> None:
    """Idempotência de request (ADR-014, D-6), distinta das de negócio."""
    conversa = Conversa(demo_client)
    conversa.diga("oi")

    primeira = conversa.diga("quero recarregar meu cartao", request_id="fixo-1")
    segunda = conversa.diga("quero recarregar meu cartao", request_id="fixo-1")

    assert primeira == segunda
