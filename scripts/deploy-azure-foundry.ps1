param(
    [string]$Namespace = "kaiops",
    [string]$SecretName = "kaiops-secrets",
    [string]$ResourceGroup,
    [string]$AksClusterName,
    [string]$AcrName,
    [string]$ImageTag = "",
    [switch]$BuildAndPushImage,
    [bool]$DisableAzureFeaturePatch = $false,
    [switch]$SkipRolloutChecks,
    [switch]$SkipAksCredentials,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$K8sDir = Join-Path $RepoRoot "k8s"
$CreateSecretScript = Join-Path $K8sDir "create-secret.ps1"
$Dockerfile = Join-Path $RepoRoot "deploy/docker/Dockerfile.service"

$BackendDeployments = @(
    "monitoring-adapter",
    "api-gateway",
    "alert-intelligence",
    "orchestrator",
    "context-agent",
    "model-router",
    "resolution-agent",
    "approval-service",
    "remediation-engine",
    "closure-service"
)

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

function Assert-EnvValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Environment variable '$Name' is required for Azure deployment."
    }
}

function Test-AzLoggedIn {
    try {
        $null = az account show --output none 2>$null
        return $true
    }
    catch {
        return $false
    }
}

if (-not $DryRun) {
    Assert-Command -Name "kubectl"
}

$requiresAzCli = $BuildAndPushImage -or ((-not $SkipAksCredentials) -and -not [string]::IsNullOrWhiteSpace($ResourceGroup) -and -not [string]::IsNullOrWhiteSpace($AksClusterName))
if ($requiresAzCli -or (-not $DryRun)) {
    Assert-Command -Name "az"
}

if ([string]::IsNullOrWhiteSpace($ImageTag)) {
    $ImageTag = (Get-Date -Format "yyyyMMddHHmmss")
}

if (-not (Test-Path $CreateSecretScript)) {
    throw "Missing script: $CreateSecretScript"
}

if ($BuildAndPushImage) {
    if ([string]::IsNullOrWhiteSpace($AcrName)) {
        throw "-AcrName is required when -BuildAndPushImage is used."
    }
    if (-not (Test-Path $Dockerfile)) {
        throw "Missing Dockerfile: $Dockerfile"
    }
}

if (-not $DryRun) {
    Invoke-Step -Name "Validate Azure login" -Action {
        if (-not (Test-AzLoggedIn)) {
            throw "Azure CLI is not logged in. Run: az login"
        }
    }
}
else {
    Invoke-Step -Name "Skip Azure login check (dry-run)" -Action {
        Write-Host "Dry-run mode does not require active Azure login."
    }
}

if (-not $SkipAksCredentials -and -not [string]::IsNullOrWhiteSpace($ResourceGroup) -and -not [string]::IsNullOrWhiteSpace($AksClusterName)) {
    Invoke-Step -Name "Fetch AKS credentials" -Action {
        $cmd = @("aks", "get-credentials", "--resource-group", $ResourceGroup, "--name", $AksClusterName, "--overwrite-existing")
        if ($DryRun) {
            Write-Host "DRY RUN: az $($cmd -join ' ')"
        }
        else {
            az @cmd
        }
    }
}

if (-not $DryRun) {
    Invoke-Step -Name "Validate required secret environment variables" -Action {
        Assert-EnvValue -Name "DATABASE_URL"
        Assert-EnvValue -Name "AZURE_SERVICE_BUS_CONNECTION_STRING"
        Assert-EnvValue -Name "AZURE_OPENAI_ENDPOINT"
        Assert-EnvValue -Name "AZURE_OPENAI_API_KEY"
        Assert-EnvValue -Name "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"
        Assert-EnvValue -Name "AZURE_AI_EVALUATION_DEPLOYMENT"
        Assert-EnvValue -Name "AZURE_CONTENT_SAFETY_ENDPOINT"
        Assert-EnvValue -Name "AZURE_CONTENT_SAFETY_API_KEY"
        Assert-EnvValue -Name "AZURE_MONITOR_CONNECTION_STRING"
    }
}
else {
    Invoke-Step -Name "Skip secret env validation (dry-run)" -Action {
        Write-Host "Dry-run mode does not validate secret environment variables."
    }
}

