param(
    [switch]$NoUi
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Error "Virtual environment not found at $Python. Create it with: python -m venv .venv"
}

$ServicePaths = @(
    "services\common",
    "services\api-gateway",
    "services\alert-intelligence",
    "services\context-agent",
    "services\model-router",
    "services\resolution-agent",
    "services\orchestrator",
    "services\approval-service",
    "services\remediation-engine",
    "services\closure-service",
    "services\monitoring-adapter"
) | ForEach-Object { Join-Path $RepoRoot $_ }

$PythonPath = $ServicePaths -join ";"

function Start-KaiOpsWindow {
    param(
        [string]$Title,
        [string]$Command
    )

    $EscapedRepoRoot = $RepoRoot.Replace("'", "''")
    $EscapedPythonPath = $PythonPath.Replace("'", "''")
    $EscapedTitle = $Title.Replace("'", "''")
    $Bootstrap = @"
Set-Location -LiteralPath '$EscapedRepoRoot'
`$env:PYTHONPATH = '$EscapedPythonPath'
`$env:KAFKA_ENABLED = 'false'
`$env:DATABASE_ENABLED = 'false'
`$Host.UI.RawUI.WindowTitle = '$EscapedTitle'
$Command
"@
    $Encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Bootstrap))

    Start-Process powershell -ArgumentList @("-NoExit", "-EncodedCommand", $Encoded)
}

Start-KaiOpsWindow `
    -Title "KaiOps monitoring-adapter :8001" `
    -Command "& '$Python' -m uvicorn app:app --host 127.0.0.1 --port 8001 --app-dir services/monitoring-adapter"

Start-KaiOpsWindow `
    -Title "KaiOps approval-service :8007" `
    -Command "& '$Python' -m uvicorn app:app --host 127.0.0.1 --port 8007 --app-dir services/approval-service"

Start-KaiOpsWindow `
    -Title "KaiOps api-gateway :8010" `
    -Command "`$env:MONITORING_ADAPTER_URL = 'http://localhost:8001'; `$env:APPROVAL_SERVICE_URL = 'http://localhost:8007'; & '$Python' -m uvicorn app:app --host 127.0.0.1 --port 8010 --app-dir services/api-gateway"

if (-not $NoUi) {
    $UiCommand = @"
`$env:MONITORING_ADAPTER_URL="http://localhost:8001"
`$env:APPROVAL_SERVICE_URL="http://localhost:8007"
`$env:API_GATEWAY_URL="http://localhost:8010"
& '$Python' -m streamlit run services/ui/app.py
"@

    Start-KaiOpsWindow -Title "KaiOps Streamlit UI :8501" -Command $UiCommand
}

Write-Host "Started KaiOps local services."
Write-Host "Monitoring adapter: http://localhost:8001"
Write-Host "Approval service:   http://localhost:8007"
Write-Host "API Gateway:        http://localhost:8010"
if (-not $NoUi) {
    Write-Host "Streamlit UI:       http://localhost:8501"
}
