param(
    [switch]$NoUi
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Read-DotEnvFile {
    param([string]$Path)

    $Map = @{}
    if (-not (Test-Path $Path)) {
        return $Map
    }

    foreach ($Line in Get-Content -Path $Path) {
        if ($Line -match '^\s*#') {
            continue
        }
        if ($Line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            continue
        }

        $Key = $matches[1]
        $Value = $matches[2].Trim()

        if ($Value.Length -ge 2) {
            if (($Value.StartsWith('"') -and $Value.EndsWith('"')) -or ($Value.StartsWith("'") -and $Value.EndsWith("'"))) {
                $Value = $Value.Substring(1, $Value.Length - 2)
            }
        }

        $Map[$Key] = $Value
    }

    return $Map
}

function Resolve-ConfigValue {
    param(
        [string]$Name,
        [string]$Default,
        [hashtable]$DotEnv
    )

    $FromProcess = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($FromProcess)) {
        return $FromProcess
    }

    if ($DotEnv.ContainsKey($Name) -and -not [string]::IsNullOrWhiteSpace($DotEnv[$Name])) {
        return [string]$DotEnv[$Name]
    }

    return $Default
}

function Stop-ProcessByPorts {
    param([int[]]$Ports)

    foreach ($Port in $Ports) {
        $Connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $Connections) {
            continue
        }

        $OwnerIds = $Connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($OwnerId in $OwnerIds) {
            try {
                $Target = Get-Process -Id $OwnerId -ErrorAction Stop
                Stop-Process -Id $OwnerId -Force -ErrorAction Stop
                Write-Host "Stopped process $($Target.ProcessName) (PID $OwnerId) on port $Port"
            }
            catch {
                Write-Warning "Unable to stop PID $OwnerId on port ${Port}: $($_.Exception.Message)"
            }
        }
    }
}

if (-not (Test-Path $Python)) {
    Write-Error "Virtual environment not found at $Python. Create it with: python -m venv .venv"
}

$ServicePaths = @(
    "services\common",
    "services\api-gateway",
    "services\alert-intelligence",
    "services\context-agent",
    "services\model-router",
    "services\resolution-agent",
    "services\orchestrator",
    "services\approval-service",
    "services\remediation-engine",
    "services\closure-service",
    "services\monitoring-adapter"
) | ForEach-Object { Join-Path $RepoRoot $_ }

$PythonPath = $ServicePaths -join ";"
$DotEnv = Read-DotEnvFile -Path (Join-Path $RepoRoot ".env")

