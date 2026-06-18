$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

$Checks = @(
    @{
        Path = "services\ui\app.py"
        Pattern = "Run Flow"
        Description = "modern Streamlit scenario runner"
    },
    @{
        Path = "services\ui\app.py"
        Pattern = "Closed Incidents"
        Description = "Streamlit closed incidents tab"
    },
    @{
        Path = "services\ui\app.py"
        Pattern = "Human approval"
        Description = "Streamlit approval screen"
    },
    @{
        Path = "services\api-gateway\app.py"
        Pattern = "/security/check"
        Description = "API Gateway safety endpoint"
    },
    @{
        Path = "services\api-gateway\app.py"
        Pattern = "/sample/flows"
        Description = "API Gateway sample flow catalog endpoint"
    },
    @{
        Path = "services\monitoring-adapter\app.py"
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

$OldUi = Select-String `
    -Path (Join-Path $RepoRoot "services\ui\app.py") `
    -Pattern "Inject payment latency alert" `
    -SimpleMatch `
    -Quiet

if ($OldUi) {
    Write-Host "FAIL old Streamlit button text is still present" -ForegroundColor Red
    $Failed = $true
}
else {
    Write-Host "OK   old Streamlit button text absent" -ForegroundColor Green
}

if ($Failed) {
    Write-Host ""
    Write-Host "Your local checkout is not updated. Pull branch cursor/agentic-incident-platform-f631 or replace your local files from the latest branch ZIP." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Local files look updated. Rebuild Docker with:" -ForegroundColor Cyan
Write-Host "docker compose down -v --remove-orphans"
Write-Host "docker compose build --no-cache"
Write-Host "docker compose up"
