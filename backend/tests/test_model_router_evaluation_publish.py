from __future__ import annotations

import asyncio

import pytest
from ai_workbench_common.model_evaluation import EvaluationResult
from common.config import Settings
from model_router.router import ModelRouter, _configured_evaluation_metrics


class StubJudgeClient:
    enabled = True

    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self.calls: list[dict] = []
        self._scores = scores or {}

    def evaluate_many(self, prediction, *, metrics, context=None):
        self.calls.append({"prediction": prediction, "metrics": list(metrics), "context": context})
        return [
            EvaluationResult(metric=metric, score=self._scores.get(metric, 0.5), explanation=f"stub {metric}")
            for metric in metrics
        ]


class DisabledJudgeClient:
    enabled = False

    def evaluate_many(self, *args, **kwargs):
        raise AssertionError("must not be called when disabled")


# ---------------------------------------------------------------------------
# _configured_evaluation_metrics
# ---------------------------------------------------------------------------


def test_configured_metrics_falls_back_to_single_metric_by_default() -> None:
    settings = Settings()
    assert _configured_evaluation_metrics(settings) == ["coherence"]


def test_configured_metrics_respects_single_metric_override() -> None:
    settings = Settings(AZURE_AI_EVALUATION_METRIC="hallucination")
    assert _configured_evaluation_metrics(settings) == ["hallucination"]


def test_configured_metrics_parses_comma_separated_list() -> None:
    settings = Settings(AZURE_AI_EVALUATION_METRICS="Coherence, Groundedness ,hallucination")
    assert _configured_evaluation_metrics(settings) == ["coherence", "groundedness", "hallucination"]


def test_configured_metrics_falls_back_when_list_is_blank() -> None:
    settings = Settings(AZURE_AI_EVALUATION_METRICS="   ", AZURE_AI_EVALUATION_METRIC="safety")
    assert _configured_evaluation_metrics(settings) == ["safety"]


# ---------------------------------------------------------------------------
# _attach_evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_evaluation_disabled_adds_no_keys() -> None:
    router = ModelRouter(providers={}, evaluation_client=DisabledJudgeClient())
    result = await router._attach_evaluation({"model": "gpt-4o", "content": "some response"}, payload={})
    assert "evaluation" not in result
    assert "evaluations" not in result


@pytest.mark.asyncio
async def test_attach_evaluation_skips_when_content_empty() -> None:
    router = ModelRouter(providers={}, evaluation_client=StubJudgeClient())
    result = await router._attach_evaluation({"model": "gpt-4o", "content": ""}, payload={})
    assert "evaluation" not in result


@pytest.mark.asyncio
async def test_attach_evaluation_default_single_metric_matches_legacy_shape() -> None:
    router = ModelRouter(providers={}, evaluation_client=StubJudgeClient({"coherence": 0.91}))
    result = await router._attach_evaluation({"model": "gpt-4o", "content": "some response"}, payload={})

    assert result["evaluation"] == {
        "metric": "coherence", "score": 0.91, "explanation": "stub coherence", "confidence": None,
    }
    assert result["evaluations"] == [result["evaluation"]]


@pytest.mark.asyncio
async def test_attach_evaluation_multi_metric_populates_both_keys(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_AI_EVALUATION_METRICS", "coherence,hallucination")
    judge = StubJudgeClient({"coherence": 0.8, "hallucination": 0.3})
    router = ModelRouter(providers={}, evaluation_client=judge, settings=Settings())
    result = await router._attach_evaluation({"model": "gpt-4o", "content": "some response"}, payload={})

    assert result["evaluation"]["metric"] == "coherence"
    assert [item["metric"] for item in result["evaluations"]] == ["coherence", "hallucination"]
    assert judge.calls[0]["metrics"] == ["coherence", "hallucination"]


# ---------------------------------------------------------------------------
# _publish_evaluation / _post_evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_evaluation_body_shape() -> None:
    router = ModelRouter(providers={}, evaluation_client=StubJudgeClient())
    captured: dict = {}

    async def fake_post_evaluation(body: dict) -> None:
        captured.update(body)

    router._post_evaluation = fake_post_evaluation  # type: ignore[method-assign]

    result = {
        "model": "gpt-4o",
        "content": "some response",
        "usage": {"model": "gpt-4o-2024"},
        "evaluations": [{"metric": "coherence", "score": 0.9, "explanation": "", "confidence": None}],
    }
    router._publish_evaluation(result=result, payload={"incident_id": "11111111-1111-1111-1111-111111111111"})
    await asyncio.sleep(0)

    assert captured["report"]["contract_version"] == "kaiops.evaluation.judge.v1"
    assert captured["report"]["metrics"] == result["evaluations"]
    assert captured["agent"] == "model-router"
    assert captured["incident_id"] == "11111111-1111-1111-1111-111111111111"
    assert captured["recommendation_id"] is None
    assert captured["model_provider"] == "gpt-4o"
    assert captured["model_name"] == "gpt-4o-2024"


@pytest.mark.asyncio
async def test_attach_evaluation_triggers_publish_when_enabled() -> None:
    router = ModelRouter(providers={}, evaluation_client=StubJudgeClient({"coherence": 0.7}))
    captured: dict = {}

    async def fake_post_evaluation(body: dict) -> None:
        captured.update(body)

    router._post_evaluation = fake_post_evaluation  # type: ignore[method-assign]

    await router._attach_evaluation(
        {"model": "gpt-4o", "content": "some response"},
        payload={"recommendation_id": "22222222-2222-2222-2222-222222222222"},
    )
    await asyncio.sleep(0)

    assert captured["recommendation_id"] == "22222222-2222-2222-2222-222222222222"
    assert captured["agent"] == "model-router"


@pytest.mark.asyncio
async def test_post_evaluation_swallows_transport_failures(monkeypatch) -> None:
    router = ModelRouter(providers={}, evaluation_client=StubJudgeClient())

    class RaisingAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    import model_router.router as router_module

    monkeypatch.setattr(router_module.httpx, "AsyncClient", RaisingAsyncClient)

    # Must not raise.
    await router._post_evaluation({"report": {}, "agent": "model-router"})
