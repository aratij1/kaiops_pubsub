param(
    [Parameter(Mandatory = $true)][string[]]$Targets,
    [string]$SshUser = "azureuser",
    [string]$SshPrivateKey,
    [string]$RemoteDir = "~/kaiops_pubsub",
    [string]$EnvFile = ".env.azure.foundry.generated",
    [bool]$ForceAzureFlags = $true,
    [switch]$SkipBuild,
    [switch]$SkipHealthCheck,
    [switch]$StopExisting,
    [switch]$NoStrictHostKeyChecking,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    Write-Host "`n==> $Name" -ForegroundColor Cyan
    & $Action
}

function Assert-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

function New-SshOptions {
    $opts = @("-o", "BatchMode=yes")
    if ($NoStrictHostKeyChecking) {
        $opts += @("-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null")
    }
    if (-not [string]::IsNullOrWhiteSpace($SshPrivateKey)) {
        $opts += @("-i", $SshPrivateKey)
    }
    return $opts
}

function Invoke-Ssh {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$Command
    )

    $sshArgs = New-SshOptions
    $remote = "$SshUser@$Target"
    $sshCommandArgs = @() + $sshArgs + @($remote, $Command)

    if ($DryRun) {
        Write-Host "DRY RUN: ssh $($sshCommandArgs -join ' ')"
        return
    }

    & ssh @sshCommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "SSH command failed for target '$Target'."
    }
}

function Invoke-Scp {
    param(
        [Parameter(Mandatory = $true)][string]$LocalPath,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$RemotePath
    )

    $scpArgs = @()
    if ($NoStrictHostKeyChecking) {
        $scpArgs += @("-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null")
    }
    if (-not [string]::IsNullOrWhiteSpace($SshPrivateKey)) {
        $scpArgs += @("-i", $SshPrivateKey)
    }

    $remote = "${SshUser}@${Target}:$RemotePath"
    $scpCommandArgs = @() + $scpArgs + @($LocalPath, $remote)

    if ($DryRun) {
        Write-Host "DRY RUN: scp $($scpCommandArgs -join ' ')"
        return
    }

    & scp @scpCommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "SCP upload failed for target '$Target'."
    }
}

function Get-HealthUrl {
    param([Parameter(Mandatory = $true)][string]$Target)
    return "http://${Target}:8010/healthz"
}

