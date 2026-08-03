from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta

from common.incident_contracts import AuditMetadata, CanonicalAlert, CanonicalTicket, TicketSeverity, TicketStatus
from common.models import EvidenceReference, utc_now


@dataclass(frozen=True)
class TriagePolicy:
    version: str = "ticket-triage-v1"
    default_team: str = "service-operations"
    sla_minutes: dict[TicketSeverity, int] | None = None

    def sla_for(self, severity: TicketSeverity) -> int:
        values = self.sla_minutes or {
            TicketSeverity.P1: 15,
            TicketSeverity.P2: 60,
            TicketSeverity.P3: 480,
            TicketSeverity.P4: 1440,
        }
        return values[severity]


class DeterministicTicketTriage:
    """Rules-first ticket triage. It never invokes a model or executes actions."""

    _P1 = re.compile(r"\b(outage|data loss|security breach|all customers|complete failure)\b", re.I)
    _P2 = re.compile(r"\b(degraded|timeout|major|multiple customers|high error)\b", re.I)
    _NOISE = re.compile(r"\b(test alert|synthetic test|resolved automatically|heartbeat)\b", re.I)

    def __init__(self, policy: TriagePolicy | None = None) -> None:
        self.policy = policy or TriagePolicy()

    @staticmethod
    def correlation_key(alert: CanonicalAlert) -> str:
        stable = "|".join((alert.affected_service.lower(), alert.environment.lower(), alert.title.lower().strip()))
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]

    def triage(self, alert: CanonicalAlert, *, tenant_id: str = "default") -> CanonicalTicket:
        text = f"{alert.title} {alert.description}"
        rules: list[str] = []
        noise = bool(self._NOISE.search(text))
        if noise:
            severity = TicketSeverity.P4
            rules.append("noise-pattern")
        elif self._P1.search(text) or alert.observed_severity.lower() in {"critical", "p1"}:
            severity = TicketSeverity.P1
            rules.append("critical-impact")
        elif self._P2.search(text) or alert.observed_severity.lower() in {"high", "p2"}:
            severity = TicketSeverity.P2
            rules.append("major-degradation")
        elif alert.observed_severity.lower() in {"warning", "p3"}:
            severity = TicketSeverity.P3
            rules.append("warning-default")
        else:
            severity = TicketSeverity.P4
            rules.append("informational-default")

        priority = {TicketSeverity.P1: 100, TicketSeverity.P2: 75, TicketSeverity.P3: 50, TicketSeverity.P4: 25}[severity]
        created = alert.observed_at
        evidence = alert.evidence or [
            EvidenceReference(
                evidence_id=alert.alert_id,
                source=alert.source,
                uri=f"{alert.source}://{alert.source_reference}",
                summary=alert.title,
                observed_at=alert.observed_at,
            )
        ]
        correlation_id = alert.correlation_id or self.correlation_key(alert)
        rationale = f"Deterministic policy {self.policy.version} fired: {', '.join(rules)}."
        return CanonicalTicket(
            ticket_id=f"kai-{alert.alert_id}",
            source=alert.source,
            source_reference=alert.source_reference,
            title=alert.title,
            description=alert.description,
            category="availability" if severity in {TicketSeverity.P1, TicketSeverity.P2} else "operations",
            subcategory="noise" if noise else "service-alert",
            severity=severity,
            priority=priority,
            status=TicketStatus.TRIAGED,
            affected_service=alert.affected_service,
            environment=alert.environment,
            customer_impact="potential customer impact" if severity in {TicketSeverity.P1, TicketSeverity.P2} else "not established",
            business_impact="urgent assessment required" if severity == TicketSeverity.P1 else "requires investigation",
            correlation_id=correlation_id,
            confidence=0.98 if rules[0] != "informational-default" else 0.85,
            evidence=evidence,
            created_at=created,
            updated_at=utc_now(),
            assigned_team=alert.labels.get("team") or self.policy.default_team,
            audit_metadata=AuditMetadata(
                tenant_id=tenant_id,
                rules_fired=rules,
                rationale=rationale,
                trace_id=alert.labels.get("trace_id"),
            ),
            noise=noise,
            false_positive=noise,
            sla_deadline=created + timedelta(minutes=self.policy.sla_for(severity)),
            escalation_required=severity == TicketSeverity.P1,
        )

