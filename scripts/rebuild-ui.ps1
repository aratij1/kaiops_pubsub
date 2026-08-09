param(
    [switch]$Validate,
    [int]$ReadyTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $RepoRoot
try {
    $env:DOCKER_BUILDKIT = "1"
    $env:COMPOSE_BAKE = "true"

    if ($Validate) {
        docker run --rm `
            -v "${RepoRoot}\frontend\react:/app" `
            -v "kaiops_ui_node_modules:/app/node_modules" `
            -v "kaiops_ui_npm_cache:/root/.npm" `
            -w /app node:20-alpine `
            sh -lc "npm ci --prefer-offline --no-audit --no-fund && npm run typecheck && npm run test:unit && npm run build:budget"
        if ($LASTEXITCODE -ne 0) { throw "Frontend validation failed." }
    }

    docker compose build ui
    if ($LASTEXITCODE -ne 0) { throw "UI image build failed." }
    docker compose up -d --no-deps ui
    if ($LASTEXITCODE -ne 0) { throw "UI container start failed." }

    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    do {
        Start-Sleep -Seconds 2
        try {
            $status = (Invoke-WebRequest -UseBasicParsing "http://localhost:8501/" -TimeoutSec 3).StatusCode
        }
        catch { $status = 0 }
    } while ($status -ne 200 -and (Get-Date) -lt $deadline)

    if ($status -ne 200) { throw "UI did not become ready within $ReadyTimeoutSeconds seconds." }
    Write-Host "KaiMS UI is ready: http://localhost:8501" -ForegroundColor Green
}
finally {
    Pop-Location
}