function New-SourceArchive {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$ArchivePath
    )

    if (Test-Path $ArchivePath) {
        Remove-Item -LiteralPath $ArchivePath -Force
    }

    $excludeArgs = @(
        "--exclude=.git",
        "--exclude=.venv",
        "--exclude=logs",
        "--exclude=__pycache__",
        "--exclude=.pytest_cache",
        "--exclude=node_modules",
        "--exclude=*.pyc"
    )

    Push-Location $RepoRoot
    try {
        & tar -czf $ArchivePath @excludeArgs .
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create source archive with tar."
        }
    }
    finally {
        Pop-Location
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposePath = Join-Path $RepoRoot "docker-compose.yml"
$EnvPath = $EnvFile
if (-not [System.IO.Path]::IsPathRooted($EnvPath)) {
    $EnvPath = Join-Path $RepoRoot $EnvPath
}

Assert-Command -Name "ssh"
Assert-Command -Name "scp"

if (-not (Test-Path $ComposePath)) {
    throw "Missing docker-compose.yml at $ComposePath"
}

if (-not (Test-Path $EnvPath) -and -not $DryRun) {
    throw "Missing env file at $EnvPath"
}

if (-not (Test-Path $EnvPath) -and $DryRun) {
    Write-Host "Dry-run: env file not found at $EnvPath (skipping upload validation)." -ForegroundColor Yellow
}

if (-not [string]::IsNullOrWhiteSpace($SshPrivateKey) -and -not (Test-Path $SshPrivateKey)) {
    throw "SSH private key not found: $SshPrivateKey"
}

$sourceArchive = Join-Path $env:TEMP "kaiops-source-$(Get-Date -Format 'yyyyMMddHHmmss').tar.gz"
if (-not $DryRun) {
    Invoke-Step -Name "Create source archive" -Action {
        New-SourceArchive -RepoRoot $RepoRoot -ArchivePath $sourceArchive
    }
}
else {
    Write-Host "Dry-run: source archive creation skipped." -ForegroundColor Yellow
}

foreach ($target in $Targets) {
    Invoke-Step -Name "Prepare target $target" -Action {
                Invoke-Ssh -Target $target -Command "mkdir -p $RemoteDir"
                Invoke-Ssh -Target $target -Command "command -v docker >/dev/null 2>&1 || (curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $SshUser || true)"
                Invoke-Ssh -Target $target -Command "docker compose version >/dev/null 2>&1 || (sudo apt-get update -y && sudo apt-get install -y docker-compose-plugin)"
    }

    Invoke-Step -Name "Upload compose and env to $target" -Action {
        Invoke-Ssh -Target $target -Command "mkdir -p $RemoteDir"
        if ($DryRun) {
            Write-Host "DRY RUN: scp <source-archive> ${SshUser}@${target}:$RemoteDir/source.tar.gz"
            Write-Host "DRY RUN: ssh ${SshUser}@${target} 'cd $RemoteDir && tar -xzf source.tar.gz && rm -f source.tar.gz'"
        }
        else {
            Invoke-Scp -LocalPath $sourceArchive -Target $target -RemotePath "$RemoteDir/source.tar.gz"
            Invoke-Ssh -Target $target -Command "cd $RemoteDir && tar -xzf source.tar.gz && rm -f source.tar.gz"
        }
        Invoke-Scp -LocalPath $ComposePath -Target $target -RemotePath "$RemoteDir/docker-compose.yml"
        if (Test-Path $EnvPath) {
            Invoke-Scp -LocalPath $EnvPath -Target $target -RemotePath "$RemoteDir/.env"
        }
        elseif ($DryRun) {
            Write-Host "DRY RUN: scp <env-file> ${SshUser}@${target}:$RemoteDir/.env"
        }
    }

    if ($ForceAzureFlags) {
        Invoke-Step -Name "Force Azure runtime flags on $target" -Action {
            $commands = @(
                "cd $RemoteDir && (grep -q '^AZURE_SERVICE_BUS_ENABLED=' .env && sed -i 's/^AZURE_SERVICE_BUS_ENABLED=.*/AZURE_SERVICE_BUS_ENABLED=true/' .env || echo 'AZURE_SERVICE_BUS_ENABLED=true' >> .env)",
                "cd $RemoteDir && (grep -q '^AZURE_CONTENT_SAFETY_ENABLED=' .env && sed -i 's/^AZURE_CONTENT_SAFETY_ENABLED=.*/AZURE_CONTENT_SAFETY_ENABLED=true/' .env || echo 'AZURE_CONTENT_SAFETY_ENABLED=true' >> .env)",
                "cd $RemoteDir && (grep -q '^AZURE_OPENAI_EMBEDDINGS_ENABLED=' .env && sed -i 's/^AZURE_OPENAI_EMBEDDINGS_ENABLED=.*/AZURE_OPENAI_EMBEDDINGS_ENABLED=true/' .env || echo 'AZURE_OPENAI_EMBEDDINGS_ENABLED=true' >> .env)",
                "cd $RemoteDir && (grep -q '^AZURE_AI_EVALUATION_ENABLED=' .env && sed -i 's/^AZURE_AI_EVALUATION_ENABLED=.*/AZURE_AI_EVALUATION_ENABLED=true/' .env || echo 'AZURE_AI_EVALUATION_ENABLED=true' >> .env)",
                "cd $RemoteDir && (grep -q '^OBSERVABILITY_AZURE_MONITOR_ENABLED=' .env && sed -i 's/^OBSERVABILITY_AZURE_MONITOR_ENABLED=.*/OBSERVABILITY_AZURE_MONITOR_ENABLED=true/' .env || echo 'OBSERVABILITY_AZURE_MONITOR_ENABLED=true' >> .env)",
                "cd $RemoteDir && (grep -q '^KAFKA_ENABLED=' .env && sed -i 's/^KAFKA_ENABLED=.*/KAFKA_ENABLED=false/' .env || echo 'KAFKA_ENABLED=false' >> .env)",
                "cd $RemoteDir && (grep -q '^EVENT_BUS_PROVIDER=' .env && sed -i 's/^EVENT_BUS_PROVIDER=.*/EVENT_BUS_PROVIDER=azure-servicebus/' .env || echo 'EVENT_BUS_PROVIDER=azure-servicebus' >> .env)"
            )
            foreach ($command in $commands) {
                Invoke-Ssh -Target $target -Command $command
            }
        }
    }

    Invoke-Step -Name "Start containers on $target" -Action {
        $upCmd = if ($SkipBuild) { "cd $RemoteDir && docker compose --env-file .env up -d" } else { "cd $RemoteDir && docker compose --env-file .env up -d --build" }
        if ($StopExisting) {
            Invoke-Ssh -Target $target -Command "cd $RemoteDir && docker compose --env-file .env down || true"
        }
        Invoke-Ssh -Target $target -Command $upCmd
    }

    if (-not $SkipHealthCheck) {
        Invoke-Step -Name "Health check api-gateway on $target" -Action {
            $url = Get-HealthUrl -Target $target
            if ($DryRun) {
                Write-Host "DRY RUN: Invoke-WebRequest -Uri $url"
            }
            else {
                $maxAttempts = 20
                $delaySeconds = 8
                $success = $false
                for ($i = 1; $i -le $maxAttempts; $i++) {
                    try {
                        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 8
                        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                            $success = $true
                            Write-Host "Health check passed at $url"
                            break
                        }
                    }
                    catch {
                    }
                    Start-Sleep -Seconds $delaySeconds
                }

                if (-not $success) {
                    throw "Health check failed for $target at $url"
                }
            }
        }
    }
}

Write-Host "`nDeployment completed for targets: $($Targets -join ', ')" -ForegroundColor Green

if ((-not $DryRun) -and (Test-Path $sourceArchive)) {
    Remove-Item -LiteralPath $sourceArchive -Force
}
