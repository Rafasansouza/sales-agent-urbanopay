<#
.SYNOPSIS
    Comandos de desenvolvimento da UrbanoPay em Windows.

.DESCRIPTION
    Equivalente PowerShell do Makefile da raiz, que permanece a definicao
    canonica usada pela CI. Este wrapper existe porque `make` normalmente
    nao esta disponivel em Windows.

.PARAMETER Target
    Alvo a executar. Use `help` para listar os alvos disponiveis.

.EXAMPLE
    .\scripts\dev.ps1 setup
    .\scripts\dev.ps1 verify
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Target = 'help',

    # Argumento adicional de alguns alvos (ex.: mensagem de `migration`).
    [Parameter(Position = 1)]
    [string]$Arg = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Todos os comandos rodam a partir da raiz do repositorio.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$ComposeFile = Join-Path $RepoRoot 'infra/docker-compose.yml'

function Invoke-Step {
    <#
        Executa um comando externo e interrompe o script se o codigo de
        saida for diferente de zero. Necessario porque o PowerShell nao
        propaga falha de executavel nativo automaticamente.

        -AllowNoTests tolera SOMENTE o codigo 5 do pytest ("nenhum teste
        coletado"), de forma ruidosa. Qualquer outro codigo continua falhando.
        Ver H-07 em docs/OPEN-QUESTIONS.md.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$CommandArgs,
        [switch]$AllowNoTests
    )

    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Command @CommandArgs
    $code = $LASTEXITCODE

    if ($code -eq 0) { return }

    if ($AllowNoTests -and $code -eq 5) {
        Write-Host "AVISO: nenhum teste coletado nesta camada." -ForegroundColor Yellow
        Write-Host "AVISO: esperado nesta fase do bootstrap. Ver docs/OPEN-QUESTIONS.md (H-07)." -ForegroundColor Yellow
        return
    }

    throw "$Label falhou com codigo $code"
}

function Show-Help {
    Write-Host ''
    Write-Host 'UrbanoPay - comandos de desenvolvimento' -ForegroundColor Green
    Write-Host ''
    $rows = @(
        @{ Name = 'setup';            Text = 'Instala o ambiente Python a partir do uv.lock' }
        @{ Name = 'up';               Text = 'Sobe PostgreSQL, Redis e OTel Collector' }
        @{ Name = 'down';             Text = 'Derruba os containers preservando volumes' }
        @{ Name = 'logs';             Text = 'Acompanha os logs da infraestrutura local' }
        @{ Name = 'ps';               Text = 'Mostra o estado dos containers' }
        @{ Name = 'api';              Text = 'Executa a API em modo desenvolvimento' }
        @{ Name = 'fmt';              Text = 'Formata o codigo' }
        @{ Name = 'fmt-check';        Text = 'Verifica a formatacao sem alterar arquivos' }
        @{ Name = 'lint';             Text = 'Executa o linter' }
        @{ Name = 'typecheck';        Text = 'Executa a verificacao de tipos' }
        @{ Name = 'test';             Text = 'Atalho para a suite rapida (unit)' }
        @{ Name = 'test-unit';        Text = 'Regras de dominio, sem I/O externo' }
        @{ Name = 'test-integration'; Text = 'Fronteiras de banco e provider (requer up)' }
        @{ Name = 'test-e2e';         Text = 'Jornadas completas de compra (requer up)' }
        @{ Name = 'evals';            Text = 'Comportamento probabilistico do agente' }
        @{ Name = 'verify';           Text = 'fmt-check + lint + typecheck + test-unit' }
        @{ Name = 'migrate';          Text = 'Aplica migrations ate head (requer up)' }
        @{ Name = 'migration';        Text = 'Gera migration candidata: migration "descricao"' }
        @{ Name = 'downgrade';        Text = 'Reverte a ultima migration aplicada' }
        @{ Name = 'migration-check';  Text = 'Falha se modelos divergirem das migrations' }
        @{ Name = 'clean';            Text = 'Remove caches de build e de ferramentas' }
    )
    foreach ($row in $rows) {
        Write-Host ('  {0,-18} {1}' -f $row.Name, $row.Text)
    }
    Write-Host ''
}

