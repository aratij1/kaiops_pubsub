import copy
import json
from pathlib import Path

from scripts.validate_jenkins_remediation import validate


ROOT = Path(__file__).resolve().parents[2]


def _inputs():
    catalog = json.loads((ROOT / "deploy/jenkins/application-resolution-catalog.json").read_text(encoding="utf-8"))
    pipeline = (ROOT / "deploy/jenkins/Jenkinsfile.auto-remediation").read_text(encoding="utf-8")
    return catalog, pipeline


def test_enterprise_self_healing_contract_is_complete() -> None:
    catalog, pipeline = _inputs()
    assert validate(catalog, pipeline) == []


def test_mutating_resolution_without_rollback_is_rejected() -> None:
    catalog, pipeline = _inputs()
    broken = copy.deepcopy(catalog)
    broken["resolutions"]["restart-workload"]["rollback_commands"] = []
    assert "restart-workload requires executable rollback_commands" in validate(broken, pipeline)


def test_unsafe_catalog_command_is_rejected() -> None:
    catalog, pipeline = _inputs()
    broken = copy.deepcopy(catalog)
    broken["resolutions"]["restart-workload"]["commands"] = ["kubectl delete namespace production"]
    errors = validate(broken, pipeline)
    assert any("unsafe commands command" in item for item in errors)


def test_pipeline_requires_rollback_capability() -> None:
    catalog, pipeline = _inputs()
    assert any("automatic rollback" in item for item in validate(catalog, pipeline.replace("Automatic rollback", "Recovery action")))


def test_temporal_owns_async_jenkins_reconciliation() -> None:
    activities = (
        ROOT / "backend/src/temporal-pilot/temporal_pilot/activities.py"
    ).read_text(encoding="utf-8")
    workflow = (
        ROOT / "backend/src/temporal-pilot/temporal_pilot/workflow.py"
    ).read_text(encoding="utf-8")

    assert '"stage": "dispatching"' in activities
    assert '"stage": "reconciling"' in activities
    assert '"dispatch_remediation_action"' in workflow
    assert '"reconcile_remediation_action"' in workflow
    assert "workflow.sleep" in workflow
    assert '"timeout_remediation_action"' in workflow


def test_jenkins_adapter_separates_dispatch_from_observation() -> None:
    plugins = (
        ROOT / "backend/src/remediation-engine/remediation_engine/plugins.py"
    ).read_text(encoding="utf-8")

    assert "async def dispatch(self, action: RemediationAction)" in plugins
    assert "async def observe(self, action: RemediationAction)" in plugins
    assert 'action.status = RemediationStatus.EXECUTOR_ACCEPTED' in plugins


def test_execution_contract_binds_approval_plan_and_target() -> None:
    contract = (
        ROOT / "backend/src/remediation-engine/remediation_engine/execution_contract.py"
    ).read_text(encoding="utf-8")

    assert 'CONTRACT_VERSION = "kaims.remediation.v3"' in contract
    assert '"approved_plan_digest"' in contract
    assert "verify_execution_contract" in contract


def test_compose_requires_a_healthy_execution_plane() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "jenkins: { condition: service_healthy }" in compose
    assert "temporal-pilot-worker: { condition: service_healthy }" in compose
    assert "http://127.0.0.1:8000/executors/readiness" in compose
