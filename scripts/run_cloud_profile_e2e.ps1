param(
    [Parameter(Mandatory = $false)]
    [ValidateSet('onprem', 'azure', 'aws', 'gcp')]
    [string]$Profile = 'onprem',
    [Parameter(Mandatory = $false)]
    [int]$Rounds = 2,
    [Parameter(Mandatory = $false)]
    [switch]$SkipPipelineCheck,
    [Parameter(Mandatory = $false)]
    [switch]$SkipWorkflowRounds,
    [Parameter(Mandatory = $false)]
    [string]$GatewayUrl = 'http://localhost:8010',
    [Parameter(Mandatory = $false)]
    [string]$MonitoringUrl = 'http://localhost:8001',
    [Parameter(Mandatory = $false)]
    [string]$PrometheusUrl = 'http://localhost:9090',
    [Parameter(Mandatory = $false)]
    [string]$AlertmanagerUrl = 'http://localhost:9093'
)

$ErrorActionPreference = 'Stop'

$PythonExe = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path $PythonExe)) {
    $PythonExe = 'python'
}

Write-Host "[1/4] Generating service profile env override for $Profile"
& $PythonExe scripts/switch_service_profile.py --profile $Profile --output .env.profile.generated

Write-Host "[2/4] Running cloud profile smoke test"
$deploymentMode = if ($Profile -eq 'azure') { 'azure_cloud' } else { 'on_prem' }
& $PythonExe scripts/cloud_profile_smoke_test.py --gateway-url $GatewayUrl --monitoring-url $MonitoringUrl --deployment-mode $deploymentMode
if ($LASTEXITCODE -ne 0) {
    throw "cloud_profile_smoke_test failed"
}

if (-not $SkipPipelineCheck) {
    Write-Host "[3/4] Verifying alert pipeline signal propagation"
    & $PythonExe scripts/verify_alert_pipeline.py --prometheus-url $PrometheusUrl --alertmanager-url $AlertmanagerUrl --gateway-url $GatewayUrl
    if ($LASTEXITCODE -ne 0) {
        throw "verify_alert_pipeline failed"
    }
} else {
    Write-Host "[3/4] Skipped pipeline signal propagation check"
}

if (-not $SkipWorkflowRounds) {
    Write-Host "[4/4] Running full async workflow e2e rounds"
    .\scripts\run_e2e_rounds.ps1 -Rounds $Rounds -AlertmanagerUrl $AlertmanagerUrl -GatewayUrl $GatewayUrl -MonitoringAdapterUrl $MonitoringUrl
    if ($LASTEXITCODE -ne 0) {
        throw "run_e2e_rounds failed"
    }
} else {
    Write-Host "[4/4] Skipped async workflow e2e rounds"
}

Write-Host "Cloud profile e2e completed successfully for profile $Profile"
