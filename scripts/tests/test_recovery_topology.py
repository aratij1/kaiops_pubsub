from pathlib import Path

from scripts.validate_recovery_topology import validate

ROOT = Path(__file__).resolve().parents[2]


def test_repository_has_one_canonical_production_baseline() -> None:
    assert validate(ROOT) == []


def test_gate_rejects_a_second_frontend_and_embedded_manifest_secret(tmp_path: Path) -> None:
    (tmp_path / "frontend/react").mkdir(parents=True)
    (tmp_path / "frontend/react/package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "frontend/react/package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "frontend/old").mkdir()
    (tmp_path / "frontend/old/package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "deploy/docker").mkdir(parents=True)
    (tmp_path / "deploy/docker/Dockerfile.ui").touch()
    (tmp_path / "deploy/docker/Dockerfile.service").touch()
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  ui:\n    build:\n      dockerfile: deploy/docker/Dockerfile.ui\n"
        "x-build:\n  dockerfile: deploy/docker/Dockerfile.service\n",
        encoding="utf-8",
    )
    (tmp_path / "k8s").mkdir()
    (tmp_path / "k8s/app.yaml").write_text("password: exposed-value\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/BRANCH_RECOVERY_REPORT.md").write_text(
        "recovery/kaims-consolidated-main 6e524173ad0c752272b6c53518e0cc8108bf820d", encoding="utf-8"
    )

    failures = validate(tmp_path)

    assert any("expected only" in failure for failure in failures)
    assert any("embedded credential" in failure for failure in failures)
