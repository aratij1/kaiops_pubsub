param(
    [Parameter(Mandatory = $true)]
    [string[]]$Targets,

    [string]$SshUser = "azureuser",
    [string]$SshPrivateKey = "",
    [string]$RemoteDir = "~/kaiops_pubsub",
    [string]$EnvFile = "config/env/.env.cloud.example",
    [string[]]$ComposeFiles = @("docker-compose.yml", "docker-compose.external-state.yml", "docker-compose.scale.yml"),
    [switch]$SkipBuild,
    [switch]$Recreate,
    [switch]$SkipHealthCheck,
    [switch]$NoStrictHostKeyChecking
)

$ErrorActionPreference = "Stop"

function Invoke-RequiredFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required file not found: $Path"
    }
}

function Get-SshArgs {
    $args = @()
    if ($SshPrivateKey) {
        Invoke-RequiredFile -Path $SshPrivateKey
        $args += @("-i", $SshPrivateKey)
    }
    if ($NoStrictHostKeyChecking) {
        $args += @("-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null")
    }
    return $args
}

function Invoke-Remote {
    param(
        [string]$Target,
        [string]$Command
    )
    $sshArgs = Get-SshArgs
    & ssh @sshArgs "$SshUser@$Target" $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Remote command failed on ${Target}: $Command"
    }
}

function Copy-Remote {
    param(
        [string]$Source,
        [string]$Target,
        [string]$Destination
    )
    $sshArgs = Get-SshArgs
    & scp @sshArgs $Source "$SshUser@$Target`:$Destination"
    if ($LASTEXITCODE -ne 0) {
        throw "Copy failed to ${Target}: $Source -> $Destination"
    }
}

Invoke-RequiredFile -Path $EnvFile
foreach ($composeFile in $ComposeFiles) {
    Invoke-RequiredFile -Path $composeFile
}

$archiveName = "kaiops-deploy-$((Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")).tar.gz"
$archivePath = Join-Path $env:TEMP $archiveName
$excludeArgs = @(
    "--exclude=.git",
    "--exclude=.venv",
    "--exclude=.tmp",
    "--exclude=.env",
    "--exclude=.env.*",
    "--exclude=node_modules",
    "--exclude=frontend/react/node_modules",
    "--exclude=frontend/react/dist",
    "--exclude=backend/rag/runbooks/stress-*",
    "--exclude=*.pyc",
    "--exclude=__pycache__"
)

Write-Host "Creating deployment archive $archivePath"
& tar -czf $archivePath @excludeArgs .
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create deployment archive."
}

$composeArgs = ($ComposeFiles | ForEach-Object { "-f $_" }) -join " "
$upArgs = "up -d"
if (-not $SkipBuild) {
    $upArgs += " --build"
}
if ($Recreate) {
    $upArgs += " --force-recreate"
}

foreach ($target in $Targets) {
    Write-Host "Deploying KaiOps to $target"

    Invoke-Remote -Target $target -Command "mkdir -p $RemoteDir"
    Copy-Remote -Source $archivePath -Target $target -Destination "$RemoteDir/$archiveName"
    Copy-Remote -Source $EnvFile -Target $target -Destination "$RemoteDir/.env.deploy"

    Invoke-Remote -Target $target -Command "cd $RemoteDir && tar -xzf $archiveName && cp .env.deploy .env"
    Invoke-Remote -Target $target -Command "docker compose version >/dev/null 2>&1 || (sudo apt-get update -y && sudo apt-get install -y docker-compose-plugin)"

    if ($Recreate) {
        Invoke-Remote -Target $target -Command "cd $RemoteDir && docker compose --env-file .env $composeArgs down || true"
    }

    Invoke-Remote -Target $target -Command "cd $RemoteDir && docker compose --env-file .env $composeArgs $upArgs"

    if (-not $SkipHealthCheck) {
        Invoke-Remote -Target $target -Command "sleep 20 && curl -fsS http://localhost:8010/healthz >/dev/null"
        Invoke-Remote -Target $target -Command "curl -fsS -I http://localhost:8501 >/dev/null"
    }

    Write-Host "Deployment completed on $target" -ForegroundColor Green
}

Remove-Item -LiteralPath $archivePath -Force
Write-Host "All target VM deployments completed." -ForegroundColor Green
