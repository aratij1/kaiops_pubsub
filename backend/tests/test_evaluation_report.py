from __future__ import annotations

import json

import pytest
from ai_workbench_common.model_evaluation import (
    AzureAIEvaluationClient,
    EvaluationReport,
    EvaluationResult,
    build_evaluation_report,
    build_quality_evaluation,
)
from common.config import Settings
from pydantic import ValidationError


def _enabled_settings(**overrides) -> Settings:
    defaults = dict(
        AZURE_AI_EVALUATION_ENABLED=True,
        AZURE_OPENAI_ENDPOINT="https://judge.example.net",
        AZURE_OPENAI_API_KEY="key",
        AZURE_AI_EVALUATION_DEPLOYMENT="judge-deploy",
    )
    defaults.update(overrides)
    return Settings(**defaults)


class _FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": json.dumps(self._body)}}]}


class _FakeSyncClient:
    def __init__(self, responder) -> None:
        self._responder = responder

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, json=None):
        return self._responder(url, headers, json)


def _patch_httpx_client(monkeypatch, responder) -> None:
    import ai_workbench_common.model_evaluation as module

    monkeypatch.setattr(module.httpx, "Client", lambda timeout: _FakeSyncClient(responder))


# ---------------------------------------------------------------------------
# EvaluationReport contract (Step A)
# ---------------------------------------------------------------------------


def test_evaluation_report_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EvaluationReport(
            confidence_score=0.5,
            grounding_score=0.5,
            hallucination_risk=0.5,
            hallucination_score=0.5,
            citation_coverage=0.5,
            evidence_coverage=0.5,
            rag_match_score=0.5,
            overall_score=0.5,
            quality_label="medium",
            requires_review=False,
            unexpected_field="not part of the contract",
        )


def test_build_evaluation_report_returns_typed_model() -> None:
    report = build_evaluation_report(
        prediction="Rollback deployment payments-api",
        context="Restart the payments deployment and check p95 latency.",
        confidence=0.87,
        citations=["runbook://payments", "incident://123"],
        rag_matches=[{"kind": "runbook", "similarity": 0.71}],
        runbook_found=True,
    )
    assert isinstance(report, EvaluationReport)
    assert report.contract_version == "kaiops.evaluation.v1"
    assert report.rag_match_score == 0.71


def test_build_quality_evaluation_matches_build_evaluation_report_dump() -> None:
    kwargs = dict(
        prediction="Rollback deployment payments-api",
        context="Restart the payments deployment and check p95 latency.",
        confidence=0.87,
        citations=["runbook://payments", "incident://123"],
        rag_matches=[{"kind": "runbook", "similarity": 0.71}],
        runbook_found=True,
    )
    assert build_quality_evaluation(**kwargs) == build_evaluation_report(**kwargs).model_dump(mode="json")


def test_quality_label_high_for_strong_grounded_confident_response() -> None:
    evaluation = build_quality_evaluation(
        prediction="Rollback deployment payments-api",
        context="payments runbook: rollback deployment payments-api",
        confidence=0.95,
        citations=["a", "b", "c"],
        rag_matches=[{"similarity": 0.95}],
        runbook_found=True,
    )
    assert evaluation["quality_label"] == "high"


def test_quality_label_medium_for_partial_signals() -> None:
    evaluation = build_quality_evaluation(
        prediction="Investigate service health and check dashboards",
        context="payments runbook mentions checking dashboards",
        confidence=0.65,
        citations=["a"],
        rag_matches=[{"similarity": 0.5}],
        runbook_found=True,
    )
    assert evaluation["quality_label"] == "medium"


def test_quality_label_low_for_empty_fallback_response() -> None:
    evaluation = build_quality_evaluation(
        prediction="", context="", confidence=None, citations=[], rag_matches=[],
        runbook_found=False, fallback_used=True,
    )
    assert evaluation["quality_label"] == "low"


def test_requires_review_true_for_low_confidence() -> None:
    evaluation = build_quality_evaluation(prediction="", context="", confidence=0.1)
    assert evaluation["requires_review"] is True


def test_requires_review_false_for_strong_grounded_response() -> None:
    evaluation = build_quality_evaluation(
        prediction="Rollback deployment payments-api",
        context="payments runbook: rollback deployment payments-api",
        confidence=0.95,
        citations=["runbook://payments", "incident://1", "incident://2"],
        rag_matches=[{"similarity": 0.95}],
        runbook_found=True,
    )
    assert evaluation["requires_review"] is False


def test_requires_review_true_for_weak_rag_match_even_with_high_confidence() -> None:
    evaluation = build_quality_evaluation(
        prediction="Archive old MySQL alert rows and validate table growth",
        context="mysql runbook: archive old MySQL alert rows and validate table growth",
        confidence=0.99,
        citations=["runbook://mysql", "incident://1", "action://archive"],
        rag_matches=[{"kind": "runbook", "similarity": 0.27}],
        runbook_found=True,
    )
    assert evaluation["requires_review"] is True
    assert evaluation["quality_label"] != "high"


def test_requires_review_true_for_fallback_even_with_text_output() -> None:
    evaluation = build_quality_evaluation(
        prediction="Investigate service health and collect Prometheus evidence",
        context="service health evidence",
        confidence=0.8,
        citations=["incident://1"],
        rag_matches=[],
        runbook_found=False,
        fallback_used=True,
    )
    assert evaluation["requires_review"] is True
    assert evaluation["quality_label"] == "low"


def test_external_judge_as_dict_blends_into_overall_score() -> None:
    baseline = build_quality_evaluation(prediction="x", context="y", confidence=0.5)
    with_external = build_quality_evaluation(
        prediction="x", context="y", confidence=0.5, external={"metric": "coherence", "score": 1.0}
    )
    assert with_external["external_judge"]["score"] == 1.0
    assert with_external["overall_score"] > baseline["overall_score"]


