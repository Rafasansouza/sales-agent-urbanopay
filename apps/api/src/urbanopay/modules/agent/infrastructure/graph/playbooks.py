"""Playbooks determinísticos do turno (SPEC-004 §2, §9.1; ADR-005).

**Aqui mora a orquestração, e ela é código.** O modelo diz o que o cliente
parece querer; a sequência de tools que realiza isso é decidida por estas
funções, não por ele. É a materialização da fronteira de ADR-005: *"o modelo
pode sugerir uma ação; o sistema decide se ela existe, é válida e pode ser
executada."*

Três invariantes governam este arquivo:

1. **comando crítico nunca recebe identificador do modelo** — `confirm_order` e
   `create_payment` derivam do contexto (§9.1), e `card_id` vem da lista de
   cartões do próprio cliente autenticado, nunca de um id proposto;
2. **`CONFIRMED` do modelo não confirma nada sozinho** — só produz efeito se
   houver `pending_confirmation`, e ambiguidade jamais dispara pagamento (§11);
3. **nada aqui inventa produto, preço ou valor de recarga** — A-05 e A-06
   seguem abertas, e a recusa é honesta e nomeada.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from urbanopay.modules.agent.domain.catalog import ToolCaller, ToolName
from urbanopay.modules.agent.domain.conversation import ConversationPhase
from urbanopay.modules.agent.domain.results import NextAction, ResultType, ToolResult
from urbanopay.modules.cards.domain.enums import CardStatus
from urbanopay.modules.orders.domain.enums import OrderStatus
from urbanopay.providers.llm import AgentIntent, ConfirmationDecision

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from urbanopay.modules.agent.application.executor import ToolExecutor
    from urbanopay.modules.agent.domain.conversation import ConversationState
    from urbanopay.providers.llm import TurnUnderstanding

# Intents que só fazem sentido sobre uma conta identificada (SPEC-002 §9).
_REQUIRES_AUTHENTICATION = frozenset(
    {
        AgentIntent.RECHARGE_CARD,
        AgentIntent.CHECK_BALANCE,
        AgentIntent.CHECK_ORDER,
        AgentIntent.CHECK_PAYMENT,
        AgentIntent.CHECK_TICKET,
    }
)

_STOP = NextAction.STOP
_ASK_AMOUNT = NextAction.ASK_AMOUNT
_CONFIRMATION_ECHO = ResultType.ORDER


class TurnPlaybook:
    """Sequências determinísticas de tools, por intenção.

    Acumula o estado e os resultados do turno. Uma instância atende a um turno
    e é descartada — não há estado compartilhado entre conversas.
    """

    def __init__(self, executor: ToolExecutor, state: ConversationState) -> None:
        self._executor = executor
        self._state = state
        self._results: list[ToolResult] = []

    @property
    def state(self) -> ConversationState:
        return self._state

    @property
    def results(self) -> tuple[ToolResult, ...]:
        return tuple(self._results)

    async def _call(
        self, tool: ToolName, arguments: Mapping[str, object] | None = None
    ) -> ToolResult:
        """Invoca uma tool como orquestração e acumula o resultado.

        `ORCHESTRATOR` alcança `LLM_VISIBLE`, `GRAPH_ONLY` e `SENSITIVE_INPUT`,
        mas **nunca** `BACKEND_ONLY` — que sequer é registrado.
        """
        outcome = await self._executor.execute(
            state=self._state,
            tool_name=tool.value,
            arguments=arguments,
            caller=ToolCaller.ORCHESTRATOR,
        )
        self._state = outcome.state
        self._results.append(outcome.result)
        return outcome.result

    def _phase(self, phase: ConversationPhase) -> None:
        self._state = self._state.with_phase(phase)

    # --- ponto de entrada -------------------------------------------------

    async def run(self, understanding: TurnUnderstanding) -> None:
        """Executa o turno.

        A confirmação é avaliada **antes** do intent: quando existe Order
        aguardando resposta, "sim" é resposta àquilo, e não o começo de outra
        jornada.
        """
        if self._state.pending_confirmation is not None and understanding.confirmation is not None:
            await self._resolve_confirmation(understanding.confirmation)
            return

        intent = understanding.intent
        if intent in _REQUIRES_AUTHENTICATION and not await self._ensure_authenticated():
            return

        await self._dispatch(intent, understanding)

    async def _dispatch(self, intent: AgentIntent, understanding: TurnUnderstanding) -> None:
        if intent is AgentIntent.CALCULATE_TRIP_COST:
            await self._calculate_fare(understanding)
        elif intent is AgentIntent.RECHARGE_CARD:
            await self._recharge(understanding)
        elif intent is AgentIntent.CHECK_BALANCE:
            await self._check_balance(understanding)
        elif intent in (AgentIntent.CHECK_ORDER, AgentIntent.CHECK_TICKET):
            await self._check_order()
        elif intent is AgentIntent.CHECK_PAYMENT:
            await self._check_payment()
        elif intent in (AgentIntent.BUY_TICKET, AgentIntent.DISCOVER_PRODUCT):
            await self._unavailable_catalog(intent)
        elif intent is AgentIntent.CALCULATE_RECHARGE_NEED:
            await self._unavailable_usage_cost()
        # `GENERAL_TRANSPORT_HELP` e `DISCOVER_PRODUCT` sem catálogo não movem a
        # fase: uma frase solta no meio da jornada não pode fazer a conversa
        # esquecer onde estava, e reperguntar o que já foi respondido é
        # exatamente o que §6 proíbe.

    # --- autenticação ------------------------------------------------------

    async def _ensure_authenticated(self) -> bool:
        """Portão de autenticação, decidido por código (SPEC-004 §7.2).

        Quem decide parar a jornada para autenticar é a orquestração, não o
        modelo: `get_authentication_status` é `GRAPH_ONLY` exatamente por
        isso. Ao parar, a fase vira `AWAITING_DOCUMENT`, que é o que faz a
        próxima mensagem ser interceptada antes do provider (§13.1).
        """
        result = await self._call(ToolName.GET_AUTHENTICATION_STATUS)
        if result.ok and result.data.get("authenticated") is True:
            return True
        self._phase(ConversationPhase.AWAITING_DOCUMENT)
        return False

    # --- tarifa ------------------------------------------------------------

    async def _calculate_fare(self, understanding: TurnUnderstanding) -> None:
        """Simulação tarifária, pública (PRD RF-05).

        Sem segmentos não há o que calcular, e inventar um trajeto seria
        inventar um preço. A conversa apenas pergunta.
        """
        if not understanding.segments:
            self._phase(ConversationPhase.CALCULATION)
            return

        await self._call(
            ToolName.CALCULATE_TRIP_FARE,
            {
                "segments": [segment.model_dump() for segment in understanding.segments],
                # O perfil declarado só vale para simulação; havendo cartão
                # selecionado em sessão autenticada, o oficial prevalece
                # (SPEC-002 §8) — e quem resolve isso é o serviço, não aqui.
                "declared_fare_profile": understanding.declared_fare_profile or "INTEGRAL",
            },
        )

    # --- recarga -----------------------------------------------------------

    async def _recharge(self, understanding: TurnUnderstanding) -> None:
        """Jornada de recarga até a apresentação do pedido (SPEC-003 §1.1).

        Para em cada informação que falta, em vez de adivinhar. O valor é
        **sempre** do cliente: enquanto A-06 estiver aberta, o agente não
        recomenda quanto recarregar.
        """
        if not await self._ensure_card_selected(understanding):
            return

        if understanding.recharge_amount is None:
            self._phase(ConversationPhase.QUOTE)
            return

        card_id = self._state.selected_card_id
        if card_id is None:  # pragma: no cover - garantido por _ensure_card_selected
            self._phase(ConversationPhase.CARD_SELECTION)
            return

        quote = await self._call(
            ToolName.CREATE_RECHARGE_QUOTE,
            {
                "card_id": str(card_id),
                "amount": understanding.recharge_amount,
                "declared_fare_profile": understanding.declared_fare_profile,
            },
        )
        if not quote.ok:
            return

        # `create_order` deriva a Quote do contexto; nenhum identificador é
        # proposto pelo modelo. O resultado abre a confirmação pendente, que
        # passa a ser a única Order confirmável desta conversa.
        await self._call(ToolName.CREATE_ORDER)

    async def _ensure_card_selected(self, understanding: TurnUnderstanding) -> bool:
        """Resolve o cartão a partir da lista do próprio cliente.

        O modelo pode oferecer um `card_hint` — os quatro últimos dígitos que
        o cliente citou. Ele **não** escolhe o `card_id`: o identificador vem
        da listagem autenticada, e um palpite que não casa com nada apenas faz
        a conversa perguntar de novo.
        """
        if self._state.selected_card_id is not None:
            return True

        listing = await self._call(ToolName.GET_CUSTOMER_CARDS)
        if not listing.ok:
            return False

        cards = listing.data.get("cards")
        if not isinstance(cards, list) or not cards:
            self._phase(ConversationPhase.CARD_SELECTION)
            return False

        usable = [
            entry
            for entry in cards
            if isinstance(entry, dict) and entry.get("status") == CardStatus.ACTIVE.value
        ]
        chosen = _match_card(usable, understanding.card_hint)
        if chosen is None:
            self._phase(ConversationPhase.CARD_SELECTION)
            return False

        # `get_card_details` é quem seleciona: a transição de estado só ocorre
        # sobre um cartão relido e utilizável (`state_transitions`).
        details = await self._call(ToolName.GET_CARD_DETAILS, {"card_id": chosen})
        if not details.ok or self._state.selected_card_id is None:
            self._phase(ConversationPhase.CARD_SELECTION)
            return False
        return True

    # --- confirmação e pagamento ------------------------------------------

    async def _resolve_confirmation(self, decision: ConfirmationDecision) -> None:
        """Consome a resposta a uma confirmação pendente (SPEC-004 §11).

        `AMBIGUOUS` e `REJECTED` **não** chamam serviço algum: nenhum efeito
        financeiro nasce de dúvida. O Order permanece em `DRAFT` e expira
        sozinho pelo TTL (A-10) — a conversa não o cancela, porque cancelar
        também é decisão que ninguém tomou.
        """
        if decision is not ConfirmationDecision.CONFIRMED:
            self._phase(ConversationPhase.ORDER_CONFIRMATION)
            self._results.append(
                ToolResult.success(
                    _CONFIRMATION_ECHO,
                    {"decision": decision.value},
                    next_action=None,
                )
            )
            return

        confirmed = await self._call(ToolName.CONFIRM_ORDER)
        if not confirmed.ok:
            return

        # Aprovação humana encerra a automação financeira do turno: nada nesta
        # camada aprova, e o único caminho adiante é a decisão humana (A-07).
        if confirmed.data.get("status") == OrderStatus.REQUIRES_APPROVAL.value:
            return

        await self._call(ToolName.CREATE_PAYMENT)

    # --- consultas ---------------------------------------------------------

    async def _check_balance(self, understanding: TurnUnderstanding) -> None:
        if not await self._ensure_card_selected(understanding):
            return
        card_id = self._state.selected_card_id
        if card_id is not None:
            await self._call(ToolName.GET_CARD_BALANCE, {"card_id": str(card_id)})

    async def _check_order(self) -> None:
        """Situação do pedido em curso, incluindo entrega e comprovante.

        O comprovante só existe depois de `COMPLETED` (SPEC-005 §13): pedi-lo
        antes devolve `RECEIPT_NOT_AVAILABLE`, que é resposta honesta — um
        documento provisório seria prova de algo que não aconteceu.
        """
        order_id = self._state.current_order_id
        if order_id is None:
            self._phase(ConversationPhase.DISCOVERY)
            return

        order = await self._call(ToolName.GET_ORDER, {"order_id": str(order_id)})
        if not order.ok:
            return

        status = order.data.get("status")
        if status == OrderStatus.REQUIRES_APPROVAL.value:
            await self._call(ToolName.GET_APPROVAL_STATUS, {"order_id": str(order_id)})
            return
        if status in _POST_PAYMENT_STATUSES:
            await self._call(ToolName.GET_FULFILLMENT_STATUS, {"order_id": str(order_id)})
        if status == OrderStatus.COMPLETED.value:
            await self._call(ToolName.GET_RECEIPT, {"order_id": str(order_id)})

    async def _check_payment(self) -> None:
        """Responde a "eu já paguei" com o que o backend sabe.

        Leitura pura: não consulta o provider e não escreve nada. A afirmação
        do cliente não é evidência financeira e não altera estado algum.
        """
        order_id = self._state.current_order_id
        if order_id is None:
            self._phase(ConversationPhase.DISCOVERY)
            return
        payment = await self._call(ToolName.GET_PAYMENT_STATUS, {"order_id": str(order_id)})
        if payment.ok and payment.data.get("status") == "APPROVED":
            await self._call(ToolName.GET_FULFILLMENT_STATUS, {"order_id": str(order_id)})

    # --- indisponibilidades honestas --------------------------------------

    async def _unavailable_catalog(self, intent: AgentIntent) -> None:
        """A-05: `catalog` não tem SPEC, e nenhum produto é inventado.

        A tool declarada resolve para `TOOL_UNAVAILABLE` nomeando o bloqueio.
        Chamá-la de verdade — em vez de responder de memória — é o que mantém
        a recusa verificável.
        """
        del intent
        await self._executor.execute(
            state=self._state,
            tool_name="search_products",
            arguments={},
            caller=ToolCaller.ORCHESTRATOR,
        )
        self._results.append(
            ToolResult.failure(
                "TOOL_UNAVAILABLE",
                next_action=_STOP,
                data={"blocker": "A-05", "available": "RECARGA_LIVRE"},
            )
        )

    async def _unavailable_usage_cost(self) -> None:
        """A-06: projeção de uso sem contrato. O cliente informa o valor."""
        self._results.append(
            ToolResult.failure(
                "TOOL_UNAVAILABLE",
                next_action=_ASK_AMOUNT,
                data={"blocker": "A-06"},
            )
        )
        self._phase(ConversationPhase.QUOTE)


def _match_card(cards: Sequence[object], hint: str | None) -> str | None:
    """Escolhe o cartão pelo palpite, ou o único disponível.

    Palpite ambíguo não escolhe nada: com dois cartões terminados nos mesmos
    dígitos, perguntar é a única resposta correta.
    """
    entries = [entry for entry in cards if isinstance(entry, dict)]
    if hint:
        matches = [
            entry
            for entry in entries
            if isinstance(entry.get("masked_number"), str)
            and str(entry["masked_number"]).endswith(hint)
        ]
        if len(matches) == 1:
            identifier = matches[0].get("card_id")
            return identifier if isinstance(identifier, str) else None
        return None
    if len(entries) == 1:
        identifier = entries[0].get("card_id")
        return identifier if isinstance(identifier, str) else None
    return None


_POST_PAYMENT_STATUSES = frozenset(
    {
        OrderStatus.PAID.value,
        OrderStatus.FULFILLING.value,
        OrderStatus.COMPLETED.value,
        OrderStatus.FULFILLMENT_FAILED.value,
    }
)
