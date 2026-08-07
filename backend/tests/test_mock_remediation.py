import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).parents[2] / "scripts" / "remediation" / "mock_restart_staging_worker.py"
SPEC = importlib.util.spec_from_file_location("mock_restart_staging_worker", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_mock_action_is_dry_run_and_validates_recovery() -> None:
    result = MODULE.execute(incident_id="i-1", target="staging-checkout-worker", dry_run=True)
    assert result["changed"] is False
    assert all(result["validation"].values())


def test_mock_action_rejects_production_targets() -> None:
    with pytest.raises(ValueError, match="staging"):
        MODULE.execute(incident_id="i-1", target="production-checkout-worker", dry_run=True)
