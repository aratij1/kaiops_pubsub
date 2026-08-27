from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED = {
    "kind", "title", "tenant_scope", "services", "owner_team", "last_reviewed",
    "source_system", "source_ref", "review_status", "content_version", "created_at", "updated_at",
}
INCIDENT_REQUIRED = {"alert_id", "alert_name", "service", "environment", "observation_window", "incident_id"}
DEPLOYMENT_REQUIRED = {"deployment", "service", "environment", "change_window"}


def metadata(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or ":" not in line:
            break
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def classify(relative: str, suffix: str, meta: dict[str, str]) -> tuple[str, str, str]:
    if relative.startswith("execution/") and suffix == ".json":
        return "PRODUCTION_CURATED", "governed execution catalog; not indexed as RAG Markdown", "retained"
    if relative.startswith("_review/") and suffix == ".json":
        return "GENERATED_UNVERIFIED", "review draft JSON; excluded by Markdown indexer", "retained in non-production review store"
    if relative == "execution/README.md":
        return "OBSOLETE", "operator documentation is not a knowledge document", "quarantined"
    if relative in {"flows.md", "flows.json"}:
        return "GENERATED_UNVERIFIED", "generated flow catalog is explicitly excluded from matching", "quarantined" if suffix == ".md" else "retained non-indexed"
    if relative == "scenarios.txt":
        return "DEMO_ONLY", "scenario fixture is not a reviewed production document", "retained non-indexed"
    if suffix == ".md":
        return "GENERATED_UNVERIFIED", "tenant eligibility and complete provenance are not verified", "quarantined"
    return "MALFORMED", "unrecognized corpus artifact", "rejected"


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory and classify every RAG corpus artifact")
    parser.add_argument("--rag-root", default="backend/rag")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    root = Path(args.rag_root).resolve()
    rows: list[dict[str, object]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        meta = metadata(path) if path.suffix.lower() == ".md" else {}
        required = set(REQUIRED)
        kind = str(meta.get("kind") or "").lower()
        if relative.startswith("incidents/") or kind == "incident":
            required |= INCIDENT_REQUIRED
        if relative.startswith("deployments/") or kind == "deployment":
            required |= DEPLOYMENT_REQUIRED
        missing = sorted(key for key in required if not meta.get(key)) if path.suffix.lower() == ".md" else []
        classification, evidence, action = classify(relative, path.suffix.lower(), meta)
        rows.append({
            "path": relative,
            "classification": classification,
            "missing": missing,
            "provenance": "verified" if meta.get("source_system") and meta.get("source_ref") else "unverified",
            "tenant": meta.get("tenant_scope") or "missing",
            "deterministic_repair": not missing and classification in {"PRODUCTION_CURATED", "TENANT_CURATED"},
            "action": action,
            "evidence": evidence,
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row["classification"])
        counts[key] = counts.get(key, 0) + 1
    lines = [
        "# RAG corpus remediation report", "",
        "This inventory is generated deterministically from the pinned recovery corpus. Missing tenant, ownership, or provenance values are never inferred.", "",
        "## Summary", "",
        f"- Files inventoried: {len(rows)}",
        *[f"- {key}: {value}" for key, value in sorted(counts.items())],
        "", "## File dispositions", "",
        "| Current path | Classification | Missing metadata | Provenance | Tenant | Deterministic repair | Final action | Evidence | SHA-256 |",
        "|---|---|---|---|---|---:|---|---|---|",
    ]
    for row in rows:
        values = [
            f"`backend/rag/{row['path']}`", str(row["classification"]), ", ".join(row["missing"]) or "none",
            str(row["provenance"]), str(row["tenant"]), "yes" if row["deterministic_repair"] else "no",
            str(row["action"]), str(row["evidence"]), f"`{row['sha256']}`",
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(rows), "classifications": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
