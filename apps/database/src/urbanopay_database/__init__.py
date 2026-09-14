"""Foundation de persistência e contratos transversais (ADR-012, ADR-017).

Camada mais baixa da aplicação: ela **não importa nenhuma outra**. Além do
`Base`, do engine, da sessão e do Unit of Work, carrega os contratos que
precisam estar abaixo de todos — o `Protocol` do Unit of Work, o contrato de
idempotência, a política de event loop e `DatabaseSettings`.

Direção de dependência, sem exceção:

```text
database ◀── domains ◀── agent ◀── backend
```
"""