$Config = @{
    KAFKA_ENABLED = Resolve-ConfigValue -Name "KAFKA_ENABLED" -Default "false" -DotEnv $DotEnv
    EVENT_BUS_PROVIDER = Resolve-ConfigValue -Name "EVENT_BUS_PROVIDER" -Default "noop" -DotEnv $DotEnv
    MESSAGE_BUS_DYNAMIC_ROUTING = Resolve-ConfigValue -Name "MESSAGE_BUS_DYNAMIC_ROUTING" -Default "true" -DotEnv $DotEnv
    MESSAGE_BUS_STREAM_THRESHOLD = Resolve-ConfigValue -Name "MESSAGE_BUS_STREAM_THRESHOLD" -Default "500" -DotEnv $DotEnv
    MESSAGE_BUS_DEFAULT_PROVIDER = Resolve-ConfigValue -Name "MESSAGE_BUS_DEFAULT_PROVIDER" -Default "rabbitmq" -DotEnv $DotEnv
    MESSAGE_BUS_WORKER_COUNT = Resolve-ConfigValue -Name "MESSAGE_BUS_WORKER_COUNT" -Default "1" -DotEnv $DotEnv
    RABBITMQ_URL = Resolve-ConfigValue -Name "RABBITMQ_URL" -Default "amqp://guest:guest@localhost:5672/" -DotEnv $DotEnv
    RABBITMQ_EXCHANGE = Resolve-ConfigValue -Name "RABBITMQ_EXCHANGE" -Default "kaiops.events" -DotEnv $DotEnv
    RABBITMQ_QUEUE_PREFIX = Resolve-ConfigValue -Name "RABBITMQ_QUEUE_PREFIX" -Default "kaiops" -DotEnv $DotEnv
    DATABASE_ENABLED = Resolve-ConfigValue -Name "DATABASE_ENABLED" -Default "true" -DotEnv $DotEnv
    DB = Resolve-ConfigValue -Name "DB" -Default "mysql" -DotEnv $DotEnv
    DB_HOST = Resolve-ConfigValue -Name "DB_HOST" -Default "localhost" -DotEnv $DotEnv
    DB_PORT = Resolve-ConfigValue -Name "DB_PORT" -Default "3306" -DotEnv $DotEnv
    DB_USER = Resolve-ConfigValue -Name "DB_USER" -Default "kaiops" -DotEnv $DotEnv
    DB_PASSWORD = Resolve-ConfigValue -Name "DB_PASSWORD" -Default "kaiops" -DotEnv $DotEnv
    DB_DATABASE = Resolve-ConfigValue -Name "DB_DATABASE" -Default "kaiops" -DotEnv $DotEnv
    JWT_SECRET_KEY = Resolve-ConfigValue -Name "JWT_SECRET_KEY" -Default "kaiops-local-demo-secret-key-change-me" -DotEnv $DotEnv
    ADMIN_USER_PASSWORD = Resolve-ConfigValue -Name "ADMIN_USER_PASSWORD" -Default "Admin@123456" -DotEnv $DotEnv
    EXECUTIVE_USER_PASSWORD = Resolve-ConfigValue -Name "EXECUTIVE_USER_PASSWORD" -Default "Executive@123456" -DotEnv $DotEnv
    L3_USER_PASSWORD = Resolve-ConfigValue -Name "L3_USER_PASSWORD" -Default "L3Engineer@123456" -DotEnv $DotEnv
    L2_USER_PASSWORD = Resolve-ConfigValue -Name "L2_USER_PASSWORD" -Default "L2Engineer@123456" -DotEnv $DotEnv
    L1_USER_PASSWORD = Resolve-ConfigValue -Name "L1_USER_PASSWORD" -Default "L1Operator@123456" -DotEnv $DotEnv
    OPENAI_API_KEY = Resolve-ConfigValue -Name "OPENAI_API_KEY" -Default "" -DotEnv $DotEnv
    OPENAI_GPT5_MODEL = Resolve-ConfigValue -Name "OPENAI_GPT5_MODEL" -Default "gpt-5" -DotEnv $DotEnv
    OPENAI_GPT4O_MODEL = Resolve-ConfigValue -Name "OPENAI_GPT4O_MODEL" -Default "gpt-4o" -DotEnv $DotEnv
}

$RunId = Get-Date -Format "yyyyMMdd-HHmmss"
$LogRoot = Join-Path $RepoRoot "logs\local"
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

Stop-ProcessByPorts -Ports @(8001, 8004, 8007, 8010, 8501)

