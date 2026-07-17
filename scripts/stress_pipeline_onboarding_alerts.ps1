param(
    [string]$GatewayBase = "http://localhost:8010",
    [string]$MonitoringBase = "http://localhost:8000",
    [int]$TotalAlerts = 20000,
    [int]$BatchSize = 500,
    [int]$DetailWrites = 200
)

$ErrorActionPreference = "Stop"

if ($TotalAlerts -le 0) { throw "TotalAlerts must be > 0" }
if ($BatchSize -le 0) { throw "BatchSize must be > 0" }
if (($TotalAlerts % $BatchSize) -ne 0) { throw "TotalAlerts must be divisible by BatchSize" }
if ($DetailWrites -le 0) { throw "DetailWrites must be > 0" }

function Get-DbCounts {
    $query = @"
SELECT JSON_OBJECT(
  'alerts', (SELECT COUNT(*) FROM alerts),
  'incidents', (SELECT COUNT(*) FROM incidents),
  'incident_events', (SELECT COUNT(*) FROM incident_events),
  'incident_projections', (SELECT COUNT(*) FROM incident_projections),
  'pending_workflows', (SELECT COUNT(*) FROM pending_workflows),
  'onboarding_state', (SELECT COUNT(*) FROM onboarding_state),
  'agent_work_items', (SELECT COUNT(*) FROM agent_work_items)
) AS payload;
"@

    $json = docker exec kaiops-mysql-1 mysql -ukaiops -pkaiops -D kaiops -N -s -e $query
    if (-not $json) {
        throw "Unable to fetch DB counts from MySQL container"
    }
    return ($json | ConvertFrom-Json)
}

function Get-ProjectionStatusCountsSince([string]$sinceUtc) {
    $query = "SELECT status, COUNT(*) AS c FROM incident_projections WHERE updated_at >= '$sinceUtc' GROUP BY status ORDER BY c DESC;"
    $rows = docker exec kaiops-mysql-1 mysql -ukaiops -pkaiops -D kaiops -N -s -e $query
    $map = @{}
    foreach ($line in $rows) {
        $parts = $line -split "`t"
        if ($parts.Length -ge 2) {
            $status = [string]$parts[0]
            $count = [int]$parts[1]
            $map[$status] = $count
        }
    }
    return $map
}

$runId = [DateTime]::UtcNow.ToString("yyyyMMddHHmmss")
$runStartUtc = [DateTime]::UtcNow.ToString("yyyy-MM-dd HH:mm:ss")
$newProjectName = "stress-onboard-$runId"

Write-Host "[1/6] Capturing baseline DB counts..."
$baseline = Get-DbCounts

Write-Host "[2/6] Onboarding new project: $newProjectName"
$onboardingPayload = @{
    project = @{
        name = $newProjectName
        owner_team = "stress-platform"
        environment = "prod"
        region = "us-east-1"
    }
    deployment_mode = "on_prem"
    prometheus_url = "http://prometheus.local:9090"
    new_relic_url = "http://newrelic.local:443"
    datadog_url = "http://datadog.local:443"
    azure_subscription_id = ""
    azure_resource_group = ""
    azure_service_bus_namespace = ""
    azure_service_bus_topic = ""
    azure_service_bus_subscription = ""
    azure_content_safety_enabled = $false
    azure_content_safety_endpoint = ""
    user_assignments = @{
        "stress-admin" = @($newProjectName)
    }
    provider_statuses = @{
        prometheus = @{ ok = $true; message = "connected" }
        new_relic = @{ ok = $true; message = "connected" }
        datadog = @{ ok = $true; message = "connected" }
    }
    active_provider = "prometheus"
}
$null = Invoke-RestMethod -Method Post -Uri "$GatewayBase/onboarding/connectivity" -ContentType "application/json" -Body ($onboardingPayload | ConvertTo-Json -Depth 8)

Write-Host "[3/6] Bulk updating monitoring connectivity details for a single project across $DetailWrites writes..."
$bulkSuccess = 0
$bulkFailed = 0
for ($i = 1; $i -le $DetailWrites; $i++) {
    $projectName = $newProjectName
    $provider = switch ($i % 3) {
        0 { "prometheus" }
        1 { "new_relic" }
        default { "datadog" }
    }

    $payload = @{
        project = @{
            name = $projectName
            owner_team = "stress-platform"
            environment = "prod"
            region = "us-east-1"
        }
        deployment_mode = "on_prem"
        prometheus_url = "http://prometheus.local:9090"
        new_relic_url = "http://newrelic.local:443"
        datadog_url = "http://datadog.local:443"
        azure_subscription_id = ""
        azure_resource_group = ""
        azure_service_bus_namespace = ""
        azure_service_bus_topic = ""
        azure_service_bus_subscription = ""
        azure_content_safety_enabled = $false
        azure_content_safety_endpoint = ""
        user_assignments = @{
            "stress-admin" = @($projectName)
        }
        provider_statuses = @{
            prometheus = @{ ok = ($provider -eq "prometheus"); message = "bulk-check" }
            new_relic = @{ ok = ($provider -eq "new_relic"); message = "bulk-check" }
            datadog = @{ ok = ($provider -eq "datadog"); message = "bulk-check" }
        }
        active_provider = $provider
    }

    try {
        $null = Invoke-RestMethod -Method Post -Uri "$GatewayBase/onboarding/connectivity" -ContentType "application/json" -Body ($payload | ConvertTo-Json -Depth 8)
        $bulkSuccess += 1
    } catch {
        $bulkFailed += 1
    }
}

