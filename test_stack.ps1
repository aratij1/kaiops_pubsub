$ErrorActionPreference = "Continue"

Write-Host "=================================================="
Write-Host "KAI-MS FULL STACK AUTOMATED VERIFICATION"
Write-Host "=================================================="

$baseUrl = "http://localhost:8010"
$uiUrl = "http://localhost:8501"

# 1. UI Root Test
Write-Host "`n[1] Testing UI Root Endpoint ($uiUrl)..."
try {
    $uiResponse = Invoke-WebRequest -Uri $uiUrl -Method Get
    Write-Host "UI Status: $($uiResponse.StatusCode) OK"
} catch {
    Write-Host "UI Failed: $_"
}

# 2. API Gateway Health
Write-Host "`n[2] Testing API Gateway Health ($baseUrl/healthz)..."
try {
    $gwHealth = Invoke-RestMethod -Uri "$baseUrl/healthz" -Method Get
    Write-Host "Gateway Health: $(ConvertTo-Json $gwHealth -Compress)"
} catch {
    Write-Host "Gateway Health Failed: $_"
}

# 3. Role Authentication & Token Testing
Write-Host "`n[3] Testing Role Authentication for all 5 Personas..."
$roles = @(
    @{ username = "admin"; password = "Admin@123456"; expectedRole = "Administrator" },
    @{ username = "l1_operator"; password = "L1Operator@123456"; expectedRole = "L1 Operator" },
    @{ username = "l2_engineer"; password = "L2Engineer@123456"; expectedRole = "L2 Engineer" },
    @{ username = "l3_engineer"; password = "L3Engineer@123456"; expectedRole = "L3 Engineer" },
    @{ username = "executive"; password = "Executive@123456"; expectedRole = "Executive" }
)

$tokens = @{}
foreach ($r in $roles) {
    try {
        $body = @{ username = $r.username; password = $r.password } | ConvertTo-Json
        $loginRes = Invoke-RestMethod -Uri "$baseUrl/auth/login" -Method Post -ContentType "application/json" -Body $body
        $tokens[$r.username] = $loginRes.access_token
        Write-Host "Auth Succeeded for $($r.username) -> Role: $($loginRes.user.role_name)"
    } catch {
        Write-Host "Auth FAILED for $($r.username): $_"
    }
}

$adminToken = $tokens["admin"]
$operatorToken = $tokens["l1_operator"]
$adminHeaders = @{ Authorization = "Bearer $adminToken" }
$operatorHeaders = @{ Authorization = "Bearer $operatorToken" }

# 4. Core Microservice Endpoints via API Gateway
Write-Host "`n[4] Testing Core Microservice Endpoints..."
$endpoints = @(
    @{ name = "Auth Config"; path = "/auth/config"; method = "GET"; headers = @{} },
    @{ name = "Auth Me"; path = "/auth/me"; method = "GET"; headers = $adminHeaders },
    @{ name = "Applications List"; path = "/applications"; method = "GET"; headers = $adminHeaders },
    @{ name = "Alerts All"; path = "/alerts/all"; method = "GET"; headers = $adminHeaders },
    @{ name = "Landing Pad Recent"; path = "/landing-pad/recent"; method = "GET"; headers = $adminHeaders },
    @{ name = "Incidents Metadata"; path = "/incidents/metadata"; method = "GET"; headers = $adminHeaders },
    @{ name = "Pending Approvals"; path = "/approvals/pending"; method = "GET"; headers = $adminHeaders },
    @{ name = "Gateway Recent Events"; path = "/gateway/recent"; method = "GET"; headers = $adminHeaders },
    @{ name = "Gateway Safety Summary"; path = "/gateway/summary"; method = "GET"; headers = $adminHeaders },
    @{ name = "Model Providers Status"; path = "/model/providers/status"; method = "GET"; headers = $adminHeaders }
)

foreach ($ep in $endpoints) {
    try {
        $res = Invoke-RestMethod -Uri "$baseUrl$($ep.path)" -Method $ep.method -Headers $ep.headers
        $sample = ConvertTo-Json $res -Compress
        if ($sample.Length -gt 120) { $sample = $sample.Substring(0, 120) + "..." }
        Write-Host "Endpoint $($ep.name) ($($ep.path)): SUCCESS -> $sample"
    } catch {
        Write-Host "Endpoint $($ep.name) ($($ep.path)): FAILED -> $_"
    }
}

# 5. Model Router Evaluation & Fallback Flow
Write-Host "`n[5] Testing Model Router Direct Routing Flow..."
try {
    $promptPayload = @{
        prompt = "Analyze this test alert: High CPU utilization on payment-service."
        provider = "local"
        task = "rca"
    } | ConvertTo-Json
    $modelRes = Invoke-RestMethod -Uri "$baseUrl/model/route" -Method Post -ContentType "application/json" -Headers $adminHeaders -Body $promptPayload
    Write-Host "Model Router Response: $(ConvertTo-Json $modelRes -Compress)"
} catch {
    Write-Host "Model Router Route: $_"
}

# 6. Role Authorization Gating (Admin vs L1 Operator)
Write-Host "`n[6] Testing RBAC Authorization Boundaries..."
try {
    # Admin users list is restricted
    $adminUsers = Invoke-RestMethod -Uri "$baseUrl/auth/users" -Method Get -Headers $adminHeaders
    Write-Host "Admin accessing /auth/users: ALLOWED ($( $adminUsers.rows.Count ) users returned)"
} catch {
    Write-Host "Admin /auth/users: $_"
}

try {
    $opUsers = Invoke-RestMethod -Uri "$baseUrl/auth/users" -Method Get -Headers $operatorHeaders
    Write-Host "L1 Operator accessing /auth/users: UNEXPECTED ALLOW"
} catch {
    Write-Host "L1 Operator accessing /auth/users: BLOCKED AS EXPECTED (Status: $($_.Exception.Response.StatusCode.value__))"
}

# 7. Alert Ingestion & Pipeline Test
Write-Host "`n[7] Ingesting Synthetic Alert to Test Ingestion Pipeline..."
$alertId = [guid]::NewGuid().ToString()
$sampleAlert = @{
    version = "4"
    groupKey = "{}:{alertname=`"HighMemoryUsage`"}"
    status = "firing"
    receiver = "kaiops-webhook"
    alerts = @(
        @{
            status = "firing"
            labels = @{
                alertname = "HighMemoryUsage"
                severity = "critical"
                service = "checkout-service"
                environment = "production"
                project_name = "KaiMS"
                instance = "checkout-prod-01"
            }
            annotations = @{
                summary = "Memory usage above 95% on checkout-service"
                description = "Container checkout-prod-01 has exceeded memory threshold."
            }
            startsAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            fingerprint = $alertId.Substring(0, 16)
        }
    )
} | ConvertTo-Json -Depth 5

try {
    $ingestRes = Invoke-RestMethod -Uri "$baseUrl/alerts" -Method Post -ContentType "application/json" -Headers $adminHeaders -Body $sampleAlert
    Write-Host "Alert Ingestion Succeeded: $(ConvertTo-Json $ingestRes -Compress)"
} catch {
    Write-Host "Alert Ingestion Failed: $_"
}

Start-Sleep -Seconds 2

try {
    $recentAlerts = Invoke-RestMethod -Uri "$baseUrl/alerts/all" -Method Get -Headers $adminHeaders
    Write-Host "Total Alerts in Stream after ingestion: $( $recentAlerts.data.rows.Count )"
} catch {
    Write-Host "Alert check failed: $_"
}

Write-Host "`n=================================================="
Write-Host "VERIFICATION RUN COMPLETE"
Write-Host "=================================================="
