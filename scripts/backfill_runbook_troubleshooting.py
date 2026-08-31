from __future__ import annotations

import re
from pathlib import Path

RUNBOOK_DIR = Path("backend/rag/runbooks")

REQUIRED_SECTIONS: list[tuple[str, str]] = [
    (
        "## Purpose",
        "## Purpose\nClarify when this runbook should be used and what incident outcome it targets.",
    ),
    (
        "## Preconditions",
        "## Preconditions\n- Required access level and tooling\n- Any approvals required before taking action\n- Safety constraints for production changes",
    ),
    (
        "## Triage Signals",
        "## Triage Signals\n- Confirm impacted service and severity\n- Verify alert freshness and blast radius\n- Identify whether this is likely change-related",
    ),
    (
        "## Investigation Steps",
        "## Investigation Steps\n1. Capture current symptoms, metrics, and logs.\n2. Check recent deploy/change events and dependency health.\n3. Isolate probable fault domain before remediation.",
    ),
    (
        "## Troubleshooting Steps",
        "## Troubleshooting Steps\n1. Run the top 3 service-specific diagnostics for this alert.\n2. Compare current telemetry against known-good baseline.\n3. Confirm if issue is transient, recurring, or systemic.\n4. Decide: remediate now, escalate, or monitor with guardrails.",
    ),
    (
        "## Remediation Steps",
        "## Remediation Steps\n1. Apply the safest reversible action first.\n2. If unresolved, proceed to deeper corrective action.\n3. Record what changed and expected recovery signal.",
    ),
    (
        "## Validation",
        "## Validation\n- Alert state transitions to healthy/suppressed as expected\n- Key SLO/SLI metrics recover to threshold\n- No collateral degradation in dependent services",
    ),
    (
        "## Rollback",
        "## Rollback\n1. Revert the last remediation action if validation fails.\n2. Restore prior known-good configuration or release.",
    ),
    (
        "## Escalation",
        "## Escalation\n- Escalate to owner team if unresolved after first response cycle\n- Escalate immediately for data loss, security risk, or expanding blast radius",
    ),
    (
        "## Notes",
        "## Notes\n- Capture root cause hypothesis and final confirmed cause\n- Add follow-up prevention tasks and owners",
    ),
]


def _is_probably_binary(payload: bytes) -> bool:
    return b"\x00" in payload


def _skip_file(path: Path) -> bool:
    name = path.name.lower()
    return "coverage" in name


def _normalize_existing_sections(content: str) -> str:
    # Promote legacy heading to the canonical heading instead of adding duplicates.
    content = re.sub(r"^##\s+Remediation\s*$", "## Remediation Steps", content, flags=re.MULTILINE)

    # Remove duplicate generic remediation block when a runbook already has a custom remediation section.
    if content.count("## Remediation Steps") > 1:
        content = re.sub(
            r"\n## Remediation Steps\s*\n\s*1\. Apply the safest reversible action first\.\s*\n\s*"
            r"2\. If unresolved, proceed to deeper corrective action\.\s*\n\s*"
            r"3\. Record what changed and expected recovery signal\.\s*\n",
            "\n",
            content,
            count=1,
            flags=re.MULTILINE,
        )

    # Collapse excessive blank lines introduced by repeated edits.
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.rstrip() + "\n"


def main() -> None:
    updated = 0
    skipped = 0

    for path in sorted(RUNBOOK_DIR.glob("*.md")):
        if _skip_file(path):
            continue

        raw = path.read_bytes()
        if _is_probably_binary(raw):
            skipped += 1
            print(f"skip(binary): {path}")
            continue

        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped += 1
            print(f"skip(decode): {path}")
            continue

        if "kind: runbook" not in content.lower():
            continue

        normalized_content = _normalize_existing_sections(content)
        content_changed = normalized_content != content
        content = normalized_content

        additions: list[str] = []
        lowered = content.lower()
        for heading, block in REQUIRED_SECTIONS:
            if heading.lower() not in lowered:
                additions.append(block)

        if not additions and not content_changed:
            continue

        if additions:
            addition_text = "\n\n" + "\n\n".join(additions) + "\n"
            content = content.rstrip() + addition_text + "\n"
        path.write_text(content, encoding="utf-8")
        updated += 1
        print(f"updated: {path}")

    print(f"done: updated={updated} skipped={skipped}")


if __name__ == "__main__":
    main()
