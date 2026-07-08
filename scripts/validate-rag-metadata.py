from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


INCIDENT_SEVERITIES = {"critical", "high", "warning", "info"}
KNOWN_SECTIONS = {"runbooks", "incidents", "changes", "dependencies", "deployments", "sops", "onboarding"}


@dataclass
class ValidationIssue:
    level: str
    path: Path
    message: str


def parse_metadata(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            break
        if ":" not in raw:
            break
        key, value = raw.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def section_for(path: Path, rag_root: Path) -> str:
    try:
        rel = path.relative_to(rag_root)
    except ValueError:
        return ""
    if not rel.parts:
        return ""
    return rel.parts[0].lower()


def normalize_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def required_keys_for(section: str) -> list[str]:
    if section == "runbooks":
        return [
            "kind",
            "title",
            "services",
            "owner_team",
            "last_reviewed",
            "source_system",
            "source_ref",
        ]
    if section == "incidents":
        return ["alert_id", "alert_name", "service", "severity", "alert_type"]
    if section == "changes":
        return ["kind", "title", "services", "deployment", "change_id"]
    if section == "dependencies":
        return ["kind", "title", "services", "dependencies"]
    if section == "deployments":
        return ["kind", "title", "services", "deployment"]
    if section == "sops":
        return ["kind", "title", "services", "owner_team", "last_reviewed", "source_system", "source_ref"]
    if section == "onboarding":
        return ["kind", "title", "services", "owner_team", "last_reviewed", "source_system", "source_ref"]
    return []


def expected_kind_for(section: str) -> str | None:
    if section == "dependencies":
        return "dependency"
    if section == "changes":
        return "change"
    if section == "runbooks":
        return "runbook"
    if section == "deployments":
        return "deployment"
    if section == "sops":
        return "sop"
    if section == "onboarding":
        return "onboarding"
    return None


def validate_file(path: Path, rag_root: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    section = section_for(path, rag_root)
    metadata = parse_metadata(path)

    if section not in KNOWN_SECTIONS:
        issues.append(ValidationIssue("warn", path, f"unknown rag section '{section}'"))
        return issues

    required_keys = required_keys_for(section)
    missing = [key for key in required_keys if not metadata.get(key, "").strip()]
    if missing:
        issues.append(ValidationIssue("error", path, f"missing required metadata keys: {', '.join(missing)}"))

    expected_kind = expected_kind_for(section)
    if expected_kind:
        actual_kind = metadata.get("kind", "").strip().lower()
        if actual_kind and actual_kind != expected_kind:
            issues.append(ValidationIssue("error", path, f"kind should be '{expected_kind}' but found '{actual_kind}'"))

    if section == "incidents":
        severity = metadata.get("severity", "").strip().lower()
        if severity and severity not in INCIDENT_SEVERITIES:
            issues.append(ValidationIssue("error", path, f"severity must be one of: {', '.join(sorted(INCIDENT_SEVERITIES))}"))
        alert_id = metadata.get("alert_id", "").strip()
        if alert_id and not re.match(r"^[A-Za-z0-9._-]+$", alert_id):
            issues.append(ValidationIssue("warn", path, "alert_id contains unusual characters"))

    services = metadata.get("services", "").strip()
    if section in {"runbooks", "changes", "dependencies"} and services:
        if not normalize_csv(services):
            issues.append(ValidationIssue("error", path, "services metadata is present but empty after parsing"))

    return issues


def validate_corpus(rag_root: Path, targets: list[Path] | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    files = sorted(targets) if targets is not None else sorted(rag_root.rglob("*.md"))
    for path in files:
        issues.extend(validate_file(path, rag_root))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate RAG markdown metadata headers")
    parser.add_argument("--rag-root", default="rag", help="Path to rag corpus root")
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="Optional list of markdown file paths to validate (delta mode)",
    )
    parser.add_argument("--strict", action="store_true", help="Fail on warnings in addition to errors")
    args = parser.parse_args()

    rag_root = Path(args.rag_root).resolve()
    if not rag_root.exists():
        print(f"RAG root not found: {rag_root}")
        return 2

    targets: list[Path] | None = None
    if args.paths:
        targets = []
        for raw in args.paths:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (Path.cwd() / candidate).resolve()
            if candidate.suffix.lower() != ".md":
                continue
            if candidate.exists():
                targets.append(candidate)
            else:
                print(f"[WARN] skipped missing path: {candidate}")

    issues = validate_corpus(rag_root, targets=targets)
    errors = [issue for issue in issues if issue.level == "error"]
    warnings = [issue for issue in issues if issue.level == "warn"]

    for issue in issues:
        print(f"[{issue.level.upper()}] {issue.path}: {issue.message}")

    scanned_count = len(targets) if targets is not None else len(list(rag_root.rglob("*.md")))
    print(f"Scanned {scanned_count} markdown files | errors={len(errors)} warnings={len(warnings)}")

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
