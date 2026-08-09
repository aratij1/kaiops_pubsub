from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceQuality:
    independent_sources: int
    direct_evidence: int
    contradictory: bool
    sufficiency: str
    confidence_ceiling: float
    reasons: tuple[str, ...]


_DIRECT_SIGNALS = {
    "stack_trace",
    "error_code",
    "metric_anomaly",
    "trace_error",
    "deployment_change",
    "code_finding",
    "alert_payload",
}

_SOURCE_FAMILIES = {
    "alert": "alerting",
    "alertmanager": "alerting",
    "prometheus": "metrics",
    "metric": "metrics",
    "metrics": "metrics",
    "telemetry": "metrics",
    "log": "logs",
    "logs": "logs",
    "opensearch": "logs",
    "elasticsearch": "logs",
    "ticket": "tickets",
    "jira": "tickets",
    "code": "code",
    "github": "code",
    "gitlab": "code",
}


def _source_family(value: Any) -> str:
    source = str(value or "unknown").strip().lower()
    return _SOURCE_FAMILIES.get(source, source)


def assess_evidence_quality(
    evidence: list[dict[str, Any]],
    *,
    accepted_ids: list[str],
    alternative_causes: list[Any] | None = None,
) -> EvidenceQuality:
    accepted = set(accepted_ids)
    rows = [row for row in evidence if str(row.get("evidence_id") or "") in accepted]
    # Connector aliases backed by the same underlying signal are one source,
    # not independent corroboration (for example Prometheus + telemetry).
    sources = {_source_family(row.get("source")) for row in rows}
    direct = sum(
        1
        for row in rows
        if _DIRECT_SIGNALS.intersection(str(signal).lower() for signal in row.get("diagnostic_signals", []))
        or row.get("signal_counts")
    )
    contradiction = any(
        bool(row.get("contradictory")) or str(row.get("stance") or "").lower() in {"contradicts", "conflicts"}
        for row in rows
    )
    alternatives = [item for item in (alternative_causes or []) if str(item or "").strip()]
    reasons: list[str] = []
    if not rows:
        reasons.append("No accepted evidence supports the causal claim.")
        return EvidenceQuality(0, 0, contradiction, "insufficient", 0.35, tuple(reasons))
    if len(sources) < 2:
        reasons.append("Only one independent evidence source supports the causal claim.")
    if not direct:
        reasons.append("No direct causal signal was identified in accepted evidence.")
    if contradiction:
        reasons.append("Accepted evidence contains a contradiction.")
    if len(alternatives) > 2 and direct < 2:
        reasons.append("Multiple viable hypotheses remain unresolved.")
    if contradiction:
        ceiling, sufficiency = 0.49, "conflicting"
    elif len(sources) >= 2 and direct >= 1:
        ceiling, sufficiency = 0.95, "sufficient"
    elif direct >= 1:
        ceiling, sufficiency = 0.69, "partial"
    else:
        ceiling, sufficiency = 0.55, "partial"
    return EvidenceQuality(len(sources), direct, contradiction, sufficiency, ceiling, tuple(reasons))


def remediation_quality_gate(
    remediation: dict[str, Any],
    *,
    rca_confidence: float,
    impact_confidence: float,
    risk: str,
    environment: str,
    fallback_used: bool,
) -> dict[str, Any]:
    validation = remediation.get("validation_queries") or remediation.get("validation_steps") or []
    rollback = remediation.get("rollback_plan") or remediation.get("rollback_steps") or []
    commands = remediation.get("commands") or []
    approval = str(remediation.get("approval_required") or "").strip().lower()
    destructive = bool(remediation.get("destructive")) or any(
        marker in str(command).lower()
        for command in commands
        for marker in ("delete ", "drop ", "truncate ", "rm -", "destroy", "failover")
    )
    blockers: list[str] = []
    if rca_confidence < 0.65:
        blockers.append("RCA confidence is below 0.65.")
    if impact_confidence < 0.55:
        blockers.append("Impact confidence is below 0.55.")
    if not validation:
        blockers.append("No validation checks are defined.")
    if commands and not rollback:
        blockers.append("Executable commands lack rollback or compensation guidance.")
    if fallback_used:
        blockers.append("A model fallback contributed to the recommendation.")
    mandatory = (
        destructive
        or risk in {"high", "critical"}
        or (environment.lower() in {"prod", "production"} and approval not in {"false", "none", "automatic"})
    )
    return {
        "trusted_for_auto_execution": not blockers and not mandatory and rca_confidence >= 0.85,
        "requires_human_review": bool(blockers) or mandatory,
        "mandatory_approval": mandatory,
        "destructive": destructive,
        "blockers": blockers,
        "validation_present": bool(validation),
        "rollback_present": bool(rollback),
    }
