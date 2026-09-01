from __future__ import annotations

import asyncio

import pytest
from ai_workbench_common.memory_store import InMemoryStore
from ai_workbench_common.model_evaluation import EvaluationResult
from ai_workbench_common.models import Context
from common.models import Alert, AlertSeverity, Incident, Recommendation
from context_agent import ContextIntelligenceAgent
from context_agent.connectors import VectorDBConnector
from model_router import ModelRouter
from model_router.router import ModelProvider, ModelResponse, build_usage
from resolution_agent import ResolutionIntelligenceAgent


class StaticProvider(ModelProvider):
    async def generate(self, prompt: str, payload: dict) -> ModelResponse:
        self._ensure_available()
        self.breaker.record_success()
        return ModelResponse(
            content=f"{self.name}:{prompt}:{payload.get('summary', payload.get('service', 'incident'))}",
            usage=build_usage(
                provider=self.name, model=f"{self.name}-model", input_tokens=10, output_tokens=5,
                input_cost_per_million=1.0, output_cost_per_million=2.0,
            ),
        )


def static_router() -> ModelRouter:
    return ModelRouter(providers={name: StaticProvider(name) for name in ("gpt-5", "gpt-4o", "claude", "local-llama")})


class DisabledJudgeClient:
    enabled = False


class StubJudgeClient:
    enabled = True

    def __init__(self, *, score: float = 0.7, confidence: float = 0.6) -> None:
        self.calls: list[dict] = []
        self._score = score
        self._confidence = confidence

    def evaluate(self, prediction, *, metric="coherence", context=None):
        self.calls.append({"prediction": prediction, "metric": metric, "context": context})
        return EvaluationResult(metric=metric, score=self._score, explanation="stub", confidence=self._confidence)


async def _sample_context(rag_root=None) -> Context:
    alert = Alert(
        tenant_id="tenant-a",
        source="prometheus", name="PaymentLatencyHigh", service="payments", severity=AlertSeverity.CRITICAL,
        description="payment latency after deployment", labels={"deployment": "payments-api"},
    )
    incident = Incident(tenant_id="tenant-a", service="payments", severity=AlertSeverity.CRITICAL, title="payments latency")
    connectors = ContextIntelligenceAgent().connectors
    if rag_root is not None:
        connectors[-1] = VectorDBConnector(rag_root=rag_root)
    agent = ContextIntelligenceAgent(connectors=connectors)
    return await agent.collect(alert, incident)


# ---------------------------------------------------------------------------
# _judge_groundedness (Step C)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_groundedness_returns_none_when_disabled() -> None:
    agent = ResolutionIntelligenceAgent(model_router=static_router(), evaluation_client=DisabledJudgeClient())
    result = await agent._judge_groundedness(prediction="x", context_text="some runbook text")
    assert result is None


@pytest.mark.asyncio
async def test_judge_groundedness_returns_none_when_no_context() -> None:
    agent = ResolutionIntelligenceAgent(model_router=static_router(), evaluation_client=StubJudgeClient())
    result = await agent._judge_groundedness(prediction="x", context_text="   ")
    assert result is None


@pytest.mark.asyncio
async def test_judge_groundedness_calls_evaluate_with_groundedness_metric() -> None:
    judge = StubJudgeClient(score=0.73)
    agent = ResolutionIntelligenceAgent(model_router=static_router(), evaluation_client=judge)
    result = await agent._judge_groundedness(prediction="rollback the deployment", context_text="runbook text here")
    assert result is not None
    assert result.score == 0.73
    assert judge.calls == [
        {"prediction": "rollback the deployment", "metric": "groundedness", "context": "runbook text here"},
    ]


@pytest.mark.asyncio
async def test_judge_groundedness_swallows_exceptions() -> None:
    class RaisingJudgeClient:
        enabled = True

        def evaluate(self, *args, **kwargs):
            raise RuntimeError("judge endpoint unreachable")

    agent = ResolutionIntelligenceAgent(model_router=static_router(), evaluation_client=RaisingJudgeClient())
    result = await agent._judge_groundedness(prediction="x", context_text="some context")
    assert result is None


