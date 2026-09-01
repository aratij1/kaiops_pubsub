param(
    [string]$Namespace = 'kaiops',
    [string]$SecretName = 'kaiops-secrets'
)

$ErrorActionPreference = 'Stop'

function Require-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name
    )

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Environment variable '$Name' is required."
    }
    return $value
}

$databaseUrl = Require-EnvValue -Name 'DATABASE_URL'
$azureServiceBusConnectionString = [Environment]::GetEnvironmentVariable('AZURE_SERVICE_BUS_CONNECTION_STRING')
$azureOpenAiEndpoint = [Environment]::GetEnvironmentVariable('AZURE_OPENAI_ENDPOINT')
$azureOpenAiApiKey = [Environment]::GetEnvironmentVariable('AZURE_OPENAI_API_KEY')
$azureOpenAiEmbeddingsDeployment = [Environment]::GetEnvironmentVariable('AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT')
$azureAiEvaluationDeployment = [Environment]::GetEnvironmentVariable('AZURE_AI_EVALUATION_DEPLOYMENT')
$azureContentSafetyEndpoint = [Environment]::GetEnvironmentVariable('AZURE_CONTENT_SAFETY_ENDPOINT')
$azureContentSafetyApiKey = [Environment]::GetEnvironmentVariable('AZURE_CONTENT_SAFETY_API_KEY')
$azureMonitorConnectionString = [Environment]::GetEnvironmentVariable('AZURE_MONITOR_CONNECTION_STRING')
$openAiApiKey = [Environment]::GetEnvironmentVariable('OPENAI_API_KEY')
$geminiApiKey = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY')
$groqApiKey = [Environment]::GetEnvironmentVariable('GROQ_API_KEY')

kubectl create secret generic $SecretName `
    --namespace $Namespace `
    --from-literal=DATABASE_URL="$databaseUrl" `
    --from-literal=AZURE_SERVICE_BUS_CONNECTION_STRING="$azureServiceBusConnectionString" `
    --from-literal=AZURE_OPENAI_ENDPOINT="$azureOpenAiEndpoint" `
    --from-literal=AZURE_OPENAI_API_KEY="$azureOpenAiApiKey" `
    --from-literal=AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT="$azureOpenAiEmbeddingsDeployment" `
    --from-literal=AZURE_AI_EVALUATION_DEPLOYMENT="$azureAiEvaluationDeployment" `
    --from-literal=AZURE_CONTENT_SAFETY_ENDPOINT="$azureContentSafetyEndpoint" `
    --from-literal=AZURE_CONTENT_SAFETY_API_KEY="$azureContentSafetyApiKey" `
    --from-literal=AZURE_MONITOR_CONNECTION_STRING="$azureMonitorConnectionString" `
    --from-literal=OPENAI_API_KEY="$openAiApiKey" `
    --from-literal=GEMINI_API_KEY="$geminiApiKey" `
    --from-literal=GROQ_API_KEY="$groqApiKey" `
    --dry-run=client -o yaml | kubectl apply -f -
