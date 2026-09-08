"""Política determinística de idempotency keys (SPEC-004 §9.1, SPEC-003 §11).

O modelo **nunca** escolhe uma key: ela não é argumento de nenhuma tool. A key
é uma função pura de identificadores já persistidos, e é essa propriedade que
entrega as duas garantias que a SPEC-003 exige:

- **mesma intenção comercial + retry técnico ⇒ mesma key**, porque a entrada da
  função não muda entre as tentativas;
- **nova tentativa comercial legítima ⇒ nova key**, porque a entrada só muda
  quando existe evidência persistida de que a tentativa anterior terminou.

Nada aqui usa relógio, contador em memória, `uuid4()` ou estado conversacional.
Contar linhas para reconstruir a máquina financeira seria pior ainda: a
orquestração passaria a manter uma segunda versão de um invariante que o banco
já protege.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from uuid import UUID

_INITIAL_ATTEMPT: Final = "initial"


class IdempotencyKeyPolicy:
    """Deriva as keys dos comandos idempotentes da jornada.

    Sem estado e sem dependências — é um agrupamento nomeado de funções puras,
    para que a política tenha um lugar único onde ser lida e testada.
    """

    @staticmethod
    def create_order(quote_id: UUID) -> str:
        """`create_order` é idempotente **pela Quote**.

        Uma Quote produz no máximo um Order (SPEC-003 §4, protegido por
        `QUOTE_ALREADY_CONSUMED`), então a própria Quote é a identidade
        natural da intenção comercial. Um retry técnico reapresenta a mesma
        Quote e reencontra a mesma key.
        """
        return f"create_order:{quote_id}"

    @staticmethod
    def confirm_order(order_id: UUID) -> str:
        """`confirm_order` é idempotente **pelo Order**.

        Um Order é confirmado uma única vez (§8, §14): não existe segunda
        confirmação comercial a distinguir, então o Order basta. É isto que
        torna um "sim" repetido inofensivo.
        """
        return f"confirm_order:{order_id}"

    @staticmethod
    def create_payment(order_id: UUID, *, previous_terminal_payment_id: UUID | None) -> str:
        """Identidade da tentativa de cobrança (SPEC-003 §13).

        `previous_terminal_payment_id` é **evidência persistida**, obtida do
        estado do Order: a tentativa anterior que já terminou sem aprovação.

        - `None` ⇒ primeira tentativa comercial;
        - preenchido ⇒ nova tentativa comercial, autorizada por §13.2, cuja
          identidade deriva do desfecho anterior.

        Duas chamadas concorrentes após o mesmo terminal observam o mesmo
        `previous_terminal_payment_id` e produzem a **mesma** key — que é
        exatamente o que faz a segunda ser um replay em vez de uma segunda
        cobrança.

        O caso de tentativa **ativa** não chega aqui: ele não é uma nova
        tentativa, e a tool o resolve antes, devolvendo o Payment existente ou
        `PAYMENT_STATUS_UNKNOWN` (§9.1).
        """
        if previous_terminal_payment_id is None:
            return f"create_payment:{order_id}:{_INITIAL_ATTEMPT}"
        return f"create_payment:{order_id}:after:{previous_terminal_payment_id}"
