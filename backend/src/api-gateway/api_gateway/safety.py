from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from common.config import get_settings
from common.logging import get_logger
from common.models import SafetyCheckResult, SafetyDecision

logger = get_logger(__name__)

_AZURE_SEVERITY_MAX = 7.0
_AZURE_BLOCK_SEVERITY = 6
_AZURE_REVIEW_SEVERITY = 3


@dataclass(frozen=True)
class SafetyRule:
    category: str
    pattern: re.Pattern[str]
    reason: str
    weight: float


@dataclass
class SafetyAnalyzer:
    max_payload_chars: int = 25_000
    block_threshold: float = 0.75
    review_threshold: float = 0.35
    rules: list[SafetyRule] = field(default_factory=list)
    provider_mode: str = "local"
    _azure_enabled: bool = False
    _azure_endpoint: str = ""
    _azure_api_key: str = ""
    _azure_api_version: str = "2024-09-01"
    _azure_timeout_seconds: float = 8.0
    _azure_sanitize_responses: bool = False

    def __post_init__(self) -> None:
        settings = get_settings()
        self._azure_enabled = bool(getattr(settings, "azure_content_safety_enabled", False))
        self._azure_endpoint = str(getattr(settings, "azure_content_safety_endpoint", "") or "").strip().rstrip("/")
        self._azure_api_key = str(getattr(settings, "azure_content_safety_api_key", "") or "").strip()
        self._azure_api_version = str(getattr(settings, "azure_content_safety_api_version", "2024-09-01") or "2024-09-01").strip()
        self._azure_timeout_seconds = float(getattr(settings, "azure_content_safety_timeout_seconds", 8.0) or 8.0)
        self._azure_sanitize_responses = bool(getattr(settings, "azure_content_safety_sanitize_responses", False))

        if self._azure_enabled:
            self.provider_mode = "azure_content_safety"

        if self.rules:
            return
        patterns = [
            (
                "jailbreak",
                r"\b(ignore|bypass|override)\b.{0,40}\b(previous|prior|system|developer)\b.{0,40}\b(instruction|prompt|policy|rule)s?\b",
                "Attempt to override system/developer instructions",
                0.45,
            ),
            (
                "jailbreak",
                r"\b(DAN|developer mode|do anything now|unfiltered mode|jailbreak)\b",
                "Known jailbreak persona or mode request",
                0.45,
            ),
            (
                "prompt_injection",
                (
                    r"\b(reveal|print|dump|show|exfiltrate)\b.{0,60}"
                    r"\b(system prompt|hidden prompt|secrets?|api keys?|tokens?)\b"
                ),
                "Attempt to reveal hidden prompts or secrets",
                0.55,
            ),
            (
                "credential_exfiltration",
                r"\b(AWS_SECRET_ACCESS_KEY|BEGIN RSA PRIVATE KEY|xox[baprs]-|ghp_[A-Za-z0-9_]{20,})\b",
                "Credential-like secret detected in request",
                0.75,
            ),
            (
                "unsafe_execution",
                r"\b(rm\s+-rf|format\s+c:|curl\s+.*\|\s*(sh|bash)|powershell\s+-enc)\b",
                "Potentially destructive command pattern",
                0.4,
            ),
        ]
        self.rules = [
            SafetyRule(category, re.compile(pattern, re.IGNORECASE | re.DOTALL), reason, weight)
            for category, pattern, reason, weight in patterns
        ]

    def analyze(self, payload: Any) -> SafetyCheckResult:
        """Screen an inbound user/request payload."""
        text = self._flatten(payload)
        if self.provider_mode == "azure_content_safety":
            cloud_result = self._analyze_with_azure_content_safety(text)
            if cloud_result is not None:
                return cloud_result

        return self._analyze_locally(text)

    def analyze_response(self, payload: Any) -> SafetyCheckResult:
        """Screen an outbound model/service response."""
        if not self._azure_sanitize_responses:
            return SafetyCheckResult(decision=SafetyDecision.ALLOW, score=0.0, categories=[], reasons=[], provider="disabled")

        text = self._flatten(payload)
        if self.provider_mode == "azure_content_safety":
            cloud_result = self._analyze_with_azure_content_safety(text)
            if cloud_result is not None:
                return cloud_result

        return self._analyze_locally(text)

    def _analyze_locally(self, text: str) -> SafetyCheckResult:
        reasons: list[str] = []
        categories: list[str] = []
        score = 0.0

        if len(text) > self.max_payload_chars:
            reasons.append(f"Payload exceeds {self.max_payload_chars} characters")
            categories.append("payload_size")
            score += 0.4

        for rule in self.rules:
            if rule.pattern.search(text):
                reasons.append(rule.reason)
                categories.append(rule.category)
                score += rule.weight

        score = min(score, 1.0)
        decision = SafetyDecision.ALLOW
        if score >= self.block_threshold:
            decision = SafetyDecision.BLOCK
        elif score >= self.review_threshold:
            decision = SafetyDecision.REVIEW

        return SafetyCheckResult(
            decision=decision,
            score=score,
            categories=sorted(set(categories)),
            reasons=reasons,
            provider="local",
        )

    def _analyze_with_azure_content_safety(self, text: str) -> SafetyCheckResult | None:
        if not self._azure_enabled or not self._azure_endpoint or not self._azure_api_key:
            return None

        response_payload = self._call_azure_content_safety(text=text)
        if not isinstance(response_payload, dict):
            return None

        analysis = response_payload.get("categoriesAnalysis") if isinstance(response_payload, dict) else None
        if not isinstance(analysis, list):
            return None
        categories: list[str] = []
        reasons: list[str] = []
        max_severity = 0
        for item in analysis:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "unknown").strip().lower()
            try:
                severity = int(item.get("severity", 0))
            except (TypeError, ValueError):
                severity = 0
            max_severity = max(max_severity, severity)
            if severity > 0:
                categories.append(category)
                reasons.append(f"Azure Content Safety flagged {category} at severity {severity}")

        if max_severity >= _AZURE_BLOCK_SEVERITY:
            decision = SafetyDecision.BLOCK
        elif max_severity >= _AZURE_REVIEW_SEVERITY:
            decision = SafetyDecision.REVIEW
        else:
            decision = SafetyDecision.ALLOW

        score = min(float(max_severity) / _AZURE_SEVERITY_MAX, 1.0)
        if not reasons and decision != SafetyDecision.ALLOW:
            reasons = ["Azure Content Safety decision"]

        return SafetyCheckResult(
            decision=decision,
            score=score,
            categories=sorted(set(categories)),
            reasons=reasons,
            provider="azure_content_safety",
        )

    def _call_azure_content_safety(self, *, text: str) -> dict[str, Any] | None:
        endpoint = f"{self._azure_endpoint}/contentsafety/text:analyze?api-version={self._azure_api_version}"
        payload: dict[str, Any] = {"text": text}
        headers = {
            "Ocp-Apim-Subscription-Key": self._azure_api_key,
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self._azure_timeout_seconds) as client:
                response = client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else None
        except Exception as exc:
            logger.warning(
                "azure content safety call failed; falling back to local analyzer",
                extra={"error": str(exc), "endpoint": endpoint},
            )
            return None

    def _flatten(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return " ".join(f"{key} {self._flatten(item)}" for key, item in value.items())
        if isinstance(value, list | tuple | set):
            return " ".join(self._flatten(item) for item in value)
        return str(value)
