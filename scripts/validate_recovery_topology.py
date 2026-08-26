from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

CANONICAL_FRONTEND = Path("frontend/react/package.json")
FORBIDDEN_PRODUCTION_SECRET = re.compile(
    r"(?i)^\s*(?:password|secret|token|api[_-]?key|client[_-]?secret)\s*:\s*['\"]?[^$<{\s][^\s]*"
)


def _relative_files(root: Path, name: str) -> list[Path]:
    ignored = {"node_modules", "dist", ".git", ".venv", ".tmp", "test-results", "ingested_alerts"}
    matches: list[Path] = []
    for current, directories, files in os.walk(root):
        directories[:] = [directory for directory in directories if directory not in ignored]
        if name in files:
            matches.append((Path(current) / name).relative_to(root))
    return sorted(matches)


def _tracked_files(root: Path) -> set[Path] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=False
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return {Path(item) for item in result.stdout.decode("utf-8").split("\0") if item}


def validate(root: Path) -> list[str]:
    failures: list[str] = []
    tracked = _tracked_files(root)
    candidates = tracked if tracked is not None else set(_relative_files(root, "package.json"))
    package_files = sorted(path for path in candidates if path.name == "package.json")
    if package_files != [CANONICAL_FRONTEND]:
        failures.append(f"expected only {CANONICAL_FRONTEND}; found: {', '.join(map(str, package_files)) or 'none'}")

    obsolete_services = root / "services"
    services_are_owned = tracked is not None and any(path.parts and path.parts[0] == "services" for path in tracked)
    unversioned_fixture = tracked is None and not (root / ".git").exists()
    if obsolete_services.exists() and (services_are_owned or unversioned_fixture):
        failures.append("obsolete root services/ tree competes with canonical backend/ and ai-workbench/ owners")

    compose_path = root / "docker-compose.yml"
    compose = compose_path.read_text(encoding="utf-8") if compose_path.is_file() else ""
    if not compose:
        failures.append("docker-compose.yml is missing")
    if re.search(r"(?im)^\s{2}[^#\n]+:\s*$[\s\S]{0,400}?streamlit", compose):
        failures.append("Streamlit must not be configured as a production Compose UI")
    if "dockerfile: deploy/docker/Dockerfile.ui" not in compose:
        failures.append("production Compose UI does not use the canonical React image")
    if "dockerfile: deploy/docker/Dockerfile.service" not in compose:
        failures.append("production services do not use the canonical shared backend image")

    required_build_files = (
        "deploy/docker/Dockerfile.service",
        "deploy/docker/Dockerfile.ui",
        "frontend/react/package-lock.json",
    )
    for relative in required_build_files:
        if not (root / relative).is_file():
            failures.append(f"missing reproducible build input: {relative}")

    for manifest in (root / "k8s").glob("*.y*ml") if (root / "k8s").is_dir() else ():
        for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN_PRODUCTION_SECRET.search(line):
                failures.append(f"embedded credential-like value: {manifest.relative_to(root)}:{line_number}")

    recovery_report = root / "docs/BRANCH_RECOVERY_REPORT.md"
    report = recovery_report.read_text(encoding="utf-8") if recovery_report.is_file() else ""
    for required in ("recovery/kaims-consolidated-main", "6e524173ad0c752272b6c53518e0cc8108bf820d"):
        if required not in report:
            failures.append(f"recovery documentation does not identify {required}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject mixed KaiMS source and deployment baselines")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    failures = validate(parser.parse_args().root.resolve())
    if failures:
        print("Recovery topology: BLOCKED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Recovery topology: canonical ownership and deployment inputs verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
