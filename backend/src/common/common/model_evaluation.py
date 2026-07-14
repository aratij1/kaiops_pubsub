from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from common.config import Settings
from common.gcp_auth import get_google_bearer_token
from common.logging import get_logger

logger = get_logger(__name__)

# Metrics that only need the model's output text (no reference/context required).
_SINGLE_INPUT_METRICS = {"coherence", "fluency", "safety"}
# Metrics that also require supporting context to compare the output against.
_CONTEXT_METRICS = {"groundedness"}
_SUPPORTED_METRICS = _SINGLE_INPUT_METRICS | _CONTEXT_METRICS


@dataclass(slots=True)
class EvaluationResult:
    metric: str
    score: float
    explanation: str = ""
    confidence: float | None = None


class VertexEvaluationClient:
    """Client for Vertex AI's Gen AI Evaluation Service (evaluateInstances).

    Disabled by default (VERTEX_EVALUATION_ENABLED=false). Scores LLM-generated
    output (e.g. model-router's RCA/fix/summarization responses) against
    Google-defined quality metrics. Never raises — returns None on any failure
    so callers can treat evaluation as best-effort telemetry, not a hard
    dependency of the generation path.
    """

    def __init__(self, settings: Settings) -> None:
        self._enabled = bool(getattr(settings, "vertex_evaluation_enabled", False))
        self._project_id = str(getattr(settings, "gcp_project_id", "") or "").strip()
        self._region = str(getattr(settings, "gcp_region", "us-central1") or "us-central1").strip() or "us-central1"
        self._timeout_seconds = float(getattr(settings, "vertex_evaluation_timeout_seconds", 8.0) or 8.0)

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._project_id)

    def _endpoint(self) -> str:
        return f"https://{self._region}-aiplatform.googleapis.com/v1/projects/{self._project_id}/locations/{self._region}:evaluateInstances"

    def evaluate(self, prediction: str, *, metric: str = "coherence", context: str | None = None) -> EvaluationResult | None:
        metric = (metric or "coherence").strip().lower()
        if metric not in _SUPPORTED_METRICS:
            logger.warning("unsupported vertex evaluation metric requested", extra={"metric": metric})
            return None
        if not self.enabled:
            return None
        if metric in _CONTEXT_METRICS and not context:
            logger.warning("vertex evaluation metric requires context but none was provided", extra={"metric": metric})
            return None

        token = get_google_bearer_token()
        if not token:
            return None

        input_key = f"{metric}Input"
        instance: dict[str, Any] = {"prediction": prediction}
        if metric in _CONTEXT_METRICS:
            instance["context"] = context
        payload = {input_key: {"metricSpec": {}, "instance": instance}}

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(self._endpoint(), headers=headers, json=payload)
            response.raise_for_status()
            parsed = response.json()
        except Exception as exc:
            logger.warning("vertex evaluation call failed", extra={"error": str(exc), "metric": metric})
            return None

        if not isinstance(parsed, dict):
            return None
        result_key = f"{metric}Result"
        result = parsed.get(result_key)
        if not isinstance(result, dict):
            logger.warning("vertex evaluation response missing expected result field", extra={"metric": metric, "result_key": result_key})
            return None

        try:
            score = float(result.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0

        confidence = result.get("confidence")
        return EvaluationResult(
            metric=metric,
            score=score,
            explanation=str(result.get("explanation") or ""),
            confidence=float(confidence) if confidence is not None else None,
        )
