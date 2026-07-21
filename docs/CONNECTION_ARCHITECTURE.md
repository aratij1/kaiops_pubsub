# Standard Connection Architecture

KaiOps uses one central connection catalog for platform services and external application integrations:

- [backend/config/kaiops-connections.json](../backend/config/kaiops-connections.json)

The catalog is selected by:

```text
CONNECTION_CONFIG_PATH=backend/config/kaiops-connections.json
```

## What Belongs In The Central Catalog

The catalog has three parts:

| Section | Purpose |
| --- | --- |
| `connection_architecture` | Human-readable architecture mode and connection principles |
| `platform` | Shared KaiOps infrastructure endpoints: database, cache, message bus, vector store, observability |
| `external_applications` | Target systems KaiOps can inspect or remediate |

## External Application Connector Contract

Every external application should have a connector profile with:

| Field | Required | Notes |
| --- | --- | --- |
| `connector_id` | yes | Stable ID used in execution plans and audit |
| `system` | yes | Application/service name |
| `type` | yes | `api`, `kubernetes`, `database`, `ssh`, `jenkins`, etc. |
| `endpoint` or target fields | type-specific | API URL, cluster/namespace, host, job path |
| `environment` | recommended | `dev`, `qa`, `prod`, etc. |
| `owner_team` | recommended | Team accountable for the target system |
| `auth_method` | yes | How credentials are obtained |
| `secret_ref` | yes | Reference only; never store secret values here |
| `timeout_seconds` | yes | Per-call timeout |
| `retry` | yes | Max attempts and backoff |
| `health_check` | recommended | Preflight check before context/remediation |
| `allowed_operations` | yes | Operations this connector permits |

Example:

```json
{
  "connector_id": "payments-k8s",
  "system": "payments-api",
  "type": "kubernetes",
  "cluster": "prod-us-east-1",
  "namespace": "payments",
  "auth_method": "kubeconfig-service-account",
  "secret_ref": "vault://kaiops/prod/payments-kubeconfig",
  "timeout_seconds": 15,
  "retry": { "max_attempts": 2, "backoff_seconds": 3 },
  "health_check": { "type": "deployment", "name": "payments-api" },
  "allowed_operations": ["read_status", "rollback_deployment", "restart_pod", "verify_slo"]
}
```

## Runtime Flow

1. Alert service name is used as the connector key.
2. KaiOps loads `CONNECTION_CONFIG_PATH`.
3. Environment placeholders such as `${ENVIRONMENT:-local}` are expanded.
4. The connector is normalized with timeout, retry, health check, and allowed operation defaults.
5. The execution plan includes:
   - connection architecture
   - platform endpoints
   - selected connector
   - onboarding connectivity checks
   - playbook and command allowability
6. Remediation can execute only if the command operation is present in `allowed_operations` and policy/approval gates pass.

## Compatibility

Existing files remain supported:

- [backend/rag/execution/connectors.json](../backend/rag/execution/connectors.json)
- [backend/rag/execution/action_catalog.json](../backend/rag/execution/action_catalog.json)
- [backend/rag/execution/playbooks.json](../backend/rag/execution/playbooks.json)

The central catalog overrides or augments legacy connector entries. Action and playbook catalogs remain separate governance artifacts.

## Cloud Migration

During cloud migration, keep connector IDs and allowed operations stable. Change only:

- `CONNECTION_CONFIG_PATH`, if using a provider-specific catalog
- endpoint values
- `secret_ref` provider paths
- platform service URLs
- cloud provider/profile env values

This keeps alert processing, approval, audit, playbooks, and remediation behavior consistent across clouds.
