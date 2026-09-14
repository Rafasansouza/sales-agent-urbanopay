"""Tickets — bilhetes simulados.

Fronteira de domínio declarada em ADR-001.

Emissão idempotente de bilhete fictício com token opaco.

Documentos obrigatórios: SPEC-005; ADR-005.

Estado: **não implementado — BLOQUEADO por A-05.** `Ticket` exige
`product_id` (catálogo sem SPEC) e `valid_from`/`valid_until`, que o PRD §19
mantém pendentes. Nenhuma tabela `tickets` existe, e `TICKET_ISSUANCE` é
recusado com `UNSUPPORTED_FULFILLMENT_TYPE` — nunca tratado com comportamento
fictício. Ver o README deste diretório antes de escrever qualquer código aqui.
"""
