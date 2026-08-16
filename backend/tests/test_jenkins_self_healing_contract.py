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
