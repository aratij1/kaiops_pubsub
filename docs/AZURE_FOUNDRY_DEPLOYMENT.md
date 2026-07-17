# Azure Foundry Deployment Runbook

This runbook configures KaiOPS for Azure deployment with Azure Service Bus, Azure OpenAI, Azure Content Safety, and Azure Monitor.

## 0. One-command deployment script

Use the deployment orchestrator script to automate AKS credentials, secret creation, manifests, Azure feature flags, and rollout checks:

```powershell
./scripts/deploy-azure-foundry.ps1 `
	-ResourceGroup <aks-resource-group> `
	-AksClusterName <aks-cluster-name> `
	-Namespace kaiops
```

Optional image build and push to ACR:

```powershell
./scripts/deploy-azure-foundry.ps1 `
	-ResourceGroup <aks-resource-group> `
	-AksClusterName <aks-cluster-name> `
	-AcrName <acr-name> `
	-BuildAndPushImage
```

Dry-run preview (no secret validation, no cluster mutation):

```powershell
./scripts/deploy-azure-foundry.ps1 -DryRun
```

## 0.1 Provision Azure resources script

Provision core Azure resources and generate deployment environment values:

```powershell
./scripts/provision-azure-foundry.ps1 `
	-SubscriptionId <subscription-id> `
	-ResourceGroup <resource-group> `
	-Location eastus `
	-AksClusterName <aks-name> `
	-AcrName <acr-name>
```

This script can create:

- Resource Group
- AKS
- ACR
- Azure Service Bus namespace/topic/subscription
- Azure OpenAI account
- Azure AI Content Safety account
- Application Insights

It also writes `.env.azure.foundry.generated` containing:

- `AZURE_SERVICE_BUS_CONNECTION_STRING`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT`
- `AZURE_AI_EVALUATION_DEPLOYMENT`
- `AZURE_CONTENT_SAFETY_ENDPOINT`
- `AZURE_CONTENT_SAFETY_API_KEY`
- `AZURE_MONITOR_CONNECTION_STRING`

Then run deployment:

```powershell
./scripts/deploy-azure-foundry.ps1 `
	-ResourceGroup <resource-group> `
	-AksClusterName <aks-name>
```

## 0.2 Deploy directly to Azure VMs (SSH + Docker Compose)

Use this when you want to deploy on Ubuntu VMs instead of AKS.

```powershell
./scripts/deploy-to-azure-vm.ps1 `
	-Targets "20.193.131.47","20.69.233.125" `
	-SshUser azureuser `
	-SshPrivateKey "C:/path/to/private_key.pem" `
	-EnvFile .env.azure.foundry.generated `
	-StopExisting
```

Notes:

- The script installs Docker/Compose on target VM if missing.
- It uploads `docker-compose.yml` and env file to `~/kaiops_pubsub`.
- It starts stack with `docker compose up -d --build`.
- It verifies `http://<vm-ip>:8010/healthz` unless `-SkipHealthCheck` is set.

## 1. Required Azure resources

- Azure Kubernetes Service (AKS)
- Azure Container Registry (ACR)
- Azure Service Bus namespace, topic, and subscription
- Azure OpenAI (or Azure AI Foundry project with deployed models)
- Azure AI Content Safety resource
- Azure Monitor Application Insights connection string
- Azure Database for MySQL (or compatible DATABASE_URL target)

## 2. Required runtime settings

### ConfigMap flags

- AZURE_SERVICE_BUS_ENABLED=true
- AZURE_CONTENT_SAFETY_ENABLED=true
- AZURE_OPENAI_EMBEDDINGS_ENABLED=true
- AZURE_AI_EVALUATION_ENABLED=true
- OBSERVABILITY_AZURE_MONITOR_ENABLED=true

### Secret values

- DATABASE_URL
- AZURE_SERVICE_BUS_CONNECTION_STRING
- AZURE_OPENAI_ENDPOINT
- AZURE_OPENAI_API_KEY
- AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT
- AZURE_AI_EVALUATION_DEPLOYMENT
- AZURE_CONTENT_SAFETY_ENDPOINT
- AZURE_CONTENT_SAFETY_API_KEY
- AZURE_MONITOR_CONNECTION_STRING

## 3. Create or update Kubernetes secret

PowerShell example:

```powershell
$env:DATABASE_URL = "mysql+aiomysql://kaiops:<password>@<mysql-host>:3306/kaiops"
$env:AZURE_SERVICE_BUS_CONNECTION_STRING = "Endpoint=sb://<namespace>.servicebus.windows.net/..."
$env:AZURE_OPENAI_ENDPOINT = "https://<resource>.openai.azure.com"
$env:AZURE_OPENAI_API_KEY = "<key>"
$env:AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT = "text-embedding-3-large"
$env:AZURE_AI_EVALUATION_DEPLOYMENT = "gpt-4.1-mini"
$env:AZURE_CONTENT_SAFETY_ENDPOINT = "https://<content-safety>.cognitiveservices.azure.com"
$env:AZURE_CONTENT_SAFETY_API_KEY = "<key>"
$env:AZURE_MONITOR_CONNECTION_STRING = "InstrumentationKey=...;IngestionEndpoint=..."
./k8s/create-secret.ps1
```

## 4. Deploy manifests

```powershell
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/services.yaml
kubectl apply -f k8s/hpa.yaml
kubectl apply -f k8s/ingress.yaml
```

## 5. Post-deploy checks

```powershell
kubectl -n kaiops get pods
kubectl -n kaiops rollout status deployment/api-gateway
kubectl -n kaiops rollout status deployment/model-router
kubectl -n kaiops rollout status deployment/alert-intelligence
```

Health checks:

- GET /healthz on api-gateway
- POST /security/check verifies Azure Content Safety path when enabled
- Model-router response includes optional evaluation block when Azure evaluation is enabled

## 6. Foundry-specific notes

- Azure OpenAI endpoint and deployment names must match Foundry deployments exactly.
- Keep evaluation and embeddings on dedicated deployments to isolate cost and latency.
- Do not commit secrets to git; use Kubernetes secret, Key Vault, or CSI driver.
