param(
  [string]$ProjectName = "etl-orders-dq-$(Get-Date -Format yyyyMMddHHmmss)",
  [string]$GatewayUrl = "http://localhost:8010",
  [string]$InputFile = "data/e2e/etl_orders_input.csv",
  [string]$RunbookFile = "docs/e2e/etl-order-quality-runbook.md"
)

$ErrorActionPreference = "Stop"

function Invoke-KaiOpsJson {
  param(
    [Parameter(Mandatory = $true)][string]$Uri,
    [string]$Method = "GET",
    [object]$Body = $null
  )
  $headers = @{ Accept = "application/json" }
  if ($null -ne $Body) {
    $json = $Body | ConvertTo-Json -Depth 40
    return Invoke-RestMethod -Uri $Uri -Method $Method -ContentType "application/json" -Headers $headers -Body $json -TimeoutSec 90
  }
  return Invoke-RestMethod -Uri $Uri -Method $Method -Headers $headers -TimeoutSec 90
}

function Unwrap-Gateway {
  param([object]$Payload)
  if ($null -ne $Payload.data) {
    return $Payload.data
  }
  return $Payload
}

function Sql-Quote {
  param([object]$Value)
  $text = [string]$Value
  return "'" + $text.Replace("\", "\\").Replace("'", "''") + "'"
}

function Get-ComposeContainer {
  param([string]$Service)
  $container = docker compose --profile application-layer --profile ai-layer --env-file .env -f docker-compose.yml -f docker-compose.layered.yml ps -q $Service
  $container = [string]$container
  if ([string]::IsNullOrWhiteSpace($container)) {
    throw "No running container found for compose service $Service"
  }
  return ($container -split "`r?`n")[0].Trim()
}

function Load-EtlRows {
  param([string]$Path)
  $rows = Import-Csv -Path $Path
  $enriched = @()
  foreach ($row in $rows) {
    $reasons = New-Object System.Collections.Generic.List[string]
    $customer = [string]$row.customer_id
    [decimal]$amount = 0
    if (-not [decimal]::TryParse([string]$row.amount, [ref]$amount)) {
      $reasons.Add("invalid_amount")
    }
    if ([string]::IsNullOrWhiteSpace($customer)) {
      $reasons.Add("missing_customer_id")
    }
    if ($amount -lt 0) {
      $reasons.Add("negative_amount")
    }
    $row | Add-Member -NotePropertyName dq_status -NotePropertyValue ($(if ($reasons.Count -gt 0) { "rejected" } else { "accepted" })) -Force
    $row | Add-Member -NotePropertyName dq_reason -NotePropertyValue ($reasons -join "|") -Force
    $enriched += $row
  }
  return $enriched
}

function Load-MysqlEtlTable {
  param(
    [string]$Project,
    [array]$Rows
  )
  $table = "etl_order_quality_events"
  $sqlLines = New-Object System.Collections.Generic.List[string]
  $sqlLines.Add("CREATE TABLE IF NOT EXISTS $table (id BIGINT AUTO_INCREMENT PRIMARY KEY, project_name VARCHAR(128) NOT NULL, order_id VARCHAR(64) NOT NULL, customer_id VARCHAR(128) NULL, amount DECIMAL(12,2) NOT NULL, status VARCHAR(32) NOT NULL, region VARCHAR(64) NOT NULL, event_ts VARCHAR(64) NOT NULL, dq_status VARCHAR(32) NOT NULL, dq_reason VARCHAR(255) NULL, loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
  $sqlLines.Add("DELETE FROM $table WHERE project_name = $(Sql-Quote $Project);")
  foreach ($row in $Rows) {
    $sqlLines.Add("INSERT INTO $table (project_name, order_id, customer_id, amount, status, region, event_ts, dq_status, dq_reason) VALUES ($(Sql-Quote $Project), $(Sql-Quote $row.order_id), $(Sql-Quote $row.customer_id), $([decimal]$row.amount), $(Sql-Quote $row.status), $(Sql-Quote $row.region), $(Sql-Quote $row.event_ts), $(Sql-Quote $row.dq_status), $(Sql-Quote $row.dq_reason));")
  }
  $sqlLines.Add("SELECT COUNT(*) AS total_rows, SUM(CASE WHEN dq_status='rejected' THEN 1 ELSE 0 END) AS rejected_rows, SUM(CASE WHEN customer_id='' OR customer_id IS NULL THEN 1 ELSE 0 END) AS null_customer_rows FROM $table WHERE project_name = $(Sql-Quote $Project);")
  $tempSql = Join-Path $env:TEMP "$Project-etl-load.sql"
  Set-Content -Path $tempSql -Value ($sqlLines -join "`n") -Encoding UTF8
  $mysqlContainer = Get-ComposeContainer -Service "mysql"
  $output = Get-Content -Path $tempSql -Raw | docker exec -i $mysqlContainer mysql -ukaiops -pkaiops kaiops
  return @{
    table = $table
    output = ($output -join "`n")
  }
}

$rows = Load-EtlRows -Path $InputFile
$totalRows = $rows.Count
$rejectedRows = @($rows | Where-Object { $_.dq_status -eq "rejected" }).Count
$nullCustomerRows = @($rows | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.customer_id) }).Count
$nullCustomerRatio = if ($totalRows -gt 0) { [math]::Round($nullCustomerRows / $totalRows, 4) } else { 0 }
$metrics = @{
  total_rows = $totalRows
  rejected_rows = $rejectedRows
  null_customer_rows = $nullCustomerRows
  null_customer_ratio = $nullCustomerRatio
}