Write-Host "[4/6] Ingesting $TotalAlerts alerts in batches of $BatchSize via Alertmanager webhook..."
$batchCount = [int]($TotalAlerts / $BatchSize)
$totalReceived = 0
$totalIngested = 0
$totalSkipped = 0
$ingestFailures = 0

for ($batch = 1; $batch -le $batchCount; $batch++) {
    $alerts = New-Object System.Collections.Generic.List[object]
    $batchPrefix = "stress-$runId-b$batch"

    for ($j = 1; $j -le $BatchSize; $j++) {
        $globalIndex = (($batch - 1) * $BatchSize) + $j
        $severity = if (($globalIndex % 20) -eq 0) { "critical" } elseif (($globalIndex % 5) -eq 0) { "high" } else { "warning" }

        $alerts.Add(@{
            status = "firing"
            labels = @{
                alertname = "StressPipelineAlert-$batchPrefix-$j"
                application = "stress-lab"
                service = "payments"
                environment = "prod"
                severity = $severity
                run_id = $runId
                sequence = "$globalIndex"
            }
            annotations = @{
                summary = "Stress pipeline alert $globalIndex"
                description = "Stress test alert $globalIndex for pipeline throughput validation"
            }
            fingerprint = "$runId-$globalIndex"
            startsAt = [DateTime]::UtcNow.ToString("o")
            endsAt = ""
            generatorURL = "stress://kaiops/$runId/$globalIndex"
        }) | Out-Null
    }

    $webhookPayload = @{
        receiver = "kaiops-stress"
        status = "firing"
        commonLabels = @{
            application = "stress-lab"
            service = "payments"
            environment = "prod"
            source = "stress-harness"
        }
        commonAnnotations = @{
            summary = "KaiOps stress batch"
        }
        alerts = $alerts
    }

    try {
        $resp = Invoke-RestMethod -Method Post -Uri "$MonitoringBase/alerts/alertmanager" -ContentType "application/json" -Body ($webhookPayload | ConvertTo-Json -Depth 10)
        $totalReceived += [int]($resp.received)
        $totalIngested += [int]($resp.ingested)
        $totalSkipped += [int]($resp.skipped)
    } catch {
        $ingestFailures += 1
    }

    if (($i % 25) -eq 0) {
        Write-Host "  detail writes complete: $i / $DetailWrites"
    }
}

Write-Host "[5/6] Capturing post-run DB counts and status distributions..."
$after = Get-DbCounts
$statusCounts = Get-ProjectionStatusCountsSince -sinceUtc $runStartUtc

$alertsDelta = [int]$after.alerts - [int]$baseline.alerts
$incidentsDelta = [int]$after.incidents - [int]$baseline.incidents
$eventsDelta = [int]$after.incident_events - [int]$baseline.incident_events
$projectionsDelta = [int]$after.incident_projections - [int]$baseline.incident_projections
$onboardingDelta = [int]$after.onboarding_state - [int]$baseline.onboarding_state
$agentWorkDelta = [int]$after.agent_work_items - [int]$baseline.agent_work_items

$alertAcceptancePct = if ($TotalAlerts -gt 0) { [math]::Round(($totalIngested * 100.0) / $TotalAlerts, 2) } else { 0 }
$alertsPersistPct = if ($totalIngested -gt 0) { [math]::Round(($alertsDelta * 100.0) / $totalIngested, 2) } else { 0 }
$projectionCoveragePct = if ($alertsDelta -gt 0) { [math]::Round(($projectionsDelta * 100.0) / $alertsDelta, 2) } else { 0 }
$eventsPerAlert = if ($alertsDelta -gt 0) { [math]::Round(($eventsDelta * 1.0) / $alertsDelta, 3) } else { 0 }

$pipelineSummary = [ordered]@{
    run_id = $runId
    run_start_utc = $runStartUtc
    onboarding_project = $newProjectName
    onboarding_detail_writes_requested = $DetailWrites
    onboarding_bulk_success = $bulkSuccess
    onboarding_bulk_failed = $bulkFailed
    ingestion_requested_alerts = $TotalAlerts
    ingestion_batches = $batchCount
    ingestion_batch_size = $BatchSize
    ingestion_failures = $ingestFailures
    ingestion_received = $totalReceived
    ingestion_ingested = $totalIngested
    ingestion_skipped = $totalSkipped
    acceptance_pct = $alertAcceptancePct
    baseline = $baseline
    after = $after
    deltas = [ordered]@{
        alerts = $alertsDelta
        incidents = $incidentsDelta
        incident_events = $eventsDelta
        incident_projections = $projectionsDelta
        onboarding_state = $onboardingDelta
        agent_work_items = $agentWorkDelta
    }
    completion = [ordered]@{
        alerts_persisted_pct = $alertsPersistPct
        projection_coverage_pct = $projectionCoveragePct
        events_per_alert = $eventsPerAlert
    }
    projection_status_counts_since_start = $statusCounts
}

Write-Host "[6/6] Stress test summary:"
$pipelineSummary | ConvertTo-Json -Depth 8