# ---------------------------------------------------------------------------
# _publish_evaluation / _post_evaluation (Step G)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_evaluation_schedules_task_with_correct_payload() -> None:
    agent = ResolutionIntelligenceAgent(model_router=static_router())
    captured: dict = {}

    async def fake_post_evaluation(payload: dict) -> None:
        captured.update(payload)

    agent._post_evaluation = fake_post_evaluation  # type: ignore[method-assign]

    recommendation = Recommendation(
        tenant_id="tenant-a",
        incident_id=Incident(service="payments", severity=AlertSeverity.HIGH, title="t").id,
        root_cause="deploy", confidence=0.8, impact="latency", recommended_action="Rollback deployment",
        severity=AlertSeverity.HIGH, rationale="because", commands=[],
    )
    recommendation.metadata["model_calls"] = [{"provider": "groq", "model": "groq-model"}]
    report = {"overall_score": 0.8}

    agent._publish_evaluation(recommendation=recommendation, report=report)
    await asyncio.sleep(0)  # let the scheduled fire-and-forget task run

    assert captured["report"] == report
    assert captured["agent"] == "resolution-agent"
    assert captured["incident_id"] == str(recommendation.incident_id)
    assert captured["recommendation_id"] == str(recommendation.id)
    assert captured["model_provider"] == "groq"
    assert captured["model_name"] == "groq-model"


@pytest.mark.asyncio
async def test_publish_evaluation_handles_missing_model_calls_gracefully() -> None:
    agent = ResolutionIntelligenceAgent(model_router=static_router())
    captured: dict = {}

    async def fake_post_evaluation(payload: dict) -> None:
        captured.update(payload)

    agent._post_evaluation = fake_post_evaluation  # type: ignore[method-assign]

    recommendation = Recommendation(
        tenant_id="tenant-a",
        incident_id=Incident(service="payments", severity=AlertSeverity.HIGH, title="t").id,
        root_cause="deploy", confidence=0.8, impact="latency", recommended_action="Rollback deployment",
        severity=AlertSeverity.HIGH, rationale="because", commands=[],
    )
    # metadata["model_calls"] deliberately absent

    agent._publish_evaluation(recommendation=recommendation, report={})
    await asyncio.sleep(0)

    assert captured["model_provider"] is None
    assert captured["model_name"] is None


@pytest.mark.asyncio
async def test_post_evaluation_swallows_transport_failures(monkeypatch) -> None:
    agent = ResolutionIntelligenceAgent(model_router=static_router())

    class RaisingAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    import resolution_agent.graph as graph_module

    monkeypatch.setattr(graph_module.httpx, "AsyncClient", RaisingAsyncClient)

    # Must not raise.
    await agent._post_evaluation({"report": {}, "agent": "resolution-agent"})


# ---------------------------------------------------------------------------
# End-to-end: resolve() wires the judge result into the evaluation report
# and never fails even when the publish target cannot be reached.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_wires_external_judge_into_evaluation(monkeypatch, governed_rag_root) -> None:
    import resolution_agent.graph as graph_module

    class NoopAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("evaluation-service unreachable in this test")

    monkeypatch.setattr(graph_module.httpx, "AsyncClient", NoopAsyncClient)

    context = await _sample_context(governed_rag_root)
    judge = StubJudgeClient(score=0.66, confidence=0.5)
    agent = ResolutionIntelligenceAgent(model_router=static_router(), evaluation_client=judge)

    recommendation = await agent.resolve(context)
    await asyncio.sleep(0)  # let the (failing, but swallowed) publish task run

    assert recommendation.metadata["evaluation"]["external_judge"]["score"] == 0.66
    assert judge.calls and judge.calls[0]["metric"] == "groundedness"


@pytest.mark.asyncio
async def test_resolve_default_construction_has_judge_disabled_and_still_succeeds() -> None:
    # Zero-arg-style default: only model_router is injected for determinism; evaluation_client
    # is left to default-construct, which must be disabled (AZURE_AI_EVALUATION_ENABLED unset).
    context = await _sample_context()
    agent = ResolutionIntelligenceAgent(model_router=static_router(), memory_store=InMemoryStore())
    assert agent.evaluation_client.enabled is False

    recommendation = await agent.resolve(context)
    await asyncio.sleep(0)

    assert recommendation.metadata["evaluation"]["external_judge"] == {
        "metric": "",
        "score": None,
        "confidence": None,
        "explanation": "",
    }