$mysqlResult = Load-MysqlEtlTable -Project $ProjectName -Rows $rows
$runbookText = (Get-Content -Path $RunbookFile -Raw).Replace("etl-orders-dq", $ProjectName)
$docText = @"
$runbookText

## Current E2E Batch Evidence
- total_rows: $($metrics.total_rows)
- rejected_rows: $($metrics.rejected_rows)
- null_customer_ratio: $($metrics.null_customer_ratio)
"@

$sourceDoc = @{
  name = "$ProjectName-etl-data-quality-runbook.md"
  kind = "runbook"
  category = "knowledge_pack"
  text = $docText
  excerpt = "Order ETL data quality runbook with null customer, rejected row, rollback, and validation checks."
}

$requirements = @(
  "Create a critical Prometheus alert named $($ProjectName)_null_customer_ratio_high when null customer ID ratio is above 20 percent for 5 minutes.",
  "Create a high Prometheus alert named $($ProjectName)_rejected_rows_detected when rejected ETL rows are greater than zero.",
  "Create a warning Prometheus alert named $($ProjectName)_etl_load_latency_high when ETL load latency is above 120 seconds."
)

$onboardingPayload = @{
  project_mode = "new"
  onboarding_path = "setup_monitoring"
  start_rules_onboarding = $true
  selected_monitoring_tool = "prometheus"
  plain_language_requirements = $requirements
  source_documents = @($sourceDoc)
  generate_documents = $true
  include_smoke_test_alert = $true
  connectivity = @{
    project = @{
      name = $ProjectName
      owner_team = "data-platform"
      environment = "prod"
      region = "us-east-1"
    }
    deployment_mode = "on_prem"
    prometheus_url = "http://prometheus:9090"
    new_relic_url = ""
    datadog_url = ""
    active_provider = "prometheus"
    provider_statuses = @{
      prometheus = @{ ok = $true; message = "Local Prometheus configured for ETL E2E" }
    }
    user_assignments = @{
      "l2.operator" = @($ProjectName)
      "l3.engineer" = @($ProjectName)
      "administrator" = @($ProjectName)
    }
  }
}

$onboarding = Unwrap-Gateway (Invoke-KaiOpsJson -Uri "$GatewayUrl/onboarding/complete" -Method POST -Body $onboardingPayload)

$knowledgePayload = @{
  service = $ProjectName
  environment = "prod"
  owner_team = "data-platform"
  approved_by = "e2e-admin"
  documents = @(
    @{
      name = $sourceDoc.name
      category = "knowledge_pack"
      text = $sourceDoc.text
      excerpt = $sourceDoc.excerpt
    }
  )
}
$knowledge = Unwrap-Gateway (Invoke-KaiOpsJson -Uri "$GatewayUrl/knowledge-pack/approve" -Method POST -Body $knowledgePayload)

$ragIngestResults = @()
$generatedDocs = @($onboarding.rag_documents)
foreach ($doc in $generatedDocs) {
  try {
    $ragIngestResults += Unwrap-Gateway (Invoke-KaiOpsJson -Uri "$GatewayUrl/rag/documents" -Method POST -Body $doc)
  } catch {
    $ragIngestResults += @{ status = "failed"; title = $doc.title; error = $_.Exception.Message }
  }
}