switch ($Target) {
    'help' { Show-Help }

    'setup' { Invoke-Step 'uv sync' 'uv' @('sync') }

    'up' { Invoke-Step 'compose up' 'docker' @('compose', '-f', $ComposeFile, 'up', '-d') }

    'down' { Invoke-Step 'compose down' 'docker' @('compose', '-f', $ComposeFile, 'down') }

    'logs' { Invoke-Step 'compose logs' 'docker' @('compose', '-f', $ComposeFile, 'logs', '-f') }

    'ps' { Invoke-Step 'compose ps' 'docker' @('compose', '-f', $ComposeFile, 'ps') }

    'api' {
        Invoke-Step 'uvicorn' 'uv' @(
            'run', 'uvicorn', 'urbanopay.main:app',
            '--reload', '--host', '127.0.0.1', '--port', '8000'
        )
    }

    'fmt' { Invoke-Step 'ruff format' 'uv' @('run', 'ruff', 'format', '.') }

    'fmt-check' { Invoke-Step 'ruff format --check' 'uv' @('run', 'ruff', 'format', '--check', '.') }

    'lint' { Invoke-Step 'ruff check' 'uv' @('run', 'ruff', 'check', '.') }

    'typecheck' { Invoke-Step 'mypy' 'uv' @('run', 'mypy') }

    { $_ -in 'test', 'test-unit' } { Invoke-Step 'pytest -m unit' 'uv' @('run', 'pytest', '-m', 'unit') }

    'test-integration' {
        # Sem tolerancia a "nenhum teste coletado": a camada possui testes
        # reais desde a persistence foundation (H-07).
        Invoke-Step 'pytest -m integration' 'uv' @('run', 'pytest', '-m', 'integration')
    }

    'test-e2e' {
        Invoke-Step 'pytest -m e2e' 'uv' @('run', 'pytest', '-m', 'e2e') -AllowNoTests
    }

    'evals' {
        Invoke-Step 'pytest -m eval' 'uv' @('run', 'pytest', '-m', 'eval') -AllowNoTests
    }

    'verify' {
        Invoke-Step 'ruff format --check' 'uv' @('run', 'ruff', 'format', '--check', '.')
        Invoke-Step 'ruff check' 'uv' @('run', 'ruff', 'check', '.')
        Invoke-Step 'mypy' 'uv' @('run', 'mypy')
        Invoke-Step 'pytest -m unit' 'uv' @('run', 'pytest', '-m', 'unit')
        Write-Host 'verify: OK' -ForegroundColor Green
    }

    'migrate' {
        Invoke-Step 'alembic upgrade head' 'uv' @('run', 'alembic', 'upgrade', 'head')
    }

    'migration' {
        if (-not $Arg) {
            Write-Host 'uso: .\scripts\dev.ps1 migration "descricao da mudanca"' -ForegroundColor Red
            exit 1
        }
        Invoke-Step 'alembic revision --autogenerate' 'uv' @(
            'run', 'alembic', 'revision', '--autogenerate', '-m', $Arg
        )
        Write-Host 'ATENCAO: autogenerate produz uma CANDIDATA. Revise antes de aceitar (ADR-012).' -ForegroundColor Yellow
    }

    'downgrade' {
        Invoke-Step 'alembic downgrade -1' 'uv' @('run', 'alembic', 'downgrade', '-1')
    }

    'migration-check' {
        Invoke-Step 'alembic check' 'uv' @('run', 'alembic', 'check')
    }

    'clean' {
        $paths = @('.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', '.coverage')
        foreach ($path in $paths) {
            if (Test-Path $path) { Remove-Item -Recurse -Force $path }
        }
        Get-ChildItem -Path $RepoRoot -Directory -Recurse -Filter '__pycache__' `
            | Where-Object { $_.FullName -notmatch '\\\.venv\\' } `
            | Remove-Item -Recurse -Force
        Write-Host 'clean: OK' -ForegroundColor Green
    }

    default {
        Write-Host "Alvo desconhecido: $Target" -ForegroundColor Red
        Show-Help
        exit 1
    }
}

# Saida explicita: sem isto o processo herdaria o codigo do ultimo executavel
# nativo invocado. O pytest retorna 5 em camada vazia, o que faria um alvo
# bem-sucedido parecer falha para qualquer chamador (outro script ou a CI).
# Os alvos que devem falhar chamam `exit 1` diretamente e nao chegam aqui.
exit 0
