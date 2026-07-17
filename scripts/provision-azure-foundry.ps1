param(
    [Parameter(Mandatory = $true)][string]$SubscriptionId,
    [Parameter(Mandatory = $true)][string]$ResourceGroup,
    [string]$Location = "eastus",

    [string]$AksClusterName = "kaiops-aks",
    [string]$AcrName = "",

    [string]$ServiceBusNamespace = "kaiops-sb",
    [string]$ServiceBusTopic = "raw-alerts",
    [string]$ServiceBusSubscription = "alert-intelligence",

    [string]$OpenAIAccountName = "kaiops-openai",
    [string]$OpenAIEmbeddingsDeployment = "text-embedding-3-large",
    [string]$OpenAIEmbeddingsModel = "text-embedding-3-large",
    [string]$OpenAIEvaluationDeployment = "gpt-4.1-mini",
    [string]$OpenAIEvaluationModel = "gpt-4.1-mini",
    [bool]$CreateOpenAIDeployments = $false,

    [string]$ContentSafetyAccountName = "kaiops-cs",
    [string]$AppInsightsName = "kaiops-appinsights",

    [bool]$CreateAks = $true,
    [bool]$CreateAcr = $true,
    [bool]$CreateServiceBus = $true,
    [bool]$CreateOpenAI = $true,
    [bool]$CreateContentSafety = $true,
    [bool]$CreateAppInsights = $true,

    [bool]$GetAksCredentials = $true,
    [string]$OutputEnvFile = ".env.azure.foundry.generated",
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

function Invoke-AzJson {
    param([Parameter(Mandatory = $true)][string[]]$Args)

    if ($DryRun) {
        Write-Host "DRY RUN: az $($Args -join ' ')"
        return $null
    }

    $output = & az @Args --output json
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Args -join ' ')"
    }

    if ([string]::IsNullOrWhiteSpace($output)) {
        return $null
    }

    return $output | ConvertFrom-Json
}

function Invoke-Az {
    param([Parameter(Mandatory = $true)][string[]]$Args)

    if ($DryRun) {
        Write-Host "DRY RUN: az $($Args -join ' ')"
        return
    }

    & az @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Args -join ' ')"
    }
}

