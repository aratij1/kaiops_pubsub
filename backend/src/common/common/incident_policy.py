from __future__ import annotations

from dataclasses import dataclass

from common.models import AlertSeverity, IncidentCandidate, SeverityPolicyDecision

_RANK = {
    AlertSeverity.INFO: 0,
    AlertSeverity.WARNING: 1,
    AlertSeverity.HIGH: 2,
    AlertSeverity.CRITICAL: 3,
}
_BY_RANK = {value: key for key, value in _RANK.items()}


@dataclass(slots=True)
class IncidentSeverityPolicy:
    """Deterministic validation applied after AI discovery."""

    version: str = "incident-severity-policy-v1"

    def evaluate(
        self,
        candidate: IncidentCandidate,
        *,
        service_criticality: str = "medium",
    ) -> SeverityPolicyDecision:
        score = _RANK[candidate.recommended_severity]
        rules: list[str] = []
        environment = candidate.environment.lower()
        criticality = service_criticality.lower()
        impact_text = f"{candidate.technical_impact} {candidate.business_impact}".lower()
        urgency = candidate.urgency.lower()
        affected_users = candidate.affected_users.lower()
        scope = candidate.scope.lower()

        if environment not in {"prod", "production"}:
            score -= 1
            rules.append("non-production-deescalation")
        if criticality in {"critical", "tier-0", "tier-1"}:
            score += 1
            rules.append("critical-service-escalation")
        if any(token in impact_text for token in ("outage", "data loss", "security", "payments unavailable")):
            score = max(score, _RANK[AlertSeverity.CRITICAL])
            rules.append("critical-impact-floor")
        elif any(token in impact_text for token in ("degraded", "errors", "latency", "partial outage")):
            score = max(score, _RANK[AlertSeverity.HIGH])
            rules.append("material-impact-floor")
        if urgency in {"immediate", "urgent"}:
            score += 1
            rules.append("urgency-escalation")
        if affected_users in {"none", "internal-only"} and scope in {"single-instance", "single-pod"}:
            score -= 1
            rules.append("limited-scope-deescalation")
        if scope in {"multi-region", "organization-wide", "all-users"}:
            score += 1
            rules.append("broad-scope-escalation")

        final = _BY_RANK[max(0, min(3, score))]
        return SeverityPolicyDecision(
            recommended_severity=candidate.recommended_severity,
            final_severity=final,
            service_criticality=service_criticality,
            environment=candidate.environment,
            impact=candidate.business_impact or candidate.technical_impact,
            urgency=candidate.urgency,
            affected_users=candidate.affected_users,
            scope=candidate.scope,
            rules_fired=rules,
            policy_version=self.version,
        )
