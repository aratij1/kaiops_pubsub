import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("phase9_gate", ROOT / "scripts/validate_phase9_readiness.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_repository_passes_phase9_artifact_gate() -> None:
    assert MODULE.validate(ROOT) == []


def test_gate_reports_missing_artifacts(tmp_path: Path) -> None:
    failures = MODULE.validate(tmp_path)
    assert any("missing or empty deliverable" in item for item in failures)