function Test-AzShow {
    param([Parameter(Mandatory = $true)][string[]]$Args)

    if ($DryRun) {
        return $false
    }

    try {
        $null = & az @Args --output none 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Set-IfEmpty {
    param(
        [AllowEmptyString()][string]$Value,
        [Parameter(Mandatory = $true)][string]$Fallback
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Fallback
    }
    return $Value
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not [System.IO.Path]::IsPathRooted($OutputEnvFile)) {
    $OutputEnvFile = Join-Path $RepoRoot $OutputEnvFile
}

$AcrName = Set-IfEmpty -Value $AcrName -Fallback ($ResourceGroup.ToLower() -replace "[^a-z0-9]", "")
if ($AcrName.Length -gt 50) {
    $AcrName = $AcrName.Substring(0, 50)
}

if (-not $DryRun) {
    Assert-Command -Name "az"
}

Invoke-Step -Name "Set subscription" -Action {
    Invoke-Az -Args @("account", "set", "--subscription", $SubscriptionId)
}

if (-not $DryRun) {
    Invoke-Step -Name "Validate Azure login" -Action {
        try {
            $null = az account show --output none
        }
        catch {
            throw "Azure CLI is not logged in. Run: az login"
        }
    }
}

Invoke-Step -Name "Create resource group" -Action {
    Invoke-Az -Args @("group", "create", "--name", $ResourceGroup, "--location", $Location)
}

if ($CreateAcr) {
    Invoke-Step -Name "Ensure Azure Container Registry" -Action {
        $exists = Test-AzShow -Args @("acr", "show", "--name", $AcrName, "--resource-group", $ResourceGroup)
        if ($exists) {
            Write-Host "ACR already exists: $AcrName"
        }
        else {
            Invoke-Az -Args @("acr", "create", "--name", $AcrName, "--resource-group", $ResourceGroup, "--location", $Location, "--sku", "Standard", "--admin-enabled", "false")
        }
    }
}

if ($CreateAks) {
    Invoke-Step -Name "Ensure AKS cluster" -Action {
        $exists = Test-AzShow -Args @("aks", "show", "--name", $AksClusterName, "--resource-group", $ResourceGroup)
        if ($exists) {
            Write-Host "AKS already exists: $AksClusterName"
        }
        else {
            $cmd = @("aks", "create", "--name", $AksClusterName, "--resource-group", $ResourceGroup, "--location", $Location, "--node-count", "2", "--enable-managed-identity", "--generate-ssh-keys")
            if ($CreateAcr -and -not [string]::IsNullOrWhiteSpace($AcrName)) {
                $cmd += @("--attach-acr", $AcrName)
            }
            Invoke-Az -Args $cmd
        }
    }
}

if ($GetAksCredentials -and -not [string]::IsNullOrWhiteSpace($AksClusterName)) {
    Invoke-Step -Name "Fetch AKS credentials" -Action {
        Invoke-Az -Args @("aks", "get-credentials", "--resource-group", $ResourceGroup, "--name", $AksClusterName, "--overwrite-existing")
    }
}

if ($CreateServiceBus) {
    Invoke-Step -Name "Ensure Service Bus namespace/topic/subscription" -Action {
        $nsExists = Test-AzShow -Args @("servicebus", "namespace", "show", "--resource-group", $ResourceGroup, "--name", $ServiceBusNamespace)
        if ($nsExists) {
            Write-Host "Service Bus namespace already exists: $ServiceBusNamespace"
        }
        else {
            Invoke-Az -Args @("servicebus", "namespace", "create", "--resource-group", $ResourceGroup, "--name", $ServiceBusNamespace, "--location", $Location, "--sku", "Standard")
        }

        $topicExists = Test-AzShow -Args @("servicebus", "topic", "show", "--resource-group", $ResourceGroup, "--namespace-name", $ServiceBusNamespace, "--name", $ServiceBusTopic)
        if (-not $topicExists) {
            Invoke-Az -Args @("servicebus", "topic", "create", "--resource-group", $ResourceGroup, "--namespace-name", $ServiceBusNamespace, "--name", $ServiceBusTopic)
        }

        $subExists = Test-AzShow -Args @("servicebus", "topic", "subscription", "show", "--resource-group", $ResourceGroup, "--namespace-name", $ServiceBusNamespace, "--topic-name", $ServiceBusTopic, "--name", $ServiceBusSubscription)
        if (-not $subExists) {
            Invoke-Az -Args @("servicebus", "topic", "subscription", "create", "--resource-group", $ResourceGroup, "--namespace-name", $ServiceBusNamespace, "--topic-name", $ServiceBusTopic, "--name", $ServiceBusSubscription)
        }
    }
}

if ($CreateOpenAI) {
    Invoke-Step -Name "Ensure Azure OpenAI account" -Action {
        $exists = Test-AzShow -Args @("cognitiveservices", "account", "show", "--resource-group", $ResourceGroup, "--name", $OpenAIAccountName)
        if ($exists) {
            Write-Host "Azure OpenAI account already exists: $OpenAIAccountName"
        }
        else {
            Invoke-Az -Args @("cognitiveservices", "account", "create", "--resource-group", $ResourceGroup, "--name", $OpenAIAccountName, "--location", $Location, "--kind", "OpenAI", "--sku", "S0", "--yes")
        }
    }

    if ($CreateOpenAIDeployments) {
        Invoke-Step -Name "Create Azure OpenAI model deployments" -Action {
            Invoke-Az -Args @("cognitiveservices", "account", "deployment", "create", "--resource-group", $ResourceGroup, "--name", $OpenAIAccountName, "--deployment-name", $OpenAIEmbeddingsDeployment, "--model-name", $OpenAIEmbeddingsModel, "--model-format", "OpenAI", "--model-version", "1", "--sku-name", "Standard", "--sku-capacity", "10")
            Invoke-Az -Args @("cognitiveservices", "account", "deployment", "create", "--resource-group", $ResourceGroup, "--name", $OpenAIAccountName, "--deployment-name", $OpenAIEvaluationDeployment, "--model-name", $OpenAIEvaluationModel, "--model-format", "OpenAI", "--model-version", "1", "--sku-name", "Standard", "--sku-capacity", "10")
        }
    }
}

if ($CreateContentSafety) {
    Invoke-Step -Name "Ensure Content Safety account" -Action {
        $exists = Test-AzShow -Args @("cognitiveservices", "account", "show", "--resource-group", $ResourceGroup, "--name", $ContentSafetyAccountName)
        if ($exists) {
            Write-Host "Content Safety account already exists: $ContentSafetyAccountName"
        }
        else {
            Invoke-Az -Args @("cognitiveservices", "account", "create", "--resource-group", $ResourceGroup, "--name", $ContentSafetyAccountName, "--location", $Location, "--kind", "ContentSafety", "--sku", "S0", "--yes")
        }
    }
}

if ($CreateAppInsights) {
    Invoke-Step -Name "Ensure Application Insights" -Action {
        $exists = Test-AzShow -Args @("monitor", "app-insights", "component", "show", "--app", $AppInsightsName, "--resource-group", $ResourceGroup)
        if ($exists) {
            Write-Host "Application Insights already exists: $AppInsightsName"
        }
        else {
            Invoke-Az -Args @("monitor", "app-insights", "component", "create", "--app", $AppInsightsName, "--location", $Location, "--resource-group", $ResourceGroup, "--application-type", "web")
        }
    }
}

Invoke-Step -Name "Generate environment output file" -Action {
    if ($DryRun) {
        Write-Host "DRY RUN: output file would be written to $OutputEnvFile"
        return
    }

    $serviceBusKeys = Invoke-AzJson -Args @("servicebus", "namespace", "authorization-rule", "keys", "list", "--resource-group", $ResourceGroup, "--namespace-name", $ServiceBusNamespace, "--name", "RootManageSharedAccessKey")
    $openAiEndpoint = "https://$OpenAIAccountName.openai.azure.com"
    $openAiKeys = Invoke-AzJson -Args @("cognitiveservices", "account", "keys", "list", "--resource-group", $ResourceGroup, "--name", $OpenAIAccountName)
    $contentSafetyKeys = Invoke-AzJson -Args @("cognitiveservices", "account", "keys", "list", "--resource-group", $ResourceGroup, "--name", $ContentSafetyAccountName)
    $contentSafetyEndpoint = "https://$ContentSafetyAccountName.cognitiveservices.azure.com"
    $appInsights = Invoke-AzJson -Args @("monitor", "app-insights", "component", "show", "--app", $AppInsightsName, "--resource-group", $ResourceGroup)

    $lines = @(
        "# Generated by scripts/provision-azure-foundry.ps1",
        "# Use this file with scripts/deploy-azure-foundry.ps1",
        "DATABASE_URL=",
        "AZURE_SERVICE_BUS_CONNECTION_STRING=$($serviceBusKeys.primaryConnectionString)",
        "AZURE_OPENAI_ENDPOINT=$openAiEndpoint",
        "AZURE_OPENAI_API_KEY=$($openAiKeys.key1)",
        "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=$OpenAIEmbeddingsDeployment",
        "AZURE_AI_EVALUATION_DEPLOYMENT=$OpenAIEvaluationDeployment",
        "AZURE_CONTENT_SAFETY_ENDPOINT=$contentSafetyEndpoint",
        "AZURE_CONTENT_SAFETY_API_KEY=$($contentSafetyKeys.key1)",
        "AZURE_MONITOR_CONNECTION_STRING=$($appInsights.connectionString)",
        "KAFKA_ENABLED=false",
        "EVENT_BUS_PROVIDER=azure-servicebus"
    )

    Set-Content -Path $OutputEnvFile -Value ($lines -join [Environment]::NewLine) -Encoding utf8
    Write-Host "Wrote environment file: $OutputEnvFile" -ForegroundColor Green
}

Invoke-Step -Name "Next step" -Action {
    Write-Host "Run deployment using generated env values:" -ForegroundColor Yellow
    Write-Host "  ./scripts/deploy-azure-foundry.ps1 -ResourceGroup $ResourceGroup -AksClusterName $AksClusterName"
}
