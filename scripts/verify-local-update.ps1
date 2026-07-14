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
Write-Host "Local files look updated. Rebuild Docker with:" -ForegroundColor Cyan
Write-Host "docker compose down -v --remove-orphans"
Write-Host "docker compose build --no-cache"
Write-Host "docker compose up"
