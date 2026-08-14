param(
    [ValidateSet("lean", "observability", "monitoring-authoring", "evaluation", "full")]
    [string]$Profile = "lean",
    [switch]$Build,
    [int]$ReadyTimeoutSeconds = 180,
    [int]$MaximumRunningContainers = 32,
    [int]$DockerCommandTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
function Invoke-DockerCommand {
    param([string[]]$Arguments, [string]$Description)
    $stdout = Join-Path $env:TEMP ("kaims-docker-{0}.out" -f [guid]::NewGuid())
    $stderr = Join-Path $env:TEMP ("kaims-docker-{0}.err" -f [guid]::NewGuid())
    try {
        $process = Start-Process docker -ArgumentList $Arguments -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if (-not $process.WaitForExit($DockerCommandTimeoutSeconds * 1000)) {
            $process.Kill()
            throw "$Description timed out after $DockerCommandTimeoutSeconds seconds. Docker Desktop is saturated; restart Docker Desktop before retrying."
        }
        Get-Content $stdout -ErrorAction SilentlyContinue | Write-Host
        Get-Content $stderr -ErrorAction SilentlyContinue | Write-Host
        if ($process.ExitCode -ne 0) { throw "$Description failed with exit code $($process.ExitCode)." }
    }
    finally {
        Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue
    }
}
Push-Location $workspace
try {
    $env:DOCKER_BUILDKIT = "1"
    $env:COMPOSE_BAKE = "false"
    $env:COMPOSE_PARALLEL_LIMIT = "1"
    docker version --format "Docker engine {{.Server.Version}}"
    if ($LASTEXITCODE -ne 0) { throw "Docker Desktop Linux engine is unavailable." }

    $optionalServices = @(
        "zookeeper", "kafka", "mysql-exporter", "node-exporter", "blackbox-exporter",
        "kafka-exporter", "alertmanager", "fault-lab", "otel-collector", "jaeger",
        "prometheus", "grafana", "discovery-service",
        "metrics-validation-agent", "rule-generation-agent", "prometheus-config-service",
        "validation-agent", "dashboard-generator", "evaluation-service",
        "temporal-pilot-worker", "temporal-ui", "jenkins", "ui-dev"
    )
    if ($Profile -eq "lean") {
        # Stop only known optional services. Avoid a project-wide orphan
        # reconciliation, which can touch an unrelated unhealthy core worker.
        Invoke-DockerCommand -Arguments (@("compose", "stop") + $optionalServices) -Description "Optional-service cleanup"
        & (Join-Path $PSScriptRoot "stop-demo-workloads.ps1")
        if ($LASTEXITCODE -ne 0) { throw "Unable to stop demo workloads" }
    }
    $dockerInfo = docker info --format "{{.NCPU}}|{{.MemTotal}}|{{.ContainersRunning}}"
    if ($LASTEXITCODE -ne 0 -or -not $dockerInfo) { throw "Docker engine did not return capacity information." }
    $capacity = $dockerInfo -split "\|"
    $memoryGb = [math]::Round(([double]$capacity[1] / 1GB), 1)
    $runningContainers = [int]$capacity[2]
    Write-Host "Docker capacity after optional-service cleanup: $($capacity[0]) CPU, ${memoryGb} GB, $runningContainers running containers."
    if ($runningContainers -gt $MaximumRunningContainers) {
        throw "Docker is still running $runningContainers containers (safe local limit: $MaximumRunningContainers). Stop overlapping Compose projects, then retry. Run 'docker compose ls' to identify them."
    }
    $leanServices = @(
        "mysql", "temporal", "redis", "rabbitmq",
        "monitoring-adapter", "monitoring-ingestion-worker", "application-onboarding",
        "api-gateway", "alert-intelligence", "orchestrator", "context-agent",
        "discovery-mcp", "docker-socket-proxy", "model-router", "resolution-agent",
        "approval-service", "notification-service", "remediation-engine",
        "closure-service", "knowledge-development-worker", "ui"
    )
    $composeArguments = @("compose")
    if ($Profile -ne "lean") { $composeArguments += @("--profile", $Profile) }
    if ($Build) {
        $buildArguments = @($composeArguments[0..($composeArguments.Count - 1)]) + @("build")
        if ($Profile -eq "lean") { $buildArguments += $leanServices }
        Write-Host "Building KaiMS sequentially (COMPOSE_PARALLEL_LIMIT=1)..."
        try { Invoke-DockerCommand -Arguments $buildArguments -Description "KaiMS sequential build" }
        catch {
            Write-Warning "BuildKit failed. Retrying once with the classic builder."
            $env:DOCKER_BUILDKIT = "0"
            Invoke-DockerCommand -Arguments $buildArguments -Description "KaiMS classic-builder retry"
        }
    }
    $composeArguments += @("up", "-d", "--no-build")
    if (-not $Build) { $composeArguments += "--no-recreate" }
    if ($Profile -eq "lean") { $composeArguments += $leanServices }
    Write-Host "Starting KaiMS profile '$Profile'..."
    Invoke-DockerCommand -Arguments $composeArguments -Description "KaiMS startup"

    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    do {
        Start-Sleep -Seconds 3
        try {
            $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8501/" -TimeoutSec 5
            $ready = $response.StatusCode -eq 200 -and $response.Content -match '<div id="root"></div>'
        }
        catch { $ready = $false }
    } while (-not $ready -and (Get-Date) -lt $deadline)
    if (-not $ready) {
        & docker compose ps
        & docker compose logs --tail 80 api-gateway ui
        throw "KaiMS UI did not become ready within $ReadyTimeoutSeconds seconds."
    }
    & docker compose ps @leanServices
    Write-Host "KaiMS is ready: http://127.0.0.1:8501" -ForegroundColor Green
}
finally { Pop-Location }
