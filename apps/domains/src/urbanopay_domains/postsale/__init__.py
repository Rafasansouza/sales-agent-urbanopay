"""Post-sale — consultas e comprovante.

Fronteira de domínio declarada em ADR-001.

Consultas autenticadas de pós-venda e comprovante simulado.

Documentos obrigatórios: SPEC-005; ADR-005.

Estado: **sem módulo próprio, por decisão.** As consultas da SPEC-005 §14 já
têm casa — saldo em `cards`, pedido em `orders`, pagamento em `payments`,
status de entrega e comprovante em `fulfillment`. Um módulo aqui seria fachada
sem lógica própria, e a composição natural dessas leituras é a camada de tools
da SPEC-004, que ainda não existe. Ver o README deste diretório.
"""