def test_external_judge_as_evaluation_result_object() -> None:
    result = EvaluationResult(metric="groundedness", score=0.42, explanation="stub", confidence=0.6)
    evaluation = build_quality_evaluation(prediction="x", context="y", confidence=0.5, external=result)
    assert evaluation["external_judge"] == {
        "metric": "groundedness",
        "score": 0.42,
        "confidence": 0.6,
        "explanation": "stub",
    }


def test_rag_match_score_reads_similarity_key() -> None:
    # Regression guard for the Step B fix: rag_matches rows carry "similarity".
    evaluation = build_quality_evaluation(
        prediction="x", context="y", rag_matches=[{"kind": "runbook", "similarity": 0.64}]
    )
    assert evaluation["rag_match_score"] == 0.64


# ---------------------------------------------------------------------------
# AzureAIEvaluationClient.evaluate / evaluate_many (Step C)
# ---------------------------------------------------------------------------


def test_evaluate_disabled_by_default_returns_none() -> None:
    client = AzureAIEvaluationClient(Settings())
    assert client.enabled is False
    assert client.evaluate("prediction", metric="coherence") is None


def test_evaluate_rejects_unsupported_metric(monkeypatch) -> None:
    client = AzureAIEvaluationClient(_enabled_settings())
    assert client.evaluate("prediction", metric="not-a-real-metric") is None


def test_evaluate_requires_context_for_context_metrics() -> None:
    client = AzureAIEvaluationClient(_enabled_settings())
    assert client.evaluate("prediction", metric="groundedness", context=None) is None


def test_evaluate_success_parses_judge_response(monkeypatch) -> None:
    client = AzureAIEvaluationClient(_enabled_settings())
    _patch_httpx_client(
        monkeypatch,
        lambda url, headers, json: _FakeResponse({"score": 0.91, "explanation": "looks coherent", "confidence": 0.8}),
    )
    result = client.evaluate("prediction text", metric="coherence")
    assert result is not None
    assert result.metric == "coherence"
    assert result.score == 0.91
    assert result.confidence == 0.8


def test_evaluate_clamps_out_of_range_score(monkeypatch) -> None:
    client = AzureAIEvaluationClient(_enabled_settings())
    _patch_httpx_client(monkeypatch, lambda url, headers, json: _FakeResponse({"score": 5.0}))
    result = client.evaluate("prediction text", metric="coherence")
    assert result is not None
    assert result.score == 1.0


def test_evaluate_returns_none_on_transport_failure(monkeypatch) -> None:
    client = AzureAIEvaluationClient(_enabled_settings())

    def _raise(url, headers, json):
        raise RuntimeError("connection refused")

    _patch_httpx_client(monkeypatch, _raise)
    assert client.evaluate("prediction text", metric="coherence") is None


def test_evaluate_many_runs_each_metric(monkeypatch) -> None:
    client = AzureAIEvaluationClient(_enabled_settings())

    def _responder(url, headers, json):
        prompt = json["messages"][1]["content"]
        metric = "coherence" if "metric: coherence" in prompt else "groundedness"
        score = 0.9 if metric == "coherence" else 0.4
        return _FakeResponse({"score": score, "explanation": metric})

    _patch_httpx_client(monkeypatch, _responder)
    results = client.evaluate_many("prediction text", metrics=["coherence", "groundedness"], context="some context")
    assert [r.metric for r in results] == ["coherence", "groundedness"]
    assert results[0].score == 0.9
    assert results[1].score == 0.4


def test_evaluate_many_omits_metrics_missing_required_context(monkeypatch) -> None:
    client = AzureAIEvaluationClient(_enabled_settings())
    _patch_httpx_client(monkeypatch, lambda url, headers, json: _FakeResponse({"score": 0.5}))
    results = client.evaluate_many("prediction text", metrics=["groundedness", "not-a-real-metric"], context=None)
    assert results == []


def test_evaluate_many_empty_metrics_list_returns_empty() -> None:
    client = AzureAIEvaluationClient(_enabled_settings())
    assert client.evaluate_many("prediction text", metrics=[]) == []


def test_metrics_are_genuinely_decoupled() -> None:
    # High confidence but zero grounding (no citations, no matches, no context overlap)
    unsupported = build_quality_evaluation(
        prediction="Arbitrary hallucinated fix for database locks",
        context="Memory usage in cache node was 90%",
        confidence=0.99,
        citations=[],
        rag_matches=[],
        runbook_found=False,
    )
    # Low confidence but strong grounding (direct verbatim overlap and runbook matches)
    grounded_hesitant = build_quality_evaluation(
        prediction="Memory usage in cache node was 90%",
        context="Memory usage in cache node was 90%",
        confidence=0.20,
        citations=["runbook://redis", "incident://db-1"],
        rag_matches=[{"similarity": 0.95}],
        runbook_found=True,
    )

    # 1. Confidence scores reflect input confidence independently
    assert unsupported["confidence_score"] == 0.99
    assert grounded_hesitant["confidence_score"] == 0.20

    # 2. Grounding score is high for grounded even if hesitant, and low for unsupported even if confident
    assert grounded_hesitant["grounding_score"] > unsupported["grounding_score"]
    assert grounded_hesitant["grounding_score"] >= 0.70
    assert unsupported["grounding_score"] < 0.20

    # 3. Hallucination risk is high when grounding is low, low when grounding is high
    assert unsupported["hallucination_risk"] > grounded_hesitant["hallucination_risk"]

    # 4. Overall score properly blends both without forcing them to equal each other
    assert unsupported["overall_score"] != unsupported["confidence_score"]
    assert grounded_hesitant["overall_score"] != grounded_hesitant["grounding_score"]

