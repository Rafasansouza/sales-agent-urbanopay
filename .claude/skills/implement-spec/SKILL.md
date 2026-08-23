---
name: implement-spec
description: Implementa uma mudança conforme uma SPEC aprovada — lê SPEC e ADRs, inspeciona a implementação atual, aplica a mudança mínima, cria ou atualiza testes e verifica. Use depois de prepare-task, quando o plano estiver aprovado.
---

# implement-spec

Etapa de implementação do fluxo de AGENT-HARNESS §13. Pressupõe um plano já
produzido por `prepare-task`.

## Pré-condições

Não comece sem que todas sejam verdadeiras:

1. A branch atual **não** é `main`.
2. Existe SPEC aceita cobrindo o comportamento a implementar.
3. Os ADRs necessários estão com status **Aceito** — não `Proposta`.
4. Nenhuma pendência de `docs/OPEN-QUESTIONS.md` bloqueia a tarefa.
5. O plano está aprovado.

Se qualquer uma falhar: **reporte e pare**.

## Regra que não se negocia

> O LLM interpreta, recomenda e explica.
> O código valida, calcula, autoriza, transiciona estado, executa e persiste.

Nunca mova regra de negócio determinística para prompt. Nunca invente regra
para preencher lacuna documental. Se a SPEC não diz, a resposta é reportar, não
decidir.

## Procedimento

### 1. Reler a SPEC no ponto exato

Releia a seção específica que está sendo implementada, incluindo os erros
tipados, as invariantes e os critérios de aceite. Não trabalhe de memória.

### 2. Implementar a mudança mínima

- Menor mudança que satisfaz a SPEC. Sem refatoração oportunista.
- Respeite a estratificação: `domain` → `application` → `infrastructure`.
- Erros tipados exatamente com os códigos da SPEC.
- `Decimal` para dinheiro, sempre. Nenhum `float` no caminho.
- Nenhum valor de tarifa, threshold ou TTL hard-coded que deveria vir de dados
  ou de configuração.
- Idempotência em toda operação crítica.
- Autorização validada no domínio, não só na API.
- Masking aplicado antes de qualquer saída.

### 3. Escrever os testes na mesma mudança

- Unit para regra de domínio.
- Integration para fronteira de banco e de provider.
- E2E para jornada completa.
- Eval para comportamento probabilístico.
- Marcador obrigatório em todo teste.
- Se for correção de bug: escreva primeiro o teste que falha.

Cubra os testes obrigatórios da SPEC afetada, não apenas o caminho felizoso.

### 4. Verificar constraints e migrations

Mudança de schema exige migration versionada. Invariante crítica ganha
constraint de banco quando praticável. Migration destrutiva exige revisão
humana explícita — nunca a execute por conta própria.

### 5. Verificar

```powershell
.\scripts\dev.ps1 verify
```

Ou, em ambiente com `make`:

```bash
make verify
```

### 6. Inspecionar o próprio diff

```bash
git diff
```

Procure: valor literal que deveria ser dado; `float` em caminho de dinheiro;
`print` ou log com PII; tool com capability ampla; teste enfraquecido; arquivo
alterado sem relação com a tarefa.

## Ao terminar

Reporte:

- o que foi implementado e qual seção da SPEC atende;
- os testes criados e sua camada;
- as invariantes protegidas e como;
- migrations criadas;
- riscos remanescentes e o que ficou fora de escopo.

Não faça commit nem push sem solicitação explícita.

Em seguida, execute `review-change`.
