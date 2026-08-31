from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-rag-metadata.py"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)


def _resolve_base_ref(raw: str) -> str | None:
    result = _run(["git", "rev-parse", "--verify", raw])
    if result.returncode == 0:
        return raw

    if raw.startswith("origin/"):
        short = raw.split("/", 1)[1]
        fetch = _run(["git", "fetch", "origin", f"{short}:{raw}"])
        if fetch.returncode == 0:
            verify = _run(["git", "rev-parse", "--verify", raw])
            if verify.returncode == 0:
                return raw

    return None


def _changed_rag_markdown(base_ref: str, rag_root: str) -> list[str]:
    diff = _run(["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD", "--", rag_root])
    if diff.returncode != 0:
        return []
    changed = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
    return [path for path in changed if path.lower().endswith(".md")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate metadata only for changed RAG markdown files")
    parser.add_argument("--rag-root", default="backend/rag", help="Path to rag root")
    parser.add_argument("--base-ref", default="origin/main", help="Git base ref for diff")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings too")
    args = parser.parse_args()

    base_ref = _resolve_base_ref(args.base_ref)
    if base_ref is None:
        print(f"Base ref '{args.base_ref}' unavailable; falling back to full corpus validation.")
        cmd = [sys.executable, str(VALIDATOR), "--rag-root", args.rag_root]
        if args.strict:
            cmd.append("--strict")
        completed = subprocess.run(cmd, cwd=ROOT)
        return completed.returncode

    changed = _changed_rag_markdown(base_ref, args.rag_root)
    if not changed:
        print("No changed RAG markdown files detected; skipping delta validation.")
        return 0

    print(f"Validating {len(changed)} changed RAG markdown files against {base_ref}...")
    cmd = [sys.executable, str(VALIDATOR), "--rag-root", args.rag_root, "--paths", *changed]
    if args.strict:
        cmd.append("--strict")
    completed = subprocess.run(cmd, cwd=ROOT)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
