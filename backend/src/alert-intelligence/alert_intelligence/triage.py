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
    _SECURITY = re.compile(r"\b(unauthori[sz]ed|credential|exfiltrat|malware|security)\b", re.I)
    _DATA = re.compile(r"\b(database|data loss|corrupt|replica|schema)\b", re.I)
    _PERFORMANCE = re.compile(r"\b(latency|slow|timeout|saturation|throttl)\b", re.I)

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

        labels = {str(key).lower(): str(value).strip() for key, value in alert.labels.items()}
        environment = alert.environment.strip().lower()
        criticality = labels.get("service_criticality", labels.get("criticality", "medium")).lower()
        affected_users_text = labels.get("affected_users", "0").replace(",", "")
        occurrence_text = labels.get("occurrence_count", labels.get("alert_frequency", "1"))
        try:
            affected_users = max(0, int(float(affected_users_text)))
        except ValueError:
            affected_users = 0
        try:
            occurrence_count = max(1, int(float(occurrence_text)))
        except ValueError:
            occurrence_count = 1

        rank = {TicketSeverity.P1: 1, TicketSeverity.P2: 2, TicketSeverity.P3: 3, TicketSeverity.P4: 4}

        def escalate(target: TicketSeverity, reason: str) -> None:
            nonlocal severity
            if rank[target] < rank[severity]:
                severity = target
            if reason not in rules:
                rules.append(reason)

        if not noise:
            if environment in {"prod", "production"} and criticality in {"high", "critical"}:
                escalate(TicketSeverity.P2, "production-critical-service")
            if affected_users >= 1000:
                escalate(TicketSeverity.P1, "large-user-impact")
            elif affected_users >= 100:
                escalate(TicketSeverity.P2, "material-user-impact")
            if occurrence_count >= 10:
                escalate(TicketSeverity.P2, "high-alert-frequency")
            elif occurrence_count >= 3 and severity == TicketSeverity.P4:
                escalate(TicketSeverity.P3, "repeated-alert")
            if self._SECURITY.search(text):
                security_severity = TicketSeverity.P1 if environment in {"prod", "production"} else TicketSeverity.P2
                escalate(security_severity, "security-impact")

        if self._SECURITY.search(text):
            category = "security"
        elif self._DATA.search(text):
            category = "data"
        elif self._PERFORMANCE.search(text):
            category = "performance"
        elif severity in {TicketSeverity.P1, TicketSeverity.P2}:
            category = "availability"
        else:
            category = "operations"
        subcategory = "noise" if noise else "service-alert"
        if category == "performance":
            subcategory = "latency-or-saturation"
        elif category == "data":
            subcategory = "database-or-integrity"
        elif category == "security":
            subcategory = "security-event"

        priority_by_severity = {
            TicketSeverity.P1: 100,
            TicketSeverity.P2: 75,
            TicketSeverity.P3: 50,
            TicketSeverity.P4: 25,
        }
        priority = priority_by_severity[severity]
        if environment not in {"prod", "production"}:
            priority = max(1, priority - 10)
            rules.append("non-production-priority-adjustment")
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
        configured_sla = labels.get("sla_minutes", "")
        try:
            sla_minutes = max(1, int(configured_sla)) if configured_sla else self.policy.sla_for(severity)
        except ValueError:
            sla_minutes = self.policy.sla_for(severity)
        if configured_sla:
            rules.append("configured-sla")
        rationale = (
            f"Deterministic policy {self.policy.version} fired: {', '.join(rules)}. "
            f"Factors: environment={environment or 'unknown'}, criticality={criticality}, "
            f"affected_users={affected_users}, occurrences={occurrence_count}, sla_minutes={sla_minutes}."
        )
        return CanonicalTicket(
            ticket_id=f"kai-{alert.alert_id}",
            source=alert.source,
            source_reference=alert.source_reference,
            title=alert.title,
            description=alert.description,
            category=category,
            subcategory=subcategory,
            severity=severity,
            priority=priority,
            status=TicketStatus.TRIAGED,
            affected_service=alert.affected_service,
            environment=alert.environment,
            customer_impact=(
                "potential customer impact"
                if severity in {TicketSeverity.P1, TicketSeverity.P2}
                else "not established"
            ),
            business_impact="urgent assessment required" if severity == TicketSeverity.P1 else "requires investigation",
            correlation_id=correlation_id,
            confidence=0.98 if rules[0] != "informational-default" else 0.85,
            evidence=evidence,
            created_at=created,
            updated_at=utc_now(),
            assigned_team=alert.labels.get("owner_team") or alert.labels.get("team") or self.policy.default_team,
            audit_metadata=AuditMetadata(
                tenant_id=tenant_id,
                rules_fired=rules,
                rationale=rationale,
                trace_id=alert.labels.get("trace_id"),
            ),
            noise=noise,
            false_positive=noise,
            sla_deadline=created + timedelta(minutes=sla_minutes),
            escalation_required=severity == TicketSeverity.P1,
        )
