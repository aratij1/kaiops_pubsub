from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from common.config import get_settings
from common.gcp_auth import get_google_bearer_token
from common.logging import get_logger
from common.models import SafetyCheckResult, SafetyDecision

logger = get_logger(__name__)

# Model Armor confidenceLevel / likelihood -> numeric score heuristics.
# Model Armor does not return a single float score; it returns discrete
# enum bands per filter. These map the documented bands onto the same
# 0..1 scale the local regex analyzer already uses, so both providers'
# results are threshold-compatible in analyze()/analyze_response().
_CONFIDENCE_LEVEL_SCORES = {"HIGH": 0.95, "MEDIUM": 0.65, "LOW": 0.35}
_LIKELIHOOD_SCORES = {
    "VERY_LIKELY": 0.95,
    "LIKELY": 0.8,
    "POSSIBLE": 0.5,
    "UNLIKELY": 0.2,
    "VERY_UNLIKELY": 0.05,
}
_MATCH_FOUND = "MATCH_FOUND"


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
    _vertex_response_endpoint: str = ""
    _vertex_timeout_seconds: float = 8.0
    _vertex_multi_language_detection: bool = False
    _vertex_source_language: str = ""
    _vertex_sanitize_responses: bool = False

    def __post_init__(self) -> None:
        settings = get_settings()
        self._vertex_enabled = bool(getattr(settings, "vertex_model_armor_enabled", False))
        self._vertex_project_id = str(getattr(settings, "gcp_project_id", "") or "").strip()
        self._vertex_region = str(getattr(settings, "gcp_region", "us-central1") or "us-central1").strip() or "us-central1"
        self._vertex_template = str(getattr(settings, "vertex_model_armor_template", "") or "").strip()
        self._vertex_timeout_seconds = float(getattr(settings, "vertex_model_armor_timeout_seconds", 8.0) or 8.0)
        self._vertex_multi_language_detection = bool(
            getattr(settings, "vertex_model_armor_multi_language_detection", False)
        )
        self._vertex_source_language = str(getattr(settings, "vertex_model_armor_source_language", "") or "").strip()
        self._vertex_sanitize_responses = bool(getattr(settings, "vertex_model_armor_sanitize_responses", False))

        # An explicit endpoint override (VERTEX_MODEL_ARMOR_ENDPOINT) is used verbatim for
        # both the prompt and response calls, since Model Armor can't otherwise distinguish
        # which verb a fully custom endpoint targets. Only when no override is given do we
        # derive two distinct URLs (…:sanitizeUserPrompt vs …:sanitizeModelResponse).
        self._vertex_endpoint = str(getattr(settings, "vertex_model_armor_endpoint", "") or "").strip()
        if not self._vertex_endpoint:
            self._vertex_response_endpoint = self._resolve_vertex_endpoint(action="sanitizeModelResponse")
            self._vertex_endpoint = self._resolve_vertex_endpoint(action="sanitizeUserPrompt")
        else:
            self._vertex_response_endpoint = self._vertex_endpoint

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
        """Screen an inbound user/request payload (Model Armor's SanitizeUserPrompt)."""
        text = self._flatten(payload)
        if self.provider_mode == "vertex_model_armor":
            cloud_result = self._analyze_with_vertex_model_armor(text)
            if cloud_result is not None:
                return cloud_result

        return self._analyze_locally(text)

    def analyze_response(self, payload: Any) -> SafetyCheckResult:
        """Screen an outbound model/service response (Model Armor's SanitizeModelResponse).

        Disabled by default even when vertex_model_armor_enabled is on — set
        VERTEX_MODEL_ARMOR_SANITIZE_RESPONSES=true to opt in, since scanning every
        proxied response is a distinct blast-radius decision from scanning requests.
        """
        if not self._vertex_sanitize_responses:
            return SafetyCheckResult(decision=SafetyDecision.ALLOW, score=0.0, categories=[], reasons=[], provider="disabled")

        text = self._flatten(payload)
        if self.provider_mode == "vertex_model_armor":
            cloud_result = self._analyze_with_vertex_model_armor(text, is_response=True)
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

    def _analyze_with_vertex_model_armor(self, text: str, *, is_response: bool = False) -> SafetyCheckResult | None:
        # Keep local safety behavior as a deterministic fallback when Vertex is unavailable.
        if not self._vertex_enabled:
            return None
        if not self._vertex_project_id or not self._vertex_endpoint:
            return None

        token = self._google_bearer_token()
        if not token:
            logger.warning("vertex model armor call skipped: no Google credentials available")
            return None

        endpoint = self._vertex_response_endpoint if is_response else self._vertex_endpoint
        field_name = "modelResponseData" if is_response else "userPromptData"
        response_payload = self._call_vertex_model_armor(
            text=text, token=token, endpoint=endpoint, field_name=field_name
        )
        if not isinstance(response_payload, dict):
            return None

        return self._parse_sanitization_response(response_payload)

    def _parse_sanitization_response(self, response_payload: dict[str, Any]) -> SafetyCheckResult | None:
        result = response_payload.get("sanitizationResult")
        if not isinstance(result, dict):
            # Defensive: tolerate a caller/mock that already unwraps sanitizationResult.
            result = response_payload

        invocation_result = str(result.get("invocationResult", "SUCCESS")).upper()
        if invocation_result == "FAILURE":
            logger.warning("vertex model armor invocation failed; falling back to local analyzer")
            return None

        filter_match_state = str(result.get("filterMatchState", "")).upper()
        filter_results = result.get("filterResults")
        if filter_match_state != _MATCH_FOUND and not isinstance(filter_results, dict):
            return SafetyCheckResult(decision=SafetyDecision.ALLOW, score=0.0, categories=[], reasons=[], provider="vertex_model_armor")

        categories: list[str] = []
        reasons: list[str] = []
        scores: list[float] = [0.0]

        if isinstance(filter_results, dict):
            self._collect_csam(filter_results, categories, reasons, scores)
            self._collect_malicious_uris(filter_results, categories, reasons, scores)
            self._collect_rai(filter_results, categories, reasons, scores)
            self._collect_pi_and_jailbreak(filter_results, categories, reasons, scores)
            self._collect_sdp(filter_results, categories, reasons, scores)

        score = min(max(scores), 1.0)
        if not categories and filter_match_state == _MATCH_FOUND:
            # A match was reported but none of the known filter shapes matched what we parsed —
            # don't silently allow; surface it generically rather than defaulting to ALLOW.
            categories.append("unknown")
            reasons.append("Model Armor reported a match in an unrecognized filter result")
            score = max(score, self.block_threshold)

        if score >= self.block_threshold:
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
            categories=sorted(set(categories)),
            reasons=reasons,
            provider="vertex_model_armor",
        )

    @staticmethod
    def _collect_csam(filter_results: dict[str, Any], categories: list[str], reasons: list[str], scores: list[float]) -> None:
        node = (filter_results.get("csam") or {}).get("csamFilterFilterResult") or {}
        if str(node.get("matchState", "")).upper() == _MATCH_FOUND:
            categories.append("csam")
            reasons.append("CSAM content detected")
            scores.append(1.0)

    @staticmethod
    def _collect_malicious_uris(
        filter_results: dict[str, Any], categories: list[str], reasons: list[str], scores: list[float]
    ) -> None:
        node = (filter_results.get("malicious_uris") or {}).get("maliciousUriFilterResult") or {}
        if str(node.get("matchState", "")).upper() == _MATCH_FOUND:
            categories.append("malicious_uris")
            reasons.append("Malicious URI detected")
            scores.append(0.9)

    @staticmethod
    def _collect_rai(filter_results: dict[str, Any], categories: list[str], reasons: list[str], scores: list[float]) -> None:
        rai_result = (filter_results.get("rai") or {}).get("raiFilterResult") or {}
        type_results = rai_result.get("raiFilterTypeResults")
        if not isinstance(type_results, dict):
            return
        for rai_type, type_result in type_results.items():
            if not isinstance(type_result, dict):
                continue
            if str(type_result.get("matchState", "")).upper() != _MATCH_FOUND:
                continue
            confidence = str(type_result.get("confidenceLevel", "")).upper()
            categories.append(f"rai_{rai_type}")
            reasons.append(f"Responsible AI filter matched: {rai_type}")
            scores.append(_CONFIDENCE_LEVEL_SCORES.get(confidence, 0.7))

    @staticmethod
    def _collect_pi_and_jailbreak(
        filter_results: dict[str, Any], categories: list[str], reasons: list[str], scores: list[float]
    ) -> None:
        node = (filter_results.get("pi_and_jailbreak") or {}).get("piAndJailbreakFilterResult") or {}
        if str(node.get("matchState", "")).upper() != _MATCH_FOUND:
            return
        confidence = str(node.get("confidenceLevel", "")).upper()
        categories.append("pi_and_jailbreak")
        reasons.append("Prompt injection / jailbreak attempt detected")
        scores.append(_CONFIDENCE_LEVEL_SCORES.get(confidence, 0.7))

    @staticmethod
    def _collect_sdp(filter_results: dict[str, Any], categories: list[str], reasons: list[str], scores: list[float]) -> None:
        sdp_result = (filter_results.get("sdp") or {}).get("sdpFilterResult") or {}
        for result_key in ("inspectResult", "redactResult"):
            inner = sdp_result.get(result_key)
            if not isinstance(inner, dict):
                continue
            if str(inner.get("matchState", "")).upper() != _MATCH_FOUND:
                continue
            findings = inner.get("findings")
            if not isinstance(findings, list) or not findings:
                categories.append("sdp")
                reasons.append("Sensitive data detected")
                scores.append(0.6)
                continue
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                info_type = str(finding.get("infoType") or "sdp").strip() or "sdp"
                likelihood = str(finding.get("likelihood", "")).upper()
                categories.append(f"sdp_{info_type}")
                reasons.append(f"Sensitive data detected: {info_type}")
                scores.append(_LIKELIHOOD_SCORES.get(likelihood, 0.5))

    def _resolve_vertex_endpoint(self, action: str = "sanitizeUserPrompt") -> str:
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

        return f"https://modelarmor.{self._vertex_region}.rep.googleapis.com/v1/{template_path}:{action}"

    def _google_bearer_token(self) -> str | None:
        return get_google_bearer_token()

    def _call_vertex_model_armor(
        self, *, text: str, token: str, endpoint: str, field_name: str
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {field_name: {"text": text}}
        if self._vertex_multi_language_detection:
            metadata: dict[str, Any] = {"enableMultiLanguageDetection": True}
            if self._vertex_source_language:
                metadata["sourceLanguage"] = self._vertex_source_language
            payload["multiLanguageDetectionMetadata"] = metadata

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self._vertex_timeout_seconds) as client:
                response = client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else None
        except Exception as exc:
            logger.warning(
                "vertex model armor call failed; falling back to local analyzer",
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
