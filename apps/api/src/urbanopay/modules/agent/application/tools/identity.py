"""Tools de identidade (SPEC-002 §3, §4; SPEC-004 §7, §13.1).

`start_authentication` e `verify_otp` são `SENSITIVE_INPUT`: recebem CPF e OTP,
e por isso **não** são oferecidas ao modelo. A entrada chega por handler
determinístico, e o valor nunca é ecoado no envelope, no estado ou no log.

Os desfechos de identificação e verificação são **resultados tipados**, não
exceções (SPEC-002 §3): "CPF não encontrado" é uma resposta do domínio, não uma
falha do sistema. O envelope marca `ok=false` porque o efeito pretendido não
aconteceu, e `next_action` diz o que a jornada faz a seguir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from urbanopay.modules.agent.application import presenters
from urbanopay.modules.agent.domain.results import NextAction, ResultType, ToolResult
from urbanopay.modules.identity.domain.results import IdentificationStatus, VerificationStatus

if TYPE_CHECKING:
    from collections.abc import Mapping

    from urbanopay.modules.agent.application.schemas import (
        NoInput,
        StartAuthenticationInput,
        VerifyOtpInput,
    )
    from urbanopay.modules.agent.application.tools import ToolContext

_IDENTIFICATION_NEXT: Final[Mapping[IdentificationStatus, NextAction]] = {
    IdentificationStatus.CUSTOMER_FOUND: NextAction.AUTHENTICATE,
    IdentificationStatus.CUSTOMER_NOT_FOUND: NextAction.RETRY_DOCUMENT,
    IdentificationStatus.INVALID_DOCUMENT: NextAction.RETRY_DOCUMENT,
    # Conta bloqueada não é problema que a conversa resolva.
    IdentificationStatus.CUSTOMER_BLOCKED: NextAction.STOP,
}

_VERIFICATION_NEXT: Final[Mapping[VerificationStatus, NextAction]] = {
    VerificationStatus.AUTHENTICATED: NextAction.CONTINUE,
    VerificationStatus.OTP_INVALID: NextAction.RETRY_OTP,
    # Expirado e bloqueado exigem novo desafio, não nova tentativa.
    VerificationStatus.OTP_EXPIRED: NextAction.RESTART_AUTH,
    VerificationStatus.CHALLENGE_BLOCKED: NextAction.RESTART_AUTH,
}


async def start_authentication(ctx: ToolContext, payload: StartAuthenticationInput) -> ToolResult:
    """Identifica o cliente e cria o desafio de OTP (SPEC-002 §3, §4).

    O documento é usado e descartado: não vai para o envelope, para o estado
    nem para o log. `CUSTOMER_NOT_FOUND` cobre também cliente `INACTIVE`, de
    propósito — a resposta não revela o estado de uma conta alheia.
    """
    result = await ctx.services.authentication.start_authentication(
        ctx.state.session_id, payload.document
    )
    return ToolResult(
        ok=result.status is IdentificationStatus.CUSTOMER_FOUND,
        result_type=ResultType.AUTHENTICATION_CHALLENGE,
        code=result.status.value,
        data=presenters.start_authentication(result),
        next_action=_IDENTIFICATION_NEXT[result.status],
    )


async def verify_otp(ctx: ToolContext, payload: VerifyOtpInput) -> ToolResult:
    """Consome o desafio pendente da sessão (SPEC-002 §4).

    Uso único e atômico: duas verificações simultâneas nunca autenticam com o
    mesmo desafio. O valor do OTP não sobrevive a esta chamada em lugar algum.
    """
    result = await ctx.services.authentication.verify_otp(ctx.state.session_id, payload.otp)
    return ToolResult(
        ok=result.status is VerificationStatus.AUTHENTICATED,
        result_type=ResultType.AUTHENTICATION_VERIFICATION,
        code=result.status.value,
        data=presenters.verification(result),
        next_action=_VERIFICATION_NEXT[result.status],
    )


async def get_authentication_status(ctx: ToolContext, payload: NoInput) -> ToolResult:
    """Estado da sessão, sem renovar a janela de inatividade.

    Consulta não é atividade: renovar aqui faria uma verificação de rotina
    manter viva uma sessão abandonada.
    """
    del payload
    status = await ctx.services.sessions.get_authentication_status(ctx.state.session_id)
    return ToolResult.success(
        ResultType.AUTHENTICATION_STATUS,
        presenters.authentication_status(status),
        next_action=NextAction.CONTINUE if status.authenticated else NextAction.AUTHENTICATE,
    )
