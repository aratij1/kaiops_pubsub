from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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

    def __post_init__(self) -> None:
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
