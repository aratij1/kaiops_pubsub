"""Generate or verify the Docker requirements projection from uv.lock."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "deploy" / "docker" / "requirements.service.txt"


def exported_requirements() -> bytes:
    with tempfile.TemporaryDirectory(prefix="kaiops-lock-") as directory:
        output = Path(directory) / "requirements.service.txt"
        subprocess.run(
            [
                "uv",
                "export",
                "--frozen",
                "--no-dev",
                "--no-emit-project",
                "--no-header",
                "--no-annotate",
                "--output-file",
                str(output),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return output.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="replace the checked-in projection")
    args = parser.parse_args()
    generated = exported_requirements()
    if args.write:
        REQUIREMENTS.write_bytes(generated)
        print(f"updated {REQUIREMENTS.relative_to(ROOT)} from uv.lock")
        return 0
    if not REQUIREMENTS.exists() or REQUIREMENTS.read_bytes() != generated:
        print("Docker requirements are stale; run: uv run python scripts/sync_locked_requirements.py --write")
        return 1
    print("Docker requirements match the frozen uv.lock projection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
