from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from common.config import Settings, get_settings
from common.models import AlertSeverity
from common.orchestration.config_loader import load_orchestration_config


@dataclass(slots=True)
class PolicyDecision:
    risk_tier: str
    requires_approval: bool
    execution_mode: str
    reason: str


@dataclass(slots=True)
class PolicyEngine:
    settings: Settings = field(default_factory=get_settings)
    policies: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.policies:
            self.policies = load_orchestration_config(self.settings)

    def _risk_tier_for_severity(self, severity: AlertSeverity) -> str:
        risk_map = self.policies.get("risk_tiers_by_severity", {})
        if isinstance(risk_map, dict):
            mapped = str(risk_map.get(severity.value) or "").strip().lower()
            if mapped:
                return mapped
        if severity in {AlertSeverity.CRITICAL, AlertSeverity.HIGH}:
            return "high"
        if severity == AlertSeverity.WARNING:
            return "medium"
        return "low"

    def evaluate(self, *, severity: AlertSeverity, confidence: float | None = None) -> PolicyDecision:
        risk_tier = self._risk_tier_for_severity(severity)
        if severity.value in self.policies.get("approval_severities", set()):
            return PolicyDecision(
                risk_tier=risk_tier,
                requires_approval=True,
                execution_mode="human-approval",
                reason="severity in mandatory approval set",
            )

        if confidence is None:
            return PolicyDecision(
                risk_tier=risk_tier,
                requires_approval=False,
                execution_mode="guided-auto",
                reason="no confidence score available; use guided execution",
            )

        auto_threshold = float(self.policies.get("confidence_auto_execute_threshold", 0.9))
        guided_threshold = float(self.policies.get("confidence_guided_execute_threshold", 0.75))
        if guided_threshold > auto_threshold:
            guided_threshold = auto_threshold

        if confidence < guided_threshold:
            return PolicyDecision(
                risk_tier=risk_tier,
                requires_approval=True,
                execution_mode="human-approval",
                reason="confidence below guided threshold",
            )
        if confidence < auto_threshold:
            return PolicyDecision(
                risk_tier=risk_tier,
                requires_approval=False,
                execution_mode="guided-auto",
                reason="confidence in guided range",
            )
        return PolicyDecision(
            risk_tier=risk_tier,
            requires_approval=False,
            execution_mode="auto-execute",
            reason="confidence above auto-execute threshold",
        )

    def requires_approval(self, *, severity: AlertSeverity, confidence: float | None = None) -> bool:
        return self.evaluate(severity=severity, confidence=confidence).requires_approval
