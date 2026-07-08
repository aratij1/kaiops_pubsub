from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from common.agentic import AgentContext, BaseAgent
from common.config import get_settings
from common.embeddings import HashingEmbeddingModel, cosine_similarity
from common.models import Alert, AlertSeverity, Incident, IncidentStatus, utc_now
from common.repository_interfaces import AlertHistoryRepository, InMemoryAlertHistoryRepository


@dataclass
class AlertIntelligenceAgent(BaseAgent):
    embedding_model: HashingEmbeddingModel = field(default_factory=HashingEmbeddingModel)
    correlation_threshold: float | None = None
    retention_minutes: int | None = None
    alert_history_repository: AlertHistoryRepository = field(default_factory=InMemoryAlertHistoryRepository)
    name: str = "alert-intelligence-agent"
    _embedding_cache: dict[str, list[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        settings = get_settings()
        if self.correlation_threshold is None:
            self.correlation_threshold = float(getattr(settings, "alert_correlation_threshold", 0.72))
        if self.retention_minutes is None:
            self.retention_minutes = int(getattr(settings, "alert_retention_minutes", 30))

    async def deduplicate_alerts(self, alert: Alert) -> Alert:
        fingerprint = self._fingerprint(alert)
        alert.fingerprint = fingerprint
        cutoff = utc_now() - timedelta(minutes=int(self.retention_minutes or 30))
        matches = [
            item
            for item in await self.alert_history_repository.list_recent_alerts()
            if item.fingerprint == fingerprint and item.starts_at >= cutoff and item.ends_at is None
        ]
        alert.deduplicated_count = len(matches) + 1
        return alert

    async def correlate_alerts(self, alert: Alert) -> Alert:
        text = self._correlation_text(alert)
        vector = self._embed(text)
        best_match: Alert | None = None
        best_score = 0.0
        for candidate in await self.alert_history_repository.list_recent_alerts():
            candidate_score = cosine_similarity(vector, self._embed(self._correlation_text(candidate)))
            if candidate_score > best_score:
                best_match = candidate
                best_score = candidate_score

        if best_match and best_score >= float(self.correlation_threshold or 0.72):
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

    async def enrich_alert(self, alert: Alert) -> tuple[Alert, Incident]:
        alert.metadata.update(
            {
                "owner_team": alert.labels.get("team", "platform-ops"),
                "runbook_hint": alert.annotations.get("runbook", f"runbooks/{alert.service}.md"),
                "source_category": self._source_category(alert.source),
            }
        )
        await self.alert_history_repository.record_alert(alert)
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

    async def process(self, alert: Alert) -> tuple[Alert, Incident]:
        alert = await self.deduplicate_alerts(alert)
        alert = await self.correlate_alerts(alert)
        alert = self.classify_severity(alert)
        return await self.enrich_alert(alert)

    async def can_execute(self, context: AgentContext) -> bool:
        return context.alert is not None

    async def execute(self, context: AgentContext) -> dict[str, Any]:
        if context.alert is None:
            raise ValueError("AgentContext.alert is required")
        alert, incident = await self.process(context.alert)
        context.alert = alert
        context.incident = incident
        context.set_result(self.name, {"alert": alert.model_dump(mode="json"), "incident": incident.model_dump(mode="json")})
        return {"alert": alert, "incident": incident}

    async def validate(self, result: Any) -> bool:
        return isinstance(result, dict) and "alert" in result and "incident" in result

    def _fingerprint(self, alert: Alert) -> str:
        stable = "|".join([alert.source, alert.name, alert.service, alert.environment, alert.labels.get("pod", "")])
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

    def _correlation_text(self, alert: Alert) -> str:
        labels = " ".join(f"{key}:{value}" for key, value in sorted(alert.labels.items()))
        return f"{alert.service} {alert.environment} {alert.name} {alert.description} {labels}"

    def _embed(self, text: str) -> list[float]:
        cached = self._embedding_cache.get(text)
        if cached is None:
            cached = self.embedding_model.embed(text)
            self._embedding_cache[text] = cached
        return cached

    def _source_category(self, source: str) -> str:
        if source in {"prometheus", "grafana", "datadog", "splunk", "azure monitor"}:
            return "monitoring"
        return "custom"
