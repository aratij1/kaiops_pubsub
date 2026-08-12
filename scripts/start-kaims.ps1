param(
    [ValidateSet("lean", "observability", "monitoring-authoring", "evaluation", "full")]
    [string]$Profile = "lean",
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Push-Location $workspace
try {
    $env:DOCKER_BUILDKIT = "1"
    $env:COMPOSE_BAKE = "false"
    $env:COMPOSE_PARALLEL_LIMIT = "1"
    docker version --format "Docker engine {{.Server.Version}}"
    if ($LASTEXITCODE -ne 0) { throw "Docker Desktop Linux engine is unavailable." }

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
        & (Join-Path $PSScriptRoot "stop-demo-workloads.ps1")
        if ($LASTEXITCODE -ne 0) { throw "Unable to stop demo workloads" }
    }
    $composeArguments = @("compose")
    if ($Profile -ne "lean") { $composeArguments += @("--profile", $Profile) }
    if ($Build) {
        $buildArguments = @($composeArguments[0..($composeArguments.Count - 1)]) + @("build")
        Write-Host "Building KaiMS sequentially (COMPOSE_PARALLEL_LIMIT=1)..."
        & docker @buildArguments
        if ($LASTEXITCODE -ne 0) { throw "Docker Compose build failed with exit code $LASTEXITCODE" }
    }
    $composeArguments += @("up", "-d", "--no-build")
    if (-not $Build) { $composeArguments += "--no-recreate" }
    Write-Host "Starting KaiMS profile '$Profile'..."
    & docker @composeArguments
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE" }
    & docker compose ps
}
finally { Pop-Location }
