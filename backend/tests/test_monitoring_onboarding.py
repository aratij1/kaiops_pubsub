import asyncio
import json

from common.models import ApplicationRegistration
from common.monitoring_onboarding import RuleGenerationAgent, write_prometheus_artifacts


def make_application() -> ApplicationRegistration:
    return ApplicationRegistration(
        tenant_id="tenant-a",
        name="checkout-api",
        owner_team="payments-sre",
        owner_email="payments@example.com",
        environment="prod",
        namespace="payments",
        region="us-east-1",
        technology="python-fastapi",
        metrics_endpoint="http://checkout-api.payments.svc.cluster.local:8000/metrics",
        labels={"security": "internal", "compliance": "pci", "workload_kind": "Deployment"},
    )


def test_rule_generation_creates_prometheus_artifacts_shape() -> None:
    application = make_application()
    discovery_payload = {
        "application_id": str(application.id),
        "tenant_id": application.tenant_id,
        "name": application.name,
        "environment": application.environment,
        "namespace": application.namespace,
        "technology": application.technology,
        "resource_kind": "deployment",
        "discovered_resources": [{"kind": "Deployment", "name": application.name}],
        "metrics_endpoint": application.metrics_endpoint,
        "labels": application.labels,
    }
    validation_payload = {
        "application_id": str(application.id),
        "tenant_id": application.tenant_id,
        "metrics_endpoint": application.metrics_endpoint,
        "metrics_available": True,
        "technology": application.technology,
        "exporter": "prometheus-client",
        "labels": application.labels,
        "metric_families": [
            "process_cpu_seconds_total",
            "process_resident_memory_bytes",
            "http_requests_total",
            "kube_pod_container_status_restarts_total",
        ],
        "sample_metrics": ["process_cpu_seconds_total 1"],
    }

    from common.models import ApplicationDiscoveryResult, MetricsValidationResult

    result = asyncio.run(
        RuleGenerationAgent().run(
            application,
            ApplicationDiscoveryResult.model_validate(discovery_payload),
            MetricsValidationResult.model_validate(validation_payload),
        )
    )

    assert result.scrape_config.job_name == "checkout-api"
    assert result.alert_rules
    assert any(rule.name == "checkout-api-target-down" for rule in result.alert_rules)
    assert any(rule.name == "checkout-api:availability:ratio" for rule in result.recording_rules)
    assert result.governance["decision"] in {"approved", "requires_approval"}


def test_write_prometheus_artifacts_writes_rule_and_target_files(tmp_path, monkeypatch) -> None:
    application = make_application()
    discovery_payload = {
        "application_id": str(application.id),
        "tenant_id": application.tenant_id,
        "name": application.name,
        "environment": application.environment,
        "namespace": application.namespace,
        "technology": application.technology,
        "resource_kind": "deployment",
        "discovered_resources": [{"kind": "Deployment", "name": application.name}],
        "metrics_endpoint": application.metrics_endpoint,
        "labels": application.labels,
    }
    validation_payload = {
        "application_id": str(application.id),
        "tenant_id": application.tenant_id,
        "metrics_endpoint": application.metrics_endpoint,
        "metrics_available": True,
        "technology": application.technology,
        "exporter": "prometheus-client",
        "labels": application.labels,
        "metric_families": ["process_cpu_seconds_total", "process_resident_memory_bytes"],
        "sample_metrics": ["process_cpu_seconds_total 1"],
    }

    from common import monitoring_onboarding
    from common.models import ApplicationDiscoveryResult, MetricsValidationResult

    monkeypatch.setattr(monitoring_onboarding, "onboarding_root", lambda: tmp_path)
    rules = asyncio.run(
        RuleGenerationAgent().run(
            application,
            ApplicationDiscoveryResult.model_validate(discovery_payload),
            MetricsValidationResult.model_validate(validation_payload),
        )
    )
    files, contents = write_prometheus_artifacts(application, rules)

    assert set(files) == {"alert_rules", "recording_rules", "scrape_config"}
    assert "groups:" in contents["alert_rules"]
    target_payload = json.loads(contents["scrape_config"])
    assert target_payload[0]["labels"]["job"] == "checkout-api"
    assert (tmp_path / "prometheus_rules" / "checkout-api-alerts.yml").exists()
    assert (tmp_path / "prometheus_targets" / "checkout-api.json").exists()