function Start-KaiMSWindow {
    param(
        [string]$Title,
        [string]$Command
    )

    $EscapedRepoRoot = $RepoRoot.Replace("'", "''")
    $EscapedPythonPath = $PythonPath.Replace("'", "''")
    $EscapedTitle = $Title.Replace("'", "''")
    $ServiceSlug = ($Title -replace "[^A-Za-z0-9._-]+", "-").Trim("-").ToLower()
    if ([string]::IsNullOrWhiteSpace($ServiceSlug)) {
        $ServiceSlug = "service"
    }
    $LogFile = Join-Path $LogRoot "$RunId-$ServiceSlug.log"
    $EscapedLogFile = $LogFile.Replace("'", "''")
    $EscapedKafkaEnabled = $Config.KAFKA_ENABLED.Replace("'", "''")
    $EscapedEventBusProvider = $Config.EVENT_BUS_PROVIDER.Replace("'", "''")
    $EscapedMessageBusDynamicRouting = $Config.MESSAGE_BUS_DYNAMIC_ROUTING.Replace("'", "''")
    $EscapedMessageBusStreamThreshold = $Config.MESSAGE_BUS_STREAM_THRESHOLD.Replace("'", "''")
    $EscapedMessageBusDefaultProvider = $Config.MESSAGE_BUS_DEFAULT_PROVIDER.Replace("'", "''")
    $EscapedMessageBusWorkerCount = $Config.MESSAGE_BUS_WORKER_COUNT.Replace("'", "''")
    $EscapedRabbitMqUrl = $Config.RABBITMQ_URL.Replace("'", "''")
    $EscapedRabbitMqExchange = $Config.RABBITMQ_EXCHANGE.Replace("'", "''")
    $EscapedRabbitMqQueuePrefix = $Config.RABBITMQ_QUEUE_PREFIX.Replace("'", "''")
    $EscapedDatabaseEnabled = $Config.DATABASE_ENABLED.Replace("'", "''")
    $EscapedDb = $Config.DB.Replace("'", "''")
    $EscapedDbHost = $Config.DB_HOST.Replace("'", "''")
    $EscapedDbPort = $Config.DB_PORT.Replace("'", "''")
    $EscapedDbUser = $Config.DB_USER.Replace("'", "''")
    $EscapedDbPassword = $Config.DB_PASSWORD.Replace("'", "''")
    $EscapedDbDatabase = $Config.DB_DATABASE.Replace("'", "''")
    $EscapedJwt = $Config.JWT_SECRET_KEY.Replace("'", "''")
    $EscapedAdminPassword = $Config.ADMIN_USER_PASSWORD.Replace("'", "''")
    $EscapedExecutivePassword = $Config.EXECUTIVE_USER_PASSWORD.Replace("'", "''")
    $EscapedL3Password = $Config.L3_USER_PASSWORD.Replace("'", "''")
    $EscapedL2Password = $Config.L2_USER_PASSWORD.Replace("'", "''")
    $EscapedL1Password = $Config.L1_USER_PASSWORD.Replace("'", "''")
    $EscapedOpenAiApiKey = $Config.OPENAI_API_KEY.Replace("'", "''")
    $EscapedOpenAiGpt5Model = $Config.OPENAI_GPT5_MODEL.Replace("'", "''")
    $EscapedOpenAiGpt4oModel = $Config.OPENAI_GPT4O_MODEL.Replace("'", "''")
    $Bootstrap = @"
Set-Location -LiteralPath '$EscapedRepoRoot'
    `$ErrorActionPreference = 'Continue'
`$env:PYTHONPATH = '$EscapedPythonPath'
`$env:KAFKA_ENABLED = '$EscapedKafkaEnabled'
`$env:EVENT_BUS_PROVIDER = '$EscapedEventBusProvider'
`$env:MESSAGE_BUS_DYNAMIC_ROUTING = '$EscapedMessageBusDynamicRouting'
`$env:MESSAGE_BUS_STREAM_THRESHOLD = '$EscapedMessageBusStreamThreshold'
`$env:MESSAGE_BUS_DEFAULT_PROVIDER = '$EscapedMessageBusDefaultProvider'
`$env:MESSAGE_BUS_WORKER_COUNT = '$EscapedMessageBusWorkerCount'
`$env:RABBITMQ_URL = '$EscapedRabbitMqUrl'
`$env:RABBITMQ_EXCHANGE = '$EscapedRabbitMqExchange'
`$env:RABBITMQ_QUEUE_PREFIX = '$EscapedRabbitMqQueuePrefix'
`$env:DATABASE_ENABLED = '$EscapedDatabaseEnabled'
`$env:DB = '$EscapedDb'
`$env:DB_HOST = '$EscapedDbHost'
`$env:DB_PORT = '$EscapedDbPort'
`$env:DB_USER = '$EscapedDbUser'
`$env:DB_PASSWORD = '$EscapedDbPassword'
`$env:DB_DATABASE = '$EscapedDbDatabase'
`$env:JWT_SECRET_KEY = '$EscapedJwt'
`$env:ADMIN_USER_PASSWORD = '$EscapedAdminPassword'
`$env:EXECUTIVE_USER_PASSWORD = '$EscapedExecutivePassword'
`$env:L3_USER_PASSWORD = '$EscapedL3Password'
`$env:L2_USER_PASSWORD = '$EscapedL2Password'
`$env:L1_USER_PASSWORD = '$EscapedL1Password'
`$env:OPENAI_API_KEY = '$EscapedOpenAiApiKey'
`$env:OPENAI_GPT5_MODEL = '$EscapedOpenAiGpt5Model'
`$env:OPENAI_GPT4O_MODEL = '$EscapedOpenAiGpt4oModel'
`$LogFile = '$EscapedLogFile'
`$env:KAIMS_LOG_FILE = `$LogFile
`$Host.UI.RawUI.WindowTitle = '$EscapedTitle'
Write-Host "Logging to `$LogFile"
"=== KaiMS service log start $(Get-Date -Format o) ===" | Out-File -FilePath `$LogFile -Append -Encoding utf8
& {
$Command
} *>&1 | Tee-Object -FilePath `$LogFile -Append
"@
    $Encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Bootstrap))

    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $Encoded)
}

function Test-UrlReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSeconds = 15
    )

    $Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($Stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3 | Out-Null
            return $true
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }

    return $false
}

Start-KaiMSWindow `
    -Title "KaiMS monitoring-adapter :8001" `
    -Command "& '$Python' -m uvicorn app:app --host 127.0.0.1 --port 8001 --app-dir services/monitoring-adapter"

