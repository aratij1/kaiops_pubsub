# KaiOps on Azure Container Apps

This deployment preserves the currently proven service entry points while grouping them with `domain` tags. It does not claim that the Python processes have already been safely merged. Portable/on-premises Compose remains supported.

## Prerequisites

Before deployment, replace every `REPLACE` value and every `:latest` image tag
with an immutable release tag or digest. The workflow enforces this with:

```bash
python scripts/validate_aca_parameters.py
```

Use `--allow-placeholders` only for repository-level structural validation of
the checked-in template; production deliberately rejects that mode.

- Azure Container Registry and Key Vault in the target resource group
- MySQL reachable through the Key Vault `DATABASE_URL`
- Azure Service Bus topics/subscriptions matching the parameter file
- Azure Blob container and connection secret
- Entra ID application with Authorization Code + PKCE callbacks
- reachable OTLP collector endpoint

Replace every `REPLACE` value and pin immutable image digests or release tags. Do not deploy `latest` in production.

```powershell
az bicep build --file deploy/azure-container-apps/main.bicep
az deployment group what-if --resource-group <resource-group> --template-file deploy/azure-container-apps/main.bicep --parameters deploy/azure-container-apps/production.parameters.json
az deployment group create --name kaiops-<release> --resource-group <resource-group> --template-file deploy/azure-container-apps/main.bicep --parameters deploy/azure-container-apps/production.parameters.json
```

The user-assigned identity receives `AcrPull` and `Key Vault Secrets User`. No secret value is stored in Bicep or Container Apps environment variables; Container Apps resolves versionless Key Vault references.

## Revision rollout and rollback

Apps use multiple-revision mode with 100% traffic assigned to the latest revision. Verify health, traces, queue age, workflow recovery, and a non-production incident before production approval.

```powershell
az containerapp revision list --resource-group <resource-group> --name <app> --query "[].{name:name,active:properties.active,traffic:properties.trafficWeight,created:properties.createdTime}" -o table
az containerapp ingress traffic set --resource-group <resource-group> --name <app> --revision-weight <known-good-revision>=100
```

Rollback traffic first; do not delete the failed revision until evidence is captured. Database migrations must remain backward-compatible across both active revisions.

## Scaling safety

HTTP services keep at least one replica; the gateway keeps two. Queue workers scale on Service Bus backlog. Scale-to-zero is deliberately disabled for API, SSE, approval, orchestration, and remediation paths because cold start or persistent workflow connections can affect incident safety.

## Remaining environment-specific validation

The repository cannot create customer Entra registrations, production secrets, MySQL networking, Service Bus entities, or DNS certificates. Those external resources must pass `what-if`, provider authentication, recovery, load, and rollback tests before promotion.
