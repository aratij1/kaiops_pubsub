param(
    [string]$AlertName = "KaiOpsMySQLAlertsTableRowsHigh",
    [string]$MetricName = "kaiops_mysql_alerts_table_rows",
    [string]$Database = "kaiops",
    [string]$Table = "alerts",
    [string]$PrometheusUrl = "http://localhost:9090",
    [string]$AlertmanagerUrl = "http://localhost:9093",
    [string]$GatewayUrl = "http://localhost:8010",
    [int]$GatewayLimit = 500,
    [ValidateSet("strict", "sanity")]
    [string]$Mode = "sanity",
    [double]$TimeoutSeconds = 60,
    [double]$PollIntervalSeconds = 5,
    [double]$RequestTimeoutSeconds = 8,
    [switch]$EnsureDockerStack,
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Error "Python virtual environment not found at $Python. Create it with: python -m venv .venv ; .venv\\Scripts\\python.exe -m pip install -e ."
}

function Test-EndpointReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSeconds = 45
    )

    $started = Get-Date
    while (((Get-Date) - $started).TotalSeconds -lt $TimeoutSeconds) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4 | Out-Null
            return $true
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

if ($EnsureDockerStack) {
    Write-Host "Ensuring required Docker services are running..."
    $ComposeArgs = @("compose", "up", "-d")
    if ($Rebuild) {
        $ComposeArgs += "--build"
    }
    $ComposeArgs += @("mysql", "monitoring-adapter", "api-gateway", "prometheus", "alertmanager")

    Push-Location $RepoRoot
    try {
        docker @ComposeArgs
    }
    finally {
        Pop-Location
    }
}

Write-Host "Waiting for endpoints..."
$Readiness = @(
    @{ Name = "Prometheus"; Url = "$($PrometheusUrl.TrimEnd('/'))/-/ready" },
    @{ Name = "Alertmanager"; Url = "$($AlertmanagerUrl.TrimEnd('/'))/-/ready" },
    @{ Name = "API Gateway"; Url = "$($GatewayUrl.TrimEnd('/'))/healthz" }
)

foreach ($Target in $Readiness) {
    if (Test-EndpointReady -Url $Target.Url -TimeoutSeconds 60) {
        Write-Host "[OK]   $($Target.Name): $($Target.Url)"
    }
    else {
        Write-Error "[FAIL] $($Target.Name) is not ready at $($Target.Url)"
    }
}

Push-Location $RepoRoot
try {
    & $Python "scripts/verify_alert_pipeline.py" `
        --alert-name $AlertName `
        --metric-name $MetricName `
        --database $Database `
        --table $Table `
        --prometheus-url $PrometheusUrl `
        --alertmanager-url $AlertmanagerUrl `
        --gateway-url $GatewayUrl `
        --gateway-limit $GatewayLimit `
        --mode $Mode `
        --timeout-seconds $TimeoutSeconds `
        --poll-interval-seconds $PollIntervalSeconds `
        --request-timeout-seconds $RequestTimeoutSeconds

    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