$ragSync = Unwrap-Gateway (Invoke-KaiOpsJson -Uri "$GatewayUrl/rag/index/sync" -Method POST -Body @{})
$query = [System.Uri]::EscapeDataString($ProjectName)
$ragSearch = Unwrap-Gateway (Invoke-KaiOpsJson -Uri "$GatewayUrl/rag/search?query=$query&limit=8")

$alertPayload = @{
  source = "prometheus"
  name = "$($ProjectName)_RejectedRowsDetected"
  service = $ProjectName
  environment = "prod"
  severity = "critical"
  description = "ETL rejected_rows=$($metrics.rejected_rows) and null_customer_ratio=$($metrics.null_customer_ratio) after landing the order input file."
  labels = @{
    alertname = "$($ProjectName)_RejectedRowsDetected"
    service = $ProjectName
    project = $ProjectName
    environment = "prod"
    severity = "critical"
    pipeline = "orders-etl"
    table = "etl_order_quality_events"
  }
  annotations = @{
    summary = "Order ETL data quality violation"
    description = "Rejected ETL rows were loaded to MySQL and should be triaged with the service knowledge pack."
    runbook = "$ProjectName ETL data quality runbook"
  }
}
$alertIngest = Unwrap-Gateway (Invoke-KaiOpsJson -Uri "$GatewayUrl/api/v1/alerts/prometheus" -Method POST -Body $alertPayload)

$recentAlert = $null
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline -and $null -eq $recentAlert) {
  $recent = Unwrap-Gateway (Invoke-KaiOpsJson -Uri "$GatewayUrl/alerts/recent?limit=200")
  foreach ($row in @($recent.rows)) {
    if ($row.service -eq $ProjectName) {
      $recentAlert = $row
      break
    }
  }
  if ($null -eq $recentAlert) {
    Start-Sleep -Seconds 5
  }
}

$state = Unwrap-Gateway (Invoke-KaiOpsJson -Uri "$GatewayUrl/onboarding/state")
$stateRows = @($state.rows | Where-Object { $_.project_name -eq $ProjectName })
$searchMatches = @()
if ($null -ne $ragSearch.matches) {
  $searchMatches = @($ragSearch.matches)
} elseif ($null -ne $ragSearch.rows) {
  $searchMatches = @($ragSearch.rows)
}
$projectSearchMatches = @($searchMatches | Where-Object {
  ($_.path -like "*$ProjectName*") -or
  ($_.title -like "*$ProjectName*") -or
  (@($_.services) -contains $ProjectName)
})
$linkedDocuments = $null
if ($null -ne $recentAlert -and -not [string]::IsNullOrWhiteSpace([string]$recentAlert.id)) {
  $linkedDocuments = Invoke-KaiOpsJson -Uri "$GatewayUrl/alerts/$($recentAlert.id)/linked-documents"
}
$linkedDocumentRows = @()
if ($null -ne $linkedDocuments.linked_documents) {
  $linkedDocumentRows = @($linkedDocuments.linked_documents)
}

$result = @{
  ok = (($stateRows.Count -gt 0) -and ($null -ne $recentAlert) -and ($projectSearchMatches.Count -gt 0) -and ($linkedDocumentRows.Count -gt 0) -and ($onboarding.rules_onboarding.status -eq "ready-for-approval"))
  project_name = $ProjectName
  etl = @{
    input_file = $InputFile
    rows_loaded = $rows.Count
    quality_metrics = $metrics
    mysql = $mysqlResult
  }
  admin_monitoring = @{
    onboarding_status = $onboarding.rules_onboarding.status
    workflow_id = $onboarding.rules_onboarding.workflow_id
    generated_rule_count = @($onboarding.rules_onboarding.result.generated_rules).Count
    generated_document_count = $generatedDocs.Count
    state_rows = $stateRows.Count
  }
  knowledge = @{
    approval_status = $knowledge.status
    rag_ingest_results = $ragIngestResults
    rag_sync_status = $ragSync.status
    search_match_count = $searchMatches.Count
    project_search_match_count = $projectSearchMatches.Count
    top_match = $(if ($searchMatches.Count -gt 0) { $searchMatches[0] } else { $null })
    linked_document_count = $linkedDocumentRows.Count
    linked_documents = $linkedDocumentRows
  }
  alert_flow = @{
    ingest = $alertIngest
    recent_alert = $recentAlert
  }
}

$result | ConvertTo-Json -Depth 60
if (-not $result.ok) {
  exit 1
}
