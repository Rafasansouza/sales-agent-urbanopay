"""`FakeLLMProvider` — provider determinístico para dev, testes e CI.

Fonte: ADR-010, ADR-015. Nenhuma rede, nenhuma credencial, nenhum dado real.

Determinismo por construção: a classificação é uma função pura do texto. É o
que permite aos evals de SPEC-004 §16 exigirem **falso positivo zero** em
confirmação crítica — uma métrica que um modelo real não entrega de forma
reprodutível em CI.

Regra que este arquivo materializa, e que é a razão de ele ser seguro: **o
Fake não tem caminho de negócio próprio**. Ele implementa o mesmo port e
devolve os mesmos contratos do provider real. Se uma decisão crítica
dependesse de qual provider está ativo, a suíte deixaria de provar qualquer
coisa sobre produção.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

from urbanopay.providers.llm.base import (
    AgentIntent,
    ConfirmationDecision,
    ModelResponse,
    TripSegmentDraft,
    TurnContext,
    TurnUnderstanding,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from urbanopay.providers.llm.base import TurnFact

_NUMBER = r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+[.,]\d{2}|\d+"

# Valor com marcador explícito de dinheiro — "R$ 100", "100,00 reais" — tem
# prioridade sobre número solto. É o que separa "quero 100 reais" de "o cartao
# 4821" quando os dois aparecem na mesma frase.
_AMOUNT_MARKED = re.compile(
    rf"(?:r\$\s*({_NUMBER})|({_NUMBER})\s*(?:reais|real|conto))",
)
_AMOUNT_LOOSE = re.compile(rf"\b({_NUMBER})\b")
_BUS_LINE = re.compile(r"\b(?:linha\s*)?(\d{3})\b")
_CARD_HINT = re.compile(r"\b(\d{4})\b")

_AFFIRMATIVE: Final = (
    "sim",
    "confirmo",
    "confirmar",
    "pode confirmar",
    "isso mesmo",
    "aceito",
    "ok",
    "pode ser",
    "fechado",
    "quero sim",
)
_NEGATIVE: Final = ("nao", "não", "cancela", "cancelar", "desisto", "melhor nao", "nao quero")
# Palavras que *parecem* confirmação mas não são. Um "acho que sim" nunca pode
# virar pagamento (SPEC-004 §11).
_HEDGING: Final = ("talvez", "acho que", "quem sabe", "sei la", "pode ser que", "nao sei")


def _normalize(text: str) -> str:
    lowered = text.strip().lower()
    for accented, plain in (
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"), ("ó", "o"),
        ("ô", "o"), ("õ", "o"), ("ú", "u"), ("ç", "c"),
    ):  # fmt: skip
        lowered = lowered.replace(accented, plain)
    return lowered


def _parse_amount(text: str) -> str | None:
    """Extrai o valor da recarga como string decimal, ou `None`.

    Duas passadas, e a ordem é o que importa: primeiro um número com marcador
    explícito de dinheiro ("R$ 100", "100 reais"); só então um número solto.
    Sem essa prioridade, "o cartao 4821, quero 100 reais" leria 4821 como
    valor — e um dígito de cartão viraria uma cobrança de quatro mil reais.

    Nunca usa `float` em ponto algum do caminho (ADR-012). A validação de faixa
    e de escala pertence ao domínio; aqui só se reconhece o número.
    """
    marked = _AMOUNT_MARKED.search(text)
    raw = (marked.group(1) or marked.group(2)) if marked else None
    if raw is None:
        loose = _AMOUNT_LOOSE.search(text)
        raw = loose.group(1) if loose else None
    if raw is None:
        return None

    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return str(Decimal(raw).quantize(Decimal("0.01")))
    except InvalidOperation:  # pragma: no cover - regex já restringe o formato
        return None


def _extract_segments(text: str) -> list[TripSegmentDraft]:
    """Monta os segmentos na ordem em que aparecem na frase.

    A ordem importa: ela é o trajeto. `METRO` nunca recebe `line_code` — o
    Fare Engine recusa metrô com linha (`INVALID_SEGMENT_STRUCTURE`).
    """
    segments: list[tuple[int, TripSegmentDraft]] = []
    for match in _BUS_LINE.finditer(text):
        segments.append((match.start(), TripSegmentDraft(mode="BUS", line_code=match.group(1))))
    for keyword in ("metro", "metrô"):
        start = text.find(keyword)
        while start != -1:
            segments.append((start, TripSegmentDraft(mode="METRO", line_code=None)))
            start = text.find(keyword, start + 1)
            break
    return [segment for _, segment in sorted(segments, key=lambda pair: pair[0])]


def _read_confirmation(text: str, context: TurnContext) -> ConfirmationDecision | None:
    """Lê a resposta a um pedido de confirmação.

    Só produz decisão quando existe confirmação pendente: fora desse contexto,
    um "sim" solto não é resposta a nada. Hesitação vira `AMBIGUOUS` **antes**
    de qualquer teste de afirmação, para que "acho que sim" nunca seja lido
    como "sim".
    """
    if not context.has_pending_confirmation:
        return None
    if any(hedge in text for hedge in _HEDGING):
        return ConfirmationDecision.AMBIGUOUS
    if any(word in text for word in _NEGATIVE):
        return ConfirmationDecision.REJECTED
    if any(word in text for word in _AFFIRMATIVE):
        return ConfirmationDecision.CONFIRMED
    return ConfirmationDecision.AMBIGUOUS


# Fases em que a conversa já está dentro de uma recarga. Nelas, uma mensagem
# com valor ou cartão é continuação da jornada — não o começo de outra. Um
# modelo real chega à mesma conclusão pelo mesmo caminho: o contexto do turno
# carrega a fase (`TurnContext`).
_RECHARGE_PHASES: Final = ("CARD_SELECTION", "QUOTE", "ORDER_CONFIRMATION")


def _classify(text: str, context: TurnContext) -> AgentIntent:
    if any(word in text for word in ("saldo", "quanto tenho", "quanto ha no cartao")):
        return AgentIntent.CHECK_BALANCE
    if any(word in text for word in ("paguei", "pagamento", "pix", "ja paguei")):
        return AgentIntent.CHECK_PAYMENT
    if any(word in text for word in ("comprovante", "recibo", "entrega", "recarregou")):
        return AgentIntent.CHECK_ORDER
    if any(word in text for word in ("bilhete", "passe diario", "pacote 10", "ticket")):
        return AgentIntent.BUY_TICKET
    if any(word in text for word in ("recarregar", "recarga", "carregar o cartao", "por credito")):
        return AgentIntent.RECHARGE_CARD
    if context.phase in _RECHARGE_PHASES:
        return AgentIntent.RECHARGE_CARD
    if any(word in text for word in ("quanto custa", "tarifa", "preco", "custo", "quanto fica")):
        return AgentIntent.CALCULATE_TRIP_COST
    if _extract_segments(text):
        return AgentIntent.CALCULATE_TRIP_COST
    if any(word in text for word in ("produto", "opcoes", "o que voces tem")):
        return AgentIntent.DISCOVER_PRODUCT
    return AgentIntent.GENERAL_TRANSPORT_HELP


class FakeLLMProvider:
    """Implementa `LLMProvider` por regra pura sobre o texto."""

    def __init__(self) -> None:
        self.understand_calls = 0
        self.compose_calls = 0

    @property
    def name(self) -> str:
        return "fake"

    async def understand(self, *, message: str, context: TurnContext) -> TurnUnderstanding:
        self.understand_calls += 1
        text = _normalize(message)
        confirmation = _read_confirmation(text, context)
        intent = _classify(text, context)
        # Segmentos só existem quando a conversa é sobre trajeto: num turno de
        # recarga, "100.00" não pode virar linha de ônibus.
        segments = _extract_segments(text) if intent is AgentIntent.CALCULATE_TRIP_COST else []

        declared: str | None = None
        if "meia" in text or "estudante" in text:
            declared = "MEIA"
        elif "integral" in text or "inteira" in text:
            declared = "INTEGRAL"

        card_hint: str | None = None
        if context.authenticated and intent is not AgentIntent.CALCULATE_TRIP_COST:
            hint = _CARD_HINT.search(text)
            if hint is not None:
                card_hint = hint.group(1)

        # O valor só é lido quando a conversa é de recarga — um "101" de linha
        # não vira R$ 101,00 — e o texto perde antes os dígitos já consumidos
        # pelo cartão, que competem pelo mesmo padrão numérico.
        amount = None
        if intent is AgentIntent.RECHARGE_CARD:
            sem_cartao = text.replace(card_hint, " ", 1) if card_hint else text
            amount = _parse_amount(sem_cartao)

        return TurnUnderstanding(
            intent=intent,
            segments=segments,
            declared_fare_profile=declared,
            recharge_amount=amount,
            card_hint=card_hint,
            confirmation=confirmation,
            wants_authentication=any(
                word in text for word in ("entrar", "login", "me identificar", "meu cpf")
            ),
        )

    async def compose_reply(
        self, *, message: str, context: TurnContext, facts: Sequence[TurnFact]
    ) -> ModelResponse:
        """Resposta determinística a partir dos fatos.

        Não inventa número: tudo o que aparece vem de `facts`, que os
        presenters já sanitizaram. Sem fato, não há afirmação.
        """
        del message
        if not facts:
            return ModelResponse(message=_NO_FACTS.get(context.phase, _DEFAULT_REPLY))

        rendered = [part for part in (_render(fact) for fact in facts) if part]
        if not rendered:
            # Nenhum fato rendeu frase: melhor orientar pela fase do que
            # devolver uma resposta vazia.
            return ModelResponse(message=_NO_FACTS.get(context.phase, _DEFAULT_REPLY))
        return ModelResponse(message=" ".join(rendered))


_DEFAULT_REPLY: Final = (
    "Posso calcular a tarifa de um trajeto ou recarregar seu cartao. Como posso ajudar?"
)

_NO_FACTS: Final[dict[str, str]] = {
    "AWAITING_DOCUMENT": "Para continuar, informe seu CPF.",
    "AWAITING_OTP": "Enviei um codigo de verificacao. Informe o codigo para continuar.",
    "AUTHENTICATION": "Para operacoes na sua conta preciso te identificar. Informe seu CPF.",
    "CARD_SELECTION": "Qual cartao voce quer usar?",
    "QUOTE": "Qual valor voce quer recarregar?",
}


def _render(fact: TurnFact) -> str:
    """Frase para um fato, sempre derivada do envelope — nunca de memória."""
    data = fact.data
    if not fact.ok:
        return _ERROR_PHRASES.get(fact.code, f"Nao consegui concluir ({fact.code}).")

    if fact.result_type == "FARE_CALCULATION":
        return f"O valor do trajeto e R$ {data.get('total')} ({data.get('trip_type')})."
    if fact.result_type == "CARD_LIST":
        cards = data.get("cards")
        count = len(cards) if isinstance(cards, list) else 0
        return f"Encontrei {count} cartao(oes) na sua conta."
    if fact.result_type == "CARD_BALANCE":
        return f"O saldo do cartao {data.get('masked_number')} e R$ {data.get('balance')}."
    if fact.result_type == "CARD_DETAILS":
        return (
            f"Cartao {data.get('masked_number')}, perfil {data.get('fare_profile')}, "
            f"situacao {data.get('status')}."
        )
    if fact.result_type == "QUOTE":
        return f"Orcamento gerado: R$ {data.get('total')}."
    if fact.result_type == "ORDER":
        return _order_phrase(data)
    if fact.result_type == "PAYMENT":
        return f"Pix gerado no valor de R$ {data.get('amount')}. Assim que for pago eu confirmo."
    if fact.result_type == "PAYMENT_STATUS":
        return f"A situacao do pagamento e {data.get('status')}."
    if fact.result_type == "FULFILLMENT_STATUS":
        return f"A entrega esta em {data.get('status')}."
    if fact.result_type == "RECEIPT":
        return (
            f"Recarga concluida: R$ {data.get('amount')} no cartao {data.get('card_last4')}. "
            f"Comprovante {data.get('document_kind')}."
        )
    if fact.result_type == "AUTHENTICATION_CHALLENGE":
        return "Enviei um codigo de verificacao. Informe o codigo para continuar."
    if fact.result_type == "AUTHENTICATION_VERIFICATION":
        return "Tudo certo, voce esta autenticado."
    if fact.result_type == "AUTHENTICATION_STATUS":
        # Sessão anônima: a jornada para aqui e pede o documento. Sem esta
        # frase a resposta sairia vazia, e uma resposta vazia é pior que uma
        # recusa — o cliente não saberia o que fazer.
        return (
            ""
            if data.get("authenticated") is True
            else "Para continuar preciso te identificar. Informe seu CPF."
        )
    return ""


def _order_phrase(data: dict[str, object]) -> str:
    status = data.get("status")
    if status == "DRAFT":
        return f"Pedido criado no valor de R$ {data.get('total')}. Voce confirma?"
    if status == "REQUIRES_APPROVAL":
        return (
            "Pedido confirmado. Por ser acima de R$ 200,00, ele depende de aprovacao "
            "humana antes do pagamento."
        )
    if status == "CONFIRMED":
        return "Pedido confirmado. Vou gerar o Pix."
    return f"Seu pedido esta em {status}."


_ERROR_PHRASES: Final[dict[str, str]] = {
    "NO_PENDING_CONFIRMATION": "Nao ha nada aguardando confirmacao no momento.",
    "CONFIRMATION_CONTEXT_MISMATCH": "Esse pedido nao e o que esta aguardando confirmacao.",
    "TOOL_UNAVAILABLE": "Essa funcionalidade ainda nao esta disponivel.",
    "TOOL_NOT_AUTHORIZED": "Nao tenho permissao para fazer isso.",
    "CARD_NOT_ACCESSIBLE": "Nao encontrei esse cartao na sua conta.",
    "CARD_NOT_ACTIVE": "Esse cartao nao esta ativo.",
    "SESSION_EXPIRED": "Sua sessao expirou. Informe seu CPF novamente.",
    "NOT_AUTHENTICATED": "Para isso preciso te identificar. Informe seu CPF.",
    "OTP_INVALID": "Codigo incorreto. Tente novamente.",
    "OTP_EXPIRED": "O codigo expirou. Vou enviar outro.",
    "INVALID_RECHARGE_AMOUNT": "Esse valor nao e valido para recarga.",
    "PAYMENT_STATUS_UNKNOWN": (
        "Ainda nao consegui confirmar o pagamento anterior. Nao vou gerar outra cobranca."
    ),
    "ORDER_ALREADY_PAID": "Esse pedido ja foi pago.",
    "EMPTY_TRIP": "Me diga o trajeto: quais linhas ou modais voce vai usar?",
}
