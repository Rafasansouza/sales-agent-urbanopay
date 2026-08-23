# scripts

Utilitários de desenvolvimento do repositório.

## Arquivos

| Arquivo | Descrição |
|---|---|
| `dev.ps1` | Equivalente PowerShell dos alvos do `Makefile`, para uso em Windows. |

## Relação com o Makefile

O `Makefile` da raiz é a **definição canônica** dos comandos e é o que a CI
executa. O `dev.ps1` existe apenas porque `make` normalmente não está
disponível em Windows.

Sempre que um alvo for adicionado ou alterado no `Makefile`, o `dev.ps1` deve
ser atualizado na mesma mudança. Divergência entre os dois é considerada
defeito.

## Uso

```powershell
.\scripts\dev.ps1 help
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 up
.\scripts\dev.ps1 verify
```

## Restrições

- Nenhum script deste diretório pode conter credenciais.
- Nenhum script pode executar operação destrutiva sem confirmação explícita
  do desenvolvedor. Operações bloqueadas pelo harness estão listadas em
  `.claude/rules/git-workflow.md` e em `docs/agent-harness/AGENT-HARNESS.md` §9.
