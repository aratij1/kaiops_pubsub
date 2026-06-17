from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta

from common.embeddings import HashingEmbeddingModel, cosine_similarity
from common.models import Alert, AlertSeverity, Incident, IncidentStatus, utc_now


@dataclass
class AlertIntelligenceAgent:
    embedding_model: HashingEmbeddingModel = field(default_factory=HashingEmbeddingModel)
    correlation_threshold: float = 0.72
    retention_minutes: int = 30
    _recent_alerts: deque[Alert] = field(default_factory=lambda: deque(maxlen=1000))

    def deduplicate_alerts(self, alert: Alert) -> Alert:
        fingerprint = self._fingerprint(alert)
        alert.fingerprint = fingerprint
        cutoff = utc_now() - timedelta(minutes=self.retention_minutes)
        matches = [
            item
            for item in self._recent_alerts
            if item.fingerprint == fingerprint and item.starts_at >= cutoff and item.ends_at is None
        ]
        alert.deduplicated_count = len(matches) + 1
        return alert

    def correlate_alerts(self, alert: Alert) -> Alert:
        text = self._correlation_text(alert)
        vector = self.embedding_model.embed(text)
        best_match: Alert | None = None
        best_score = 0.0
        for candidate in self._recent_alerts:
            candidate_score = cosine_similarity(
                vector, self.embedding_model.embed(self._correlation_text(candidate))
            )
            if candidate_score > best_score:
                best_match = candidate
                best_score = candidate_score

        if best_match and best_score >= self.correlation_threshold:
            alert.correlation_id = best_match.correlation_id or str(best_match.id)
        else:
            alert.correlation_id = str(alert.id)
        return alert

    def classify_severity(self, alert: Alert) -> Alert:
        text = f"{alert.name} {alert.description}".lower()
        critical_terms = ("outage", "unavailable", "data loss", "payment", "security")
        high_terms = ("latency", "error", "saturation", "throttling", "degraded")
        if alert.severity == AlertSeverity.CRITICAL or any(term in text for term in critical_terms):
            alert.severity = AlertSeverity.CRITICAL
        elif alert.severity == AlertSeverity.HIGH or any(term in text for term in high_terms):
            alert.severity = AlertSeverity.HIGH
        elif "warn" in text:
            alert.severity = AlertSeverity.WARNING
        else:
            alert.severity = AlertSeverity.INFO if alert.severity == AlertSeverity.INFO else alert.severity
        return alert

    def enrich_alert(self, alert: Alert) -> tuple[Alert, Incident]:
        alert.metadata.update(
            {
                "owner_team": alert.labels.get("team", "platform-ops"),
                "runbook_hint": alert.annotations.get("runbook", f"runbooks/{alert.service}.md"),
                "source_category": self._source_category(alert.source),
            }
        )
        self._recent_alerts.append(alert)
        incident = Incident(
            alert_ids=[alert.id],
            service=alert.service,
            environment=alert.environment,
            severity=alert.severity,
            status=IncidentStatus.INVESTIGATING,
            title=f"{alert.service}: {alert.name}",
            summary=alert.description,
            owner_team=alert.metadata["owner_team"],
        )
        return alert, incident

    def process(self, alert: Alert) -> tuple[Alert, Incident]:
        alert = self.deduplicate_alerts(alert)
        alert = self.correlate_alerts(alert)
        alert = self.classify_severity(alert)
        return self.enrich_alert(alert)

    def _fingerprint(self, alert: Alert) -> str:
        stable = "|".join(
            [alert.source, alert.name, alert.service, alert.environment, alert.labels.get("pod", "")]
        )
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

    def _correlation_text(self, alert: Alert) -> str:
        labels = " ".join(f"{key}:{value}" for key, value in sorted(alert.labels.items()))
        return f"{alert.service} {alert.environment} {alert.name} {alert.description} {labels}"

    def _source_category(self, source: str) -> str:
        if source in {"prometheus", "grafana", "datadog", "splunk", "azure monitor"}:
            return "monitoring"
        return "custom"
