from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "backend" / "rag" / "execution" / "playbooks.json"


def playbook_checksum(playbook: dict[str, Any]) -> str:
    payload = {key: value for key, value in playbook.items() if key != "checksum_sha256"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Update or verify governed execution playbook checksums")
    parser.add_argument("--check", action="store_true", help="Fail if a stored checksum is stale")
    args = parser.parse_args()

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rows = catalog.get("playbooks") if isinstance(catalog.get("playbooks"), list) else []
    stale: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        expected = playbook_checksum(row)
        if row.get("checksum_sha256") != expected:
            stale.append(str(row.get("id") or "<missing-id>"))
            row["checksum_sha256"] = expected

    if args.check:
        if stale:
            print("Stale execution playbook checksums: " + ", ".join(stale))
            return 1
        print(f"Execution playbook checksums OK: {len(rows)}")
        return 0

    CATALOG_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated {len(stale)} execution playbook checksum(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
