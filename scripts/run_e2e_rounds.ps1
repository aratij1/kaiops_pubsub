$ErrorActionPreference = 'Stop'

function Run-Round {
    param(
        [Parameter(Mandatory = $true)][string]$Tag
    )

    $name = "KaiOpsStable$Tag-" + (Get-Date -Format 'yyyyMMddHHmmss')
    $now = (Get-Date).ToUniversalTime()
    $ends = $now.AddMinutes(10)

    $alert = '[{"labels":{"alertname":"' + $name + '","service":"payments","severity":"critical","category":"latency","instance":"payments-api","application":"payments"},"annotations":{"summary":"E2E validation ' + $name + '","description":"Stable async round ' + $Tag + '"},"startsAt":"' + $now.ToString('o') + '","endsAt":"' + $ends.ToString('o') + '","generatorURL":"http://localhost:9090/graph?g0.expr=vector(1)"}]'

    Invoke-RestMethod -Uri 'http://localhost:9093/api/v2/alerts' -Method Post -ContentType 'application/json' -Body $alert -TimeoutSec 60 | Out-Null

    $row = $null
    for ($i = 0; $i -lt 120; $i++) {
        $recent = Invoke-RestMethod -Uri 'http://localhost:8010/alerts/recent?limit=80' -Method Get -TimeoutSec 60
        $row = $recent.data.rows | Where-Object { $_.name -eq $name } | Select-Object -First 1
        if ($row) { break }
        Start-Sleep -Milliseconds 1000
    }
    if (-not $row) {
        return [pscustomobject]@{
            round = $Tag
            name = $name
            status = 'fail'
            reason = 'not_ingested'
        }
    }

    $processed = $null
    for ($i = 0; $i -lt 240; $i++) {
        try {
            $processed = Invoke-RestMethod -Uri ("http://localhost:8001/alerts/{0}/processed-result" -f $row.id) -Method Get -TimeoutSec 60
            if ($processed.recommendation.id) { break }
        }
        catch {
            # Retry until processed-result is available.
        }
        Start-Sleep -Milliseconds 1000
    }

    if (-not $processed -or -not $processed.recommendation.id) {
        $incidentId = $null
        if ($processed -and $processed.incident -and $processed.incident.id) {
            $incidentId = $processed.incident.id
        }
        elseif ($row.incident_id) {
            $incidentId = $row.incident_id
        }

        $completion = $null
        $missing = $null
        if ($incidentId) {
            try {
                $sc = Invoke-RestMethod -Uri ("http://localhost:8010/incidents/{0}/stage-completeness" -f $incidentId) -Method Get -TimeoutSec 60
                $completion = $sc.data.stage_completion.percentage
                $missing = ($sc.data.stage_completion.missing -join ',')
            }
            catch {
                $completion = 'unknown'
                $missing = 'unknown'
            }
        }

        return [pscustomobject]@{
            round = $Tag
            name = $name
            alert_id = $row.id
            incident_id = $incidentId
            status = 'fail'
            reason = 'no_recommendation'
            completion = $completion
            missing = $missing
        }
    }

    $approve = @{
        incident_id = $processed.incident.id
        recommendation_id = $processed.recommendation.id
        approver = 'admin'
        channel = 'web'
        comment = 'approved in stable e2e round'
    } | ConvertTo-Json

    Invoke-RestMethod -Uri 'http://localhost:8010/approval/approve' -Method Post -ContentType 'application/json' -Body $approve -TimeoutSec 60 | Out-Null

    $comp = $null
    $final = $null
    for ($i = 0; $i -lt 240; $i++) {
        $comp = Invoke-RestMethod -Uri ("http://localhost:8010/incidents/{0}/stage-completeness" -f $processed.incident.id) -Method Get -TimeoutSec 60
        $latest = Invoke-RestMethod -Uri 'http://localhost:8010/alerts/recent?limit=80' -Method Get -TimeoutSec 60
        $final = $latest.data.rows | Where-Object { $_.id -eq $row.id } | Select-Object -First 1
        if (($comp.data.stage_completion.percentage -eq 100) -and ($final.status -eq 'closed')) { break }
        Start-Sleep -Milliseconds 1000
    }

    $ok = (($comp.data.stage_completion.percentage -eq 100) -and ($final.status -eq 'closed'))
    return [pscustomobject]@{
        round = $Tag
        name = $name
        alert_id = $row.id
        incident_id = $processed.incident.id
        recommendation_id = $processed.recommendation.id
        completion = $comp.data.stage_completion.percentage
        alert_status = $final.status
        status = $(if ($ok) { 'pass' } else { 'fail' })
    }
}

$r1 = Run-Round -Tag 'R1'
$r2 = Run-Round -Tag 'R2'
$r3 = Run-Round -Tag 'R3'

$summary = [pscustomobject]@{
    results = @($r1, $r2, $r3)
    passed = (@($r1, $r2, $r3) | Where-Object { $_.status -eq 'pass' }).Count
    failed = (@($r1, $r2, $r3) | Where-Object { $_.status -eq 'fail' }).Count
}

$summary | ConvertTo-Json -Depth 8
