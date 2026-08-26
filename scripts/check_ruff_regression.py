from __future__ import annotations

import argparse
import io
import json
import subprocess
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

CANONICAL_PYTHON_ROOTS = ("backend", "ai-workbench", "scripts")


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, cwd=cwd, capture_output=True, check=False)


def _ruff_counts(scan_root: Path, *, config: Path) -> Counter[tuple[str, str]]:
    targets = [str(scan_root / relative) for relative in CANONICAL_PYTHON_ROOTS if (scan_root / relative).exists()]
    result = _run(
        ["ruff", "check", *targets, "--config", str(config), "--output-format=json"],
        cwd=scan_root,
    )
    try:
        findings = json.loads(result.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Ruff did not return JSON: {stderr}") from exc
    counts: Counter[tuple[str, str]] = Counter()
    for finding in findings:
        filename = Path(str(finding["filename"])).resolve().relative_to(scan_root.resolve()).as_posix()
        counts[(filename, str(finding["code"]))] += 1
    return counts


def regressions(
    baseline: Counter[tuple[str, str]], current: Counter[tuple[str, str]]
) -> list[tuple[str, str, int, int]]:
    return sorted(
        (path, code, baseline.get((path, code), 0), count)
        for (path, code), count in current.items()
        if count > baseline.get((path, code), 0)
    )


def validate(root: Path, baseline_revision: str) -> tuple[int, int, list[tuple[str, str, int, int]]]:
    archive = _run(["git", "archive", "--format=tar", baseline_revision], cwd=root)
    if archive.returncode:
        raise RuntimeError(archive.stderr.decode("utf-8", errors="replace"))
    with tempfile.TemporaryDirectory(prefix="kaims-ruff-baseline-") as temporary:
        baseline_root = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
            bundle.extractall(baseline_root, filter="data")
        baseline_counts = _ruff_counts(baseline_root, config=root / "pyproject.toml")
    current_counts = _ruff_counts(root, config=root / "pyproject.toml")
    return sum(baseline_counts.values()), sum(current_counts.values()), regressions(baseline_counts, current_counts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when Ruff debt increases above the pinned recovery baseline")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    baseline_total, current_total, increases = validate(args.root.resolve(), args.baseline)
    if increases:
        print("Ruff recovery ratchet: BLOCKED")
        for path, code, before, after in increases:
            print(f"- {path} {code}: {before} -> {after}")
        return 1
    print(f"Ruff recovery ratchet: passed ({baseline_total} baseline findings; {current_total} current)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
