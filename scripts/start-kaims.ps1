param(
    [ValidateSet("lean", "observability", "monitoring-authoring", "evaluation", "full")]
    [string]$Profile = "lean",
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Push-Location $workspace
try {
    $optionalServices = @(
        "mysql-exporter", "node-exporter", "blackbox-exporter", "alertmanager",
        "otel-collector", "jaeger", "prometheus", "grafana", "discovery-service",
        "metrics-validation-agent", "rule-generation-agent", "prometheus-config-service",
        "validation-agent", "dashboard-generator", "evaluation-service",
        "temporal-pilot-worker", "temporal-ui"
    )
    if ($Profile -eq "lean") {
        # Stop only known optional services. Avoid a project-wide orphan
        # reconciliation, which can touch an unrelated unhealthy core worker.
        & docker compose stop @optionalServices
        if ($LASTEXITCODE -ne 0) { throw "Unable to stop one or more optional services" }
    }
    $composeArguments = @("compose")
    if ($Profile -ne "lean") { $composeArguments += @("--profile", $Profile) }
    $composeArguments += @("up", "-d")
    if ($Build) { $composeArguments += "--build" }
    else { $composeArguments += "--no-recreate" }
    Write-Host "Starting KaiMS profile '$Profile'..."
    & docker @composeArguments
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE" }
    & docker compose ps
}
finally { Pop-Location }
