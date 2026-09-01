# KaiMS Phase 9 Connector Model

## Contract

The Connector Hub provides one provider-neutral `ConnectorPlugin` protocol for credential validation, connection tests, resource discovery, health, metrics, logs, traces, changes, capability execution, execution validation, rollback, and capability discovery.

Connector metadata is served dynamically from the registry. Frontend code should consume this catalog instead of hardcoding provider behavior.

## Initial catalog

The catalog includes Prometheus, Grafana, Datadog, New Relic, Splunk, OpenSearch/Elastic, Azure Monitor, AWS CloudWatch, Google Cloud Monitoring, Kubernetes, SSH/Linux, Windows/PowerShell, Jenkins, GitHub, GitLab, Ansible, Terraform, ServiceNow, Jira, MySQL, PostgreSQL, Oracle, SQL Server, Kafka, and Airflow.

Catalog presence does not claim a live integration. Entries are currently `metadata_only` unless a certified adapter is registered. Unsupported operations fail with `connector_operation_unavailable`; they never return simulated success.

## Secret providers

Connections contain only `secret_ref`. The provider registry requires an explicit URI scheme:

- `env://` for local development
- `aws-sm://` for AWS Secrets Manager
- `azure-kv://` for Azure Key Vault
- `gcp-sm://` for Google Secret Manager
- `vault://` for HashiCorp Vault

Only the environment provider is active by default. Cloud and Vault clients must be injected using `ClientSecretProvider`; missing SDKs or clients fail closed. Connector catalog and API responses never return resolved secret values.

## API

- `GET /connectors`
- `GET /connectors/{connector_id}`
- `GET /connectors/{connector_id}/capabilities`

The service is exposed locally on port `8028`. Connection mutation and execution endpoints are intentionally deferred until persistence, authorization, auditing, rate limits, and certified adapters are bound end to end.

## Compatibility and rollback

The hub is additive and does not replace existing monitoring, cloud-operations, discovery, or remediation adapters. Those implementations will be wrapped incrementally. Rollback removes the service from Compose and the new package; existing flows remain unchanged.

## Remaining placeholders

All 25 catalog entries are metadata-only in this hub increment. Existing real provider paths elsewhere in KaiMS remain operational but are not yet registered as Connector Hub plugins. The next milestone should introduce the Capability Registry and adapt the first real read-only and remediation connectors without enabling unrestricted execution.

