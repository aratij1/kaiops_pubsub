param(
    [string]$GatewayBase = "http://localhost:8010",
    [string]$MonitoringBase = "http://localhost:8001",
    [int]$PostIngestSettleSeconds = 15,
    [int]$MaxPersistenceWaitSeconds = 180,
    [string]$MysqlContainer = ""
)

$ErrorActionPreference = "Stop"
$arguments = @{
    GatewayBase = $GatewayBase
    MonitoringBase = $MonitoringBase
    TotalAlerts = 1000
    BatchSize = 100
    DetailWrites = 1
    PostIngestSettleSeconds = $PostIngestSettleSeconds
    MaxPersistenceWaitSeconds = $MaxPersistenceWaitSeconds
    RequireEndToEndTarget = $true
}
if ($MysqlContainer.Trim()) { $arguments.MysqlContainer = $MysqlContainer }

& "$PSScriptRoot/stress_pipeline_onboarding_alerts.ps1" @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
