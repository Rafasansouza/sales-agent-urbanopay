"""Fulfillment — recarga, ledger e reconciliação.

Fronteira de domínio declarada em ADR-001.

Executa a entrega após pagamento aprovado: crédito de recarga, ledger
imutável, idempotência por chave natural, comprovante simulado e detecção de
inconsistência.

**Não existe retentativa automática** neste escopo: o efeito é uma transação
local que acontece por inteiro ou não acontece, e não há resultado externo a
interpretar. A reentrada a partir de `FAILED` ou `RECONCILIATION_REQUIRED`
acontece somente por comando explícito de backend.

Documentos obrigatórios: SPEC-005; ADR-005, ADR-007, ADR-012.

Estado: implementado no escopo `RECHARGE`. `TICKET_ISSUANCE` está bloqueado
por A-05. Ver o README deste diretório antes de escrever qualquer código aqui.
"""