Start-KaiMSWindow `
    -Title "KaiMS approval-service :8007" `
    -Command "& '$Python' -m uvicorn app:app --host 127.0.0.1 --port 8007 --app-dir services/approval-service"

Start-KaiMSWindow `
    -Title "KaiMS context-agent :8004" `
    -Command "& '$Python' -m uvicorn app:app --host 127.0.0.1 --port 8004 --app-dir services/context-agent"

Start-KaiMSWindow `
    -Title "KaiMS api-gateway :8010" `
    -Command "`$env:MONITORING_ADAPTER_URL = 'http://localhost:8001'; `$env:APPROVAL_SERVICE_URL = 'http://localhost:8007'; `$env:CONTEXT_AGENT_URL = 'http://localhost:8004'; & '$Python' -m uvicorn app:app --host 127.0.0.1 --port 8010 --app-dir services/api-gateway"

if (-not $NoUi) {
    $UiDb = $Config.DB.Replace("'", "''")
    $UiDbHost = $Config.DB_HOST.Replace("'", "''")
    $UiDbPort = $Config.DB_PORT.Replace("'", "''")
    $UiDbUser = $Config.DB_USER.Replace("'", "''")
    $UiDbPassword = $Config.DB_PASSWORD.Replace("'", "''")
    $UiDbDatabase = $Config.DB_DATABASE.Replace("'", "''")
    $UiJwt = $Config.JWT_SECRET_KEY.Replace("'", "''")
    $UiAdminPassword = $Config.ADMIN_USER_PASSWORD.Replace("'", "''")
    $UiExecutivePassword = $Config.EXECUTIVE_USER_PASSWORD.Replace("'", "''")
    $UiL3Password = $Config.L3_USER_PASSWORD.Replace("'", "''")
    $UiL2Password = $Config.L2_USER_PASSWORD.Replace("'", "''")
    $UiL1Password = $Config.L1_USER_PASSWORD.Replace("'", "''")
    $UiCommand = @"
`$env:MONITORING_ADAPTER_URL="http://localhost:8001"
`$env:APPROVAL_SERVICE_URL="http://localhost:8007"
`$env:API_GATEWAY_URL="http://localhost:8010"
`$env:DB="$UiDb"
`$env:DB_HOST="$UiDbHost"
`$env:DB_PORT="$UiDbPort"
`$env:DB_USER="$UiDbUser"
`$env:DB_PASSWORD="$UiDbPassword"
`$env:DB_DATABASE="$UiDbDatabase"
`$env:JWT_SECRET_KEY="$UiJwt"
`$env:ADMIN_USER_PASSWORD="$UiAdminPassword"
`$env:EXECUTIVE_USER_PASSWORD="$UiExecutivePassword"
`$env:L3_USER_PASSWORD="$UiL3Password"
`$env:L2_USER_PASSWORD="$UiL2Password"
`$env:L1_USER_PASSWORD="$UiL1Password"
& '$Python' -m streamlit run services/ui/app.py
"@

    Start-KaiMSWindow -Title "KaiMS Streamlit UI :8501" -Command $UiCommand
}

Write-Host "Started KaiMS local services."
Write-Host "Monitoring adapter: http://localhost:8001"
Write-Host "Approval service:   http://localhost:8007"
Write-Host "Context agent:      http://localhost:8004"
Write-Host "API Gateway:        http://localhost:8010"
if (-not $NoUi) {
    Write-Host "Streamlit UI:       http://localhost:8501"
}
Write-Host "Logs directory:     $LogRoot"

$ReadinessTargets = @(
    @{ Name = "Monitoring adapter"; Url = "http://localhost:8001/healthz" },
    @{ Name = "Approval service"; Url = "http://localhost:8007/healthz" },
    @{ Name = "Context agent"; Url = "http://localhost:8004/healthz" },
    @{ Name = "API Gateway"; Url = "http://localhost:8010/healthz" }
)

if (-not $NoUi) {
    $ReadinessTargets += @{ Name = "Streamlit UI"; Url = "http://localhost:8501" }
}

Write-Host "Checking readiness..."
foreach ($Target in $ReadinessTargets) {
    $IsReady = Test-UrlReady -Url $Target.Url -TimeoutSeconds 20
    if ($IsReady) {
        Write-Host ("[OK]   {0}: {1}" -f $Target.Name, $Target.Url)
    }
    else {
        Write-Warning ("[FAIL] {0}: {1}" -f $Target.Name, $Target.Url)
    }
}
