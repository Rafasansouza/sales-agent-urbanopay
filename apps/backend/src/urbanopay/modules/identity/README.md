# Identity — clientes, sessões e autenticação simulada

**Fronteira de domínio:** ADR-001
**Documentos obrigatórios:** SPEC-002
**ADRs aplicáveis:** ADR-004, ADR-005, ADR-012
**Estado:** **implementado** (SPEC-002)

## Responsabilidade

Cadeia determinística: sessão anônima → identificação por CPF → OTP simulado →
sessão autenticada → `customer_id`. O LLM nunca decide autenticação; o portão
das operações protegidas é `SessionService.require_authenticated`.

## Decisões vigentes (aprovadas no plano da SPEC-002)

- **CPF nunca armazenado**: lookup por `HMAC-SHA256(secret, "cpf:"+normalizado)`
  (`IDENTITY_HASH_SECRET`; rotação exige migração dos identificadores).
- Validação de documento = formato apenas (11 dígitos) — §3 não exige dígitos
  verificadores. `email`/`phone` omitidos (conceituais, sem consumidor, §12).
- **OTP**: gerado por `secrets` (porta `OtpGenerator`; fake determinístico nos
  testes; **sem OTP fixo por configuração**); armazenado como
  `HMAC(secret, "otp:"+challenge_id+":"+otp)`; verificação em tempo constante;
  uso único; supersede ao reiniciar; exposição na demo é H-12 (SPEC-004).
- `OTPChallenge.session_id` vincula o desafio à sessão (anti uso cruzado).
- TTLs configuráveis com defaults da SPEC: sessão 30 min **de inatividade**
  (janela deslizante), OTP 5 min, 5 tentativas.
- Mesmo `session_id` após autenticação (MVP); fixation registrado como
  evolução futura. Re-autenticação por fluxo completo de OTP revincula.
- `INACTIVE` responde como `CUSTOMER_NOT_FOUND` (não revela estado da conta).
- Concorrência: locks `Session → OTPChallenge` (ordem global); índice único
  parcial (1 PENDING/sessão) como última defesa, não como state machine.

## Resultados × erros

Resultados tipados (§3): `CUSTOMER_FOUND/NOT_FOUND`, `INVALID_DOCUMENT`,
`CUSTOMER_BLOCKED`; verificação: `AUTHENTICATED`, `OTP_INVALID(+restantes)`,
`OTP_EXPIRED`, `CHALLENGE_BLOCKED`. Erros puros (sem HTTP/PII):
`SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `NOT_AUTHENTICATED`,
`AUTHENTICATION_CHALLENGE_NOT_FOUND`.

## Tools que este módulo suportará (SPEC-004)

`start_authentication`, `verify_otp`, `get_authentication_status`.

## Tools proibidas

`authenticate_as`, `change_customer` — nem sob nome equivalente.

## PII

Nunca em log/trace/erro/repr: OTP, HMACs, segredo, CPF. `cpf_hash` e
`otp_hash` ficam fora do `repr` das entidades. Permitidos: IDs internos
opacos, status, códigos de erro.
