from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from common.config import Settings
from common.logging import get_logger

logger = get_logger(__name__)

_SINGLE_INPUT_METRICS = {"coherence", "fluency", "safety", "hallucination"}
_CONTEXT_METRICS = {"groundedness", "grounding", "relevance", "citation_coverage"}
_SUPPORTED_METRICS = _SINGLE_INPUT_METRICS | _CONTEXT_METRICS


@dataclass(slots=True)
class EvaluationResult:
    metric: str
    score: float
    explanation: str = ""
    confidence: float | None = None


def _clamp_score(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return min(max(numeric, 0.0), 1.0)


def _token_set(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_:-]{3,}", str(value or "").lower())
        if token not in {"the", "and", "for", "with", "from", "this", "that", "into", "will", "are", "was"}
    }


def _best_match_score(rows: list[dict[str, Any]]) -> float:
    best = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("match_confidence", "_similarity", "similarity", "score", "confidence"):
            if key in row:
                best = max(best, _clamp_score(row.get(key)))
    return best


def build_quality_evaluation(
    *,
    prediction: Any,
    context: Any = "",
    confidence: float | None = None,
    citations: list[str] | None = None,
    rag_matches: list[dict[str, Any]] | None = None,
    runbook_found: bool = False,
    fallback_used: bool = False,
    external: EvaluationResult | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an always-available quality envelope for AIOps recommendations.

    The scores are deterministic guardrail signals, not a replacement for a
    human or model judge. If an external judge result exists, its score is
    included and blended into the overall score.
    """

    prediction_text = str(prediction or "").strip()
    context_text = str(context or "").strip()
    citation_rows = [str(item).strip() for item in (citations or []) if str(item or "").strip()]
    match_rows = [item for item in (rag_matches or []) if isinstance(item, dict)]

    confidence_score = _clamp_score(confidence, 0.5 if prediction_text else 0.0)
    citation_coverage = _clamp_score(len(citation_rows) / 3.0)
    rag_match_score = _best_match_score(match_rows)
    evidence_coverage = _clamp_score((0.35 if runbook_found else 0.0) + (0.4 if match_rows else 0.0) + (0.25 if context_text else 0.0))

    prediction_tokens = _token_set(prediction_text)
    context_tokens = _token_set(context_text)
    overlap = len(prediction_tokens & context_tokens) / max(1, len(prediction_tokens)) if prediction_tokens else 0.0
    token_grounding = _clamp_score(overlap)
    grounding_score = _clamp_score(
        (0.3 * citation_coverage)
        + (0.25 * evidence_coverage)
        + (0.25 * max(rag_match_score, token_grounding))
        + (0.2 if runbook_found else 0.0)
    )

    external_score = None
    external_confidence = None
    external_metric = ""
    external_explanation = ""
    if isinstance(external, EvaluationResult):
        external_score = _clamp_score(external.score)
        external_confidence = _clamp_score(external.confidence, external_score) if external.confidence is not None else None
        external_metric = external.metric
        external_explanation = external.explanation
    elif isinstance(external, dict):
        external_score = _clamp_score(external.get("score")) if external.get("score") is not None else None
        external_confidence = _clamp_score(external.get("confidence"), external_score or 0.0) if external.get("confidence") is not None else None
        external_metric = str(external.get("metric") or "")
        external_explanation = str(external.get("explanation") or "")

    hallucination_risk = _clamp_score(
        1.0
        - (0.42 * grounding_score)
        - (0.22 * citation_coverage)
        - (0.18 * evidence_coverage)
        - (0.18 * confidence_score)
        + (0.12 if fallback_used else 0.0)
    )
    hallucination_score = _clamp_score(1.0 - hallucination_risk)
    overall_score = _clamp_score(
        (0.3 * confidence_score)
        + (0.3 * grounding_score)
        + (0.2 * hallucination_score)
        + (0.1 * citation_coverage)
        + (0.1 * evidence_coverage)
    )
    if external_score is not None:
        overall_score = _clamp_score((0.7 * overall_score) + (0.3 * external_score))

    label = "high" if overall_score >= 0.82 and hallucination_risk <= 0.25 else "medium" if overall_score >= 0.62 else "low"
    return {
        "contract_version": "kaiops.evaluation.v1",
        "provider": "deterministic-quality-gate",
        "confidence_score": round(confidence_score, 4),
        "grounding_score": round(grounding_score, 4),
        "hallucination_risk": round(hallucination_risk, 4),
        "hallucination_score": round(hallucination_score, 4),
        "citation_coverage": round(citation_coverage, 4),
        "evidence_coverage": round(evidence_coverage, 4),
        "rag_match_score": round(rag_match_score, 4),
        "overall_score": round(overall_score, 4),
        "quality_label": label,
        "requires_review": bool(hallucination_risk >= 0.45 or grounding_score < 0.55 or confidence_score < 0.65),
        "external_judge": {
            "metric": external_metric,
            "score": round(external_score, 4) if external_score is not None else None,
            "confidence": round(external_confidence, 4) if external_confidence is not None else None,
            "explanation": external_explanation,
        },
        "signals": {
            "citations": len(citation_rows),
            "rag_matches": len(match_rows),
            "runbook_found": bool(runbook_found),
            "fallback_used": bool(fallback_used),
            "token_overlap": round(token_grounding, 4),
        },
    }


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
