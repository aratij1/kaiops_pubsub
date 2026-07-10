from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from common.config import get_settings
from common.models import SafetyCheckResult, SafetyDecision


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
    _vertex_enabled: bool = False
    _vertex_project_id: str = ""
    _vertex_region: str = "us-central1"
    _vertex_template: str = ""
    _vertex_endpoint: str = ""
    _vertex_timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        settings = get_settings()
        self._vertex_enabled = bool(getattr(settings, "vertex_model_armor_enabled", False))
        self._vertex_project_id = str(getattr(settings, "gcp_project_id", "") or "").strip()
        self._vertex_region = str(getattr(settings, "gcp_region", "us-central1") or "us-central1").strip() or "us-central1"
        self._vertex_template = str(getattr(settings, "vertex_model_armor_template", "") or "").strip()
        self._vertex_endpoint = str(getattr(settings, "vertex_model_armor_endpoint", "") or "").strip()
        if not self._vertex_endpoint:
            self._vertex_endpoint = self._resolve_vertex_endpoint()
        self._vertex_timeout_seconds = float(getattr(settings, "vertex_model_armor_timeout_seconds", 8.0) or 8.0)
        if self._vertex_enabled:
            self.provider_mode = "vertex_model_armor"

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
        text = self._flatten(payload)
        if self.provider_mode == "vertex_model_armor":
            cloud_result = self._analyze_with_vertex_model_armor(text)
            if cloud_result is not None:
                return cloud_result

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
        )

    def _analyze_with_vertex_model_armor(self, text: str) -> SafetyCheckResult | None:
        # Keep local safety behavior as a deterministic fallback when Vertex is unavailable.
        if not self._vertex_enabled:
            return None
        if not self._vertex_project_id or not self._vertex_endpoint:
            return None

        token = self._google_bearer_token()
        if not token:
            return None

        response_payload = self._call_vertex_model_armor(text=text, token=token)
        if not isinstance(response_payload, dict):
            return None

        parsed_payload = response_payload
        for key in ("result", "data", "response"):
            nested = parsed_payload.get(key)
            if isinstance(nested, dict):
                parsed_payload = nested

        blocked = bool(
            parsed_payload.get("blocked")
            or parsed_payload.get("isBlocked")
            or parsed_payload.get("block")
            or parsed_payload.get("malicious")
        )

        score = self._as_float(
            parsed_payload.get("score")
            or parsed_payload.get("riskScore")
            or parsed_payload.get("confidence")
            or 0.0
        )
        score = min(max(score, 0.0), 1.0)

        categories = self._extract_list(parsed_payload.get("categories") or parsed_payload.get("labels"))
        reasons = self._extract_list(parsed_payload.get("reasons") or parsed_payload.get("messages"))

        violations = parsed_payload.get("violations")
        if isinstance(violations, list):
            for violation in violations:
                if isinstance(violation, str):
                    reasons.append(violation)
                elif isinstance(violation, dict):
                    category = str(violation.get("category") or violation.get("label") or "").strip()
                    message = str(violation.get("reason") or violation.get("message") or "").strip()
                    if category:
                        categories.append(category)
                    if message:
                        reasons.append(message)

        categories = sorted(set(item for item in categories if item))
        reasons = [item for item in reasons if item]

        if blocked:
            score = max(score, self.block_threshold)
            decision = SafetyDecision.BLOCK
        elif score >= self.block_threshold:
            decision = SafetyDecision.BLOCK
        elif score >= self.review_threshold:
            decision = SafetyDecision.REVIEW
        else:
            decision = SafetyDecision.ALLOW

        if not reasons:
            reasons = ["vertex model armor decision"]

        return SafetyCheckResult(
            decision=decision,
            score=score,
            categories=categories,
            reasons=reasons,
        )

    def _resolve_vertex_endpoint(self) -> str:
        explicit = str(self._vertex_endpoint or "").strip()
        if explicit:
            return explicit

        template = str(self._vertex_template or "").strip()
        if not template:
            return ""

        if template.startswith(("http://", "https://")):
            return template

        template_path = template.lstrip("/")
        if not template_path.startswith("projects/"):
            if not self._vertex_project_id:
                return ""
            template_path = (
                f"projects/{self._vertex_project_id}/"
                f"locations/{self._vertex_region}/templates/{template_path}"
            )

        return f"https://modelarmor.{self._vertex_region}.rep.googleapis.com/v1/{template_path}:sanitizeUserPrompt"

    @staticmethod
    def _as_float(value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

    @staticmethod
    def _extract_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, dict):
            return [str(key).strip() for key, flag in value.items() if str(key).strip() and bool(flag)]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    def _google_bearer_token(self) -> str | None:
        try:
            import google.auth
            from google.auth.transport.requests import Request

            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            credentials.refresh(Request())
            token = str(getattr(credentials, "token", "") or "").strip()
            return token or None
        except Exception:
            return None

    def _call_vertex_model_armor(self, *, text: str, token: str) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "userPrompt": {"text": text},
            "project": self._vertex_project_id,
            "location": self._vertex_region,
        }
        if self._vertex_template:
            payload["template"] = self._vertex_template

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self._vertex_timeout_seconds) as client:
                response = client.post(self._vertex_endpoint, headers=headers, json=payload)
            response.raise_for_status()
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else None
        except Exception:
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
