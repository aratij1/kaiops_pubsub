import asyncio
import json

from common.models import ApplicationRegistration
from common.monitoring_onboarding import RuleGenerationAgent, write_prometheus_artifacts
from monitoring_adapter.onboarding_pipelines import capabilities_catalog, run_new_rule_pipeline, NewRuleOnboardingRequest
from monitoring_adapter.existing_monitoring import get_provider_adapter, normalize_provider_name


def test_uptimerobot_native_payload_is_normalized_without_inventing_details() -> None:
    normalized = get_provider_adapter("uptimerobot").normalize_alert({
        "monitorID": "42",
        "monitorFriendlyName": "Public API",
        "monitorURL": "https://api.example.com/health",
        "alertType": "1",
        "alertTypeFriendlyName": "Down",
        "alertDetails": "HTTP 503",
        "httpStatusCode": "503",
        "alertDateTime": "1786400000",
    })

    assert normalize_provider_name("UptimeRobot") == "uptime_robot"
    assert normalized["alertName"] == "Public API Down"
    assert normalized["severity"] == "critical"
    assert normalized["labels"]["monitor_id"] == "42"
    assert normalized["environment"] == "unknown"


def test_raygun_native_payload_preserves_vendor_provenance() -> None:
    normalized = get_provider_adapter("raygun").normalize_alert({
        "event": "error_notification",
        "eventType": "NewErrorOccurred",
        "error": {"message": "Checkout failed", "url": "https://app.raygun.com/errors/1", "instance": {"tags": ["env:prod"]}},
        "application": {"name": "checkout-api", "url": "https://app.raygun.com/apps/1"},
    })

    assert normalized["application"] == "checkout-api"
    assert normalized["environment"] == "prod"
    assert normalized["alertName"] == "Checkout failed"
    assert normalized["labels"]["event_type"] == "NewErrorOccurred"


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
    assert any(rule.name == "checkout_api:availability:ratio" for rule in result.recording_rules)
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


def test_monitoring_adapter_capabilities_label_real_and_simulated_contracts() -> None:
    rows = {row["platform"]: row for row in capabilities_catalog()}

    assert rows["prometheus"]["contract_mode"] == "real"
    assert rows["prometheus"]["contract_status"] == "partial"
    assert rows["datadog"]["contract_mode"] == "simulated"
    assert rows["datadog"]["contract_status"] == "stub"


def test_new_rule_pipeline_includes_adapter_contract_on_generated_rules() -> None:
    payload = NewRuleOnboardingRequest.model_validate(
        {
            "project": {
                "project_name": "checkout-api",
                "environment": "prod",
                "criticality": "high",
                "monitoring_platforms": ["prometheus", "datadog"],
            },
            "target_platforms": ["prometheus", "datadog"],
            "monitoring_requirements": ["alert when checkout availability drops below 99 for 5m"],
        }
    )

    result = run_new_rule_pipeline(payload)
    rows = {row["platform"]: row for row in result["generated_rules"]}

    assert rows["prometheus"]["contract_mode"] == "real"
    assert rows["datadog"]["contract_mode"] == "simulated"


def test_new_rule_pipeline_maps_etl_data_quality_requirements_to_etl_metrics() -> None:
    payload = NewRuleOnboardingRequest.model_validate(
        {
            "project": {
                "project_name": "etl-orders-dq",
                "environment": "prod",
                "criticality": "high",
                "support_team": "data-platform",
                "business_owner": "data-platform",
                "technical_owner": "data-platform",
                "region": "us-east-1",
                "monitoring_platforms": ["prometheus"],
                "notification_platforms": ["slack"],
            },
            "target_platforms": ["prometheus"],
            "monitoring_requirements": [
                "Create a critical Prometheus alert when null customer ID ratio is above 20 percent for 5 minutes.",
                "Create a high Prometheus alert when rejected ETL rows are greater than zero.",
                "Create a warning Prometheus alert when ETL load latency is above 120 seconds.",
            ],
        }
    )

    result = run_new_rule_pipeline(payload)
    rules = {row["metric"]: row for row in result["generated_rules"]}

    assert result["status"] == "ready-for-approval"
    assert {
        "etl_null_customer_ratio",
        "etl_rejected_rows",
        "etl_load_latency_seconds",
    }.issubset(rules)
    assert rules["etl_rejected_rows"]["threshold"] == 0.0
