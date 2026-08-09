param([int]$ReadyTimeoutSeconds = 90)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $RepoRoot
try {
    docker compose --profile ui-dev up -d ui-dev
    if ($LASTEXITCODE -ne 0) { throw "Unable to start the UI development container." }
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    do {
        Start-Sleep -Seconds 2
        try { $status = (Invoke-WebRequest -UseBasicParsing "http://localhost:8502/" -TimeoutSec 3).StatusCode }
        catch { $status = 0 }
    } while ($status -ne 200 -and (Get-Date) -lt $deadline)
    if ($status -ne 200) {
        docker compose logs --tail 80 ui-dev
        throw "UI development server did not become ready."
    }
    Write-Host "KaiMS UI development server: http://localhost:8502" -ForegroundColor Green
    Write-Host "Source edits now use Vite hot reload; no image rebuild is required." -ForegroundColor Cyan
}
finally { Pop-Location }
