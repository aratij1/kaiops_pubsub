from __future__ import annotations

from connector_hub.contracts import ConnectorCategory as C, ConnectorMetadata, ConnectorPlugin, MetadataOnlyConnector


CONNECTOR_CATALOG = {
    "prometheus": ("Prometheus", [C.MONITORING], ["metrics.read", "health.read"]),
    "grafana": ("Grafana", [C.MONITORING], ["dashboards.read"]),
    "datadog": ("Datadog", [C.MONITORING], ["metrics.read", "logs.read", "traces.read"]),
    "new-relic": ("New Relic", [C.MONITORING], ["metrics.read", "logs.read", "traces.read"]),
    "splunk": ("Splunk", [C.MONITORING], ["logs.read"]),
    "opensearch-elastic": ("OpenSearch / Elastic", [C.MONITORING], ["logs.read"]),
    "azure-monitor": ("Azure Monitor", [C.MONITORING], ["metrics.read", "logs.read"]),
    "aws-cloudwatch": ("AWS CloudWatch", [C.MONITORING], ["metrics.read", "logs.read"]),
    "google-cloud-monitoring": ("Google Cloud Monitoring", [C.MONITORING], ["metrics.read", "logs.read"]),
    "kubernetes": ("Kubernetes", [C.DIAGNOSTIC, C.REMEDIATION], ["resources.discover", "health.read", "kubernetes.restart_workload"]),
    "ssh-linux": ("SSH / Linux", [C.DIAGNOSTIC, C.REMEDIATION], ["health.read", "linux.restart_service"]),
    "windows-powershell": ("Windows / PowerShell", [C.DIAGNOSTIC, C.REMEDIATION], ["health.read", "windows.restart_service"]),
    "jenkins": ("Jenkins", [C.SOURCE_CICD, C.CHANGE_INTELLIGENCE, C.REMEDIATION], ["changes.read", "jenkins.rollback_deployment"]),
    "github": ("GitHub", [C.SOURCE_CICD, C.CHANGE_INTELLIGENCE], ["changes.read"]),
    "gitlab": ("GitLab", [C.SOURCE_CICD, C.CHANGE_INTELLIGENCE], ["changes.read"]),
    "ansible": ("Ansible", [C.REMEDIATION], ["ansible.run_playbook"]),
    "terraform": ("Terraform", [C.CHANGE_INTELLIGENCE, C.REMEDIATION], ["changes.read", "terraform.rollback"]),
    "servicenow": ("ServiceNow", [C.ITSM, C.CHANGE_INTELLIGENCE], ["incidents.read", "changes.read"]),
    "jira": ("Jira", [C.ITSM, C.CHANGE_INTELLIGENCE], ["incidents.read", "changes.read"]),
    "mysql": ("MySQL", [C.DIAGNOSTIC, C.REMEDIATION], ["database.collect_diagnostics", "database.kill_session"]),
    "postgresql": ("PostgreSQL", [C.DIAGNOSTIC, C.REMEDIATION], ["database.collect_diagnostics", "database.kill_session"]),
    "oracle": ("Oracle", [C.DIAGNOSTIC, C.REMEDIATION], ["database.collect_diagnostics"]),
    "sql-server": ("SQL Server", [C.DIAGNOSTIC, C.REMEDIATION], ["database.collect_diagnostics"]),
    "kafka": ("Kafka", [C.DIAGNOSTIC, C.REMEDIATION], ["health.read", "kafka.rebalance", "kafka.restart_consumer"]),
    "airflow": ("Airflow", [C.DIAGNOSTIC, C.REMEDIATION], ["health.read", "airflow.retry_task"]),
}


class ConnectorRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, ConnectorPlugin] = {}

    def register(self, plugin: ConnectorPlugin) -> None:
        connector_id = plugin.metadata.connector_id
        if connector_id in self._plugins:
            raise ValueError(f"connector {connector_id} is already registered")
        self._plugins[connector_id] = plugin

    def get(self, connector_id: str) -> ConnectorPlugin:
        try:
            return self._plugins[connector_id]
        except KeyError as exc:
            raise KeyError(f"unknown connector {connector_id}") from exc

    def list_metadata(self) -> list[ConnectorMetadata]:
        return sorted((plugin.metadata for plugin in self._plugins.values()), key=lambda row: row.display_name)


def default_connector_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    for connector_id, (name, categories, capabilities) in CONNECTOR_CATALOG.items():
        registry.register(MetadataOnlyConnector(ConnectorMetadata(
            connector_id=connector_id, display_name=name, categories=categories, capabilities=capabilities,
        )))
    return registry

