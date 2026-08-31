$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

$Checks = @(
    @{
        Path = "backend\src\api-gateway\app.py"
        Pattern = "/security/check"
        Description = "API Gateway safety endpoint"
    },
    @{
        Path = "backend\src\api-gateway\app.py"
        Pattern = "/sample/flows"
        Description = "API Gateway sample flow catalog endpoint"
    },
    @{
        Path = "backend\src\api-gateway\app.py"
        Pattern = "/rag/documents"
        Description = "API Gateway RAG ingestion endpoint"
    },
    @{
        Path = "backend\src\monitoring-adapter\app.py"
        Pattern = "payment-latency/workflow"
        Description = "local no-Kafka workflow endpoint"
    },
    @{
        Path = "docker-compose.yml"
        Pattern = "healthcheck"
        Description = "Docker Compose service health checks"
    }
)

$Failed = $false

foreach ($Check in $Checks) {
    $File = Join-Path $RepoRoot $Check.Path
    if (-not (Test-Path $File)) {
        Write-Host "FAIL missing $($Check.Path)" -ForegroundColor Red
        $Failed = $true
        continue
    }

    $Match = Select-String -Path $File -Pattern $Check.Pattern -SimpleMatch -Quiet
    if ($Match) {
        Write-Host "OK   $($Check.Description)" -ForegroundColor Green
    }
    else {
        Write-Host "FAIL $($Check.Description) not found in $($Check.Path)" -ForegroundColor Red
        $Failed = $true
    }
}

if ($Failed) {
    Write-Host ""
    Write-Host "Your local checkout is not updated. Pull the latest branch or replace your local files from the latest branch ZIP." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Local files look updated. Use the targeted cached rebuild:" -ForegroundColor Cyan
Write-Host ".\scripts\rebuild-ui.ps1"
Write-Host "For backend changes, rebuild only the affected service:" -ForegroundColor Cyan
Write-Host "docker compose build <service>"
Write-Host "docker compose up -d --no-deps <service>"
Write-Host "Avoid 'down -v' and '--no-cache' unless you intentionally need destructive data reset or cache diagnostics." -ForegroundColor Yellow
