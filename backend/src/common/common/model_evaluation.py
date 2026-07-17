from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from common.config import Settings
from common.logging import get_logger

logger = get_logger(__name__)

_SINGLE_INPUT_METRICS = {"coherence", "fluency", "safety"}
_CONTEXT_METRICS = {"groundedness"}
_SUPPORTED_METRICS = _SINGLE_INPUT_METRICS | _CONTEXT_METRICS


@dataclass(slots=True)
class EvaluationResult:
    metric: str
    score: float
    explanation: str = ""
    confidence: float | None = None


class AzureAIEvaluationClient:
    """Best-effort evaluation via Azure OpenAI judge deployment."""

    def __init__(self, settings: Settings) -> None:
        self._enabled = bool(getattr(settings, "azure_ai_evaluation_enabled", False))
        self._endpoint = str(getattr(settings, "azure_openai_endpoint", "") or "").strip().rstrip("/")
        self._api_key = str(getattr(settings, "azure_openai_api_key", "") or "").strip()
        self._deployment = str(getattr(settings, "azure_ai_evaluation_deployment", "") or "").strip()
        self._api_version = str(getattr(settings, "azure_openai_api_version", "2024-06-01") or "2024-06-01").strip()
        self._timeout_seconds = float(getattr(settings, "azure_ai_evaluation_timeout_seconds", 8.0) or 8.0)

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._endpoint and self._api_key and self._deployment)

    def _endpoint_url(self) -> str:
        return (
            f"{self._endpoint}/openai/deployments/{self._deployment}/chat/completions"
            f"?api-version={self._api_version}"
        )

    @staticmethod
    def _build_prompt(prediction: str, metric: str, context: str | None) -> str:
        context_text = context or ""
        return (
            "You are an evaluator for operational AI outputs. "
            "Return compact JSON with keys score, explanation, confidence. "
            "score must be a float between 0 and 1.\n"
            f"metric: {metric}\n"
            f"context: {context_text}\n"
            f"prediction: {prediction}"
        )

    def evaluate(self, prediction: str, *, metric: str = "coherence", context: str | None = None) -> EvaluationResult | None:
        metric = (metric or "coherence").strip().lower()
        if metric not in _SUPPORTED_METRICS:
            logger.warning("unsupported azure evaluation metric requested", extra={"metric": metric})
            return None
        if not self.enabled:
            return None
        if metric in _CONTEXT_METRICS and not context:
            logger.warning("azure evaluation metric requires context but none was provided", extra={"metric": metric})
            return None

        payload = {
            "messages": [
                {"role": "system", "content": "You are a strict evaluator."},
                {"role": "user", "content": self._build_prompt(prediction, metric, context)},
            ],
            "temperature": 0,
            "max_tokens": 200,
        }
        headers = {"api-key": self._api_key, "Content-Type": "application/json"}

        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(self._endpoint_url(), headers=headers, json=payload)
            response.raise_for_status()
            parsed = response.json()
        except Exception as exc:
            logger.warning("azure evaluation call failed", extra={"error": str(exc), "metric": metric})
            return None

        content = ""
        try:
            content = str(parsed["choices"][0]["message"]["content"])
        except Exception:
            logger.warning("azure evaluation response missing completion content", extra={"metric": metric})
            return None

        try:
            body = json.loads(content)
        except Exception:
            logger.warning("azure evaluation completion was not valid json", extra={"metric": metric})
            return None

        try:
            score = float(body.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = min(max(score, 0.0), 1.0)

        confidence_value = body.get("confidence")
        confidence = None
        if confidence_value is not None:
            try:
                confidence = float(confidence_value)
            except (TypeError, ValueError):
                confidence = None

        return EvaluationResult(
            metric=metric,
            score=score,
            explanation=str(body.get("explanation") or ""),
            confidence=confidence,
        )


class VertexEvaluationClient(AzureAIEvaluationClient):
    """Compatibility alias retained for existing imports."""
