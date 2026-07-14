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
$openAiApiKey = [Environment]::GetEnvironmentVariable('OPENAI_API_KEY')
$geminiApiKey = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY')
$groqApiKey = [Environment]::GetEnvironmentVariable('GROQ_API_KEY')

kubectl create secret generic $SecretName `
    --namespace $Namespace `
    --from-literal=DATABASE_URL="$databaseUrl" `
    --from-literal=OPENAI_API_KEY="$openAiApiKey" `
    --from-literal=GEMINI_API_KEY="$geminiApiKey" `
    --from-literal=GROQ_API_KEY="$groqApiKey" `
    --dry-run=client -o yaml | kubectl apply -f -