if ($BuildAndPushImage) {
    Invoke-Step -Name "Build and push service image to ACR" -Action {
        $imageRef = "$AcrName.azurecr.io/kaiops/service-bundle:$ImageTag"
        $buildCmd = @(
            "acr", "build",
            "--registry", $AcrName,
            "--image", $imageRef,
            "--file", $Dockerfile,
            $RepoRoot
        )

        if ($DryRun) {
            Write-Host "DRY RUN: az $($buildCmd -join ' ')"
        }
        else {
            az @buildCmd
        }

        foreach ($deployment in $BackendDeployments) {
            $setImageCmd = @("set", "image", "deployment/$deployment", "$deployment=$imageRef", "-n", $Namespace)
            if ($DryRun) {
                Write-Host "DRY RUN: kubectl $($setImageCmd -join ' ')"
            }
            else {
                kubectl @setImageCmd
            }
        }
    }
}

Invoke-Step -Name "Create or update Kubernetes secret" -Action {
    $secretCmd = @("-Namespace", $Namespace, "-SecretName", $SecretName)
    if ($DryRun) {
        Write-Host "DRY RUN: powershell -File $CreateSecretScript $($secretCmd -join ' ')"
        Write-Host "DRY RUN: secret script execution skipped"
    }
    else {
        & $CreateSecretScript @secretCmd
    }
}

Invoke-Step -Name "Apply Kubernetes manifests" -Action {
    $manifests = @("namespace.yaml", "configmap.yaml", "services.yaml", "hpa.yaml", "ingress.yaml", "networkpolicy.yaml")
    foreach ($manifest in $manifests) {
        $path = Join-Path $K8sDir $manifest
        if (-not (Test-Path $path)) {
            continue
        }

        if ($DryRun) {
            Write-Host "DRY RUN: kubectl apply -f $path"
        }
        else {
            kubectl apply -f $path
        }
    }
}

if (-not $DisableAzureFeaturePatch) {
    Invoke-Step -Name "Patch ConfigMap for Azure feature flags" -Action {
        $patchData = @{
            data = @{
                AZURE_SERVICE_BUS_ENABLED = "true"
                AZURE_CONTENT_SAFETY_ENABLED = "true"
                AZURE_OPENAI_EMBEDDINGS_ENABLED = "true"
                AZURE_AI_EVALUATION_ENABLED = "true"
                OBSERVABILITY_AZURE_MONITOR_ENABLED = "true"
                KAFKA_ENABLED = "false"
                EVENT_BUS_PROVIDER = "azure-service-bus"
            }
        }
        $patchJson = $patchData | ConvertTo-Json -Depth 8 -Compress
        if ($DryRun) {
            Write-Host "DRY RUN: kubectl patch configmap kaiops-config -n $Namespace --type merge --patch '$patchJson'"
        }
        else {
            kubectl patch configmap kaiops-config -n $Namespace --type merge --patch $patchJson
            kubectl rollout restart deployment -n $Namespace
        }
    }
}

if (-not $SkipRolloutChecks) {
    Invoke-Step -Name "Wait for deployment rollouts" -Action {
        foreach ($deployment in $BackendDeployments) {
            if ($DryRun) {
                Write-Host "DRY RUN: kubectl rollout status deployment/$deployment -n $Namespace --timeout=180s"
            }
            else {
                kubectl rollout status "deployment/$deployment" -n $Namespace --timeout=180s
            }
        }
    }
}

Invoke-Step -Name "Deployment summary" -Action {
    if ($DryRun) {
        Write-Host "Dry run completed successfully."
        return
    }

    kubectl get pods -n $Namespace
    Write-Host "\nAzure Foundry deployment flow completed." -ForegroundColor Green
}
