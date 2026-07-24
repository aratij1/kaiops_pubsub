import json

import pytest
from ai_workbench_common.memory_store import InMemoryStore
from common.models import Alert, AlertSeverity, Incident
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
                provider=self.name,
                model=f"{self.name}-model",
                input_tokens=100,
                output_tokens=50,
                input_cost_per_million=1.0,
                output_cost_per_million=2.0,
            ),
        )


class FallbackGateway:
    async def generate(self, request) -> dict:
        content = {
            "title": "Identify the most likely root cause using only",
            "summary": "Generic fallback RCA draft",
            "content": "Generic fallback content that should not be used as trusted RCA.",
            "commands": [],
            "scripts": [],
            "queries": [],
            "metadata": {
                "fallback": True,
                "fallback_reason": "gemini unavailable; gpt-4o unavailable; gpt-5 unavailable",
            },
        }
        return {
            "model": "heuristic-fallback",
            "content": json.dumps(content),
            "usage": {
                "provider": "heuristic-fallback",
                "model": "heuristic-fallback",
                "task": request.task,
                "estimated": True,
                "fallback": True,
            },
        }


def static_router() -> ModelRouter:
    return ModelRouter(
        providers={
            "gpt-5": StaticProvider("gpt-5"),
            "gpt-4o": StaticProvider("gpt-4o"),
            "claude": StaticProvider("claude"),
            "local-llama": StaticProvider("local-llama"),
        }
    )


def test_vector_db_connector_loads_rag_documents() -> None:
    connector = VectorDBConnector()

    assert connector.documents
    assert any(doc["kind"] == "runbook" for doc in connector.documents)
    assert any(doc["kind"] == "incident" for doc in connector.documents)
    assert any(doc["kind"] == "dependency" for doc in connector.documents)


@pytest.mark.asyncio
async def test_context_agent_returns_requested_shape() -> None:
    alert = Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="payment latency after deployment",
        labels={"deployment": "payments-api"},
    )
    incident = Incident(service="payments", severity=AlertSeverity.CRITICAL, title="payments latency")

    context = await ContextIntelligenceAgent().collect(alert, incident)

    assert context.deployment == "Deployment 2.5"
    assert context.runbook
    assert set(context.dependency_services) >= {"checkout", "ledger", "fraud", "postgres-primary"}
    assert context.recent_changes
    assert context.metadata["rag_documents"] >= 1
    assert any(match["kind"] == "runbook" for match in context.metadata["rag_matches"])
    assert context.metadata["rag_index"]["vector_store"]["provider"] == "file-backed-memory"
    assert context.metadata["rag_index"]["embedding_model"]["model"] == "hashing-token-counter-v1"
    assert context.metadata["context_graph"] == {
        "enabled": True,
        "stages": ["validate_event", "collect_connector_evidence", "assemble_context"],
        "connector_count": 8,
    }


@pytest.mark.asyncio
async def test_resolution_agent_generates_recommendation() -> None:
    alert = Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="payment latency after deployment",
        labels={"deployment": "payments-api"},
    )
    incident = Incident(service="payments", severity=AlertSeverity.CRITICAL, title="payments latency")
    context = await ContextIntelligenceAgent().collect(alert, incident)

    recommendation = await ResolutionIntelligenceAgent(model_router=static_router()).resolve(context)

    assert recommendation.root_cause == "Deployment 2.5"
    assert recommendation.confidence >= 0.9
    assert recommendation.impact == "Payments latency"
    assert recommendation.recommended_action == "Rollback deployment"


@pytest.mark.asyncio
async def test_resolution_agent_clamps_all_model_fallback_confidence() -> None:
    alert = Alert(
        source="prometheus",
        name="KaiOpsServiceDown",
        service="kaiops-platform",
        severity=AlertSeverity.CRITICAL,
        description="KaiOps platform service is not reachable by Prometheus for more than 1 minute.",
    )
    incident = Incident(service="kaiops-platform", severity=AlertSeverity.CRITICAL, title="kaiops service down")
    context = await ContextIntelligenceAgent().collect(alert, incident)

    recommendation = await ResolutionIntelligenceAgent(model_gateway=FallbackGateway()).resolve(context)

    assert recommendation.confidence <= 0.49
    assert not recommendation.root_cause.startswith("{")
    assert recommendation.metadata["fallback_used"] is True
    assert recommendation.metadata["quality_gate"]["requires_human_review"] is True
    assert recommendation.metadata["quality_gate"]["trusted_for_auto_execution"] is False


@pytest.mark.asyncio
async def test_resolution_agent_runtime_persists_reflection_memory() -> None:
    alert = Alert(
        source="prometheus",
        name="PaymentLatencyHigh",
        service="payments",
        severity=AlertSeverity.CRITICAL,
        description="payment latency after deployment",
        labels={"deployment": "payments-api"},
    )
    incident = Incident(service="payments", severity=AlertSeverity.CRITICAL, title="payments latency")
    context = await ContextIntelligenceAgent().collect(alert, incident)
    memory = InMemoryStore()

    recommendation = await ResolutionIntelligenceAgent(model_router=static_router(), memory_store=memory).resolve_with_runtime(context)

    assert recommendation.metadata.get("runtime", {}).get("status") == "succeeded"
    assert recommendation.metadata.get("runtime", {}).get("reflection", {}).get("agent") == "resolution-agent"
    entries = await memory.recent("incident-memory", limit=5)
    assert entries
    assert entries[-1]["incident_id"] == str(context.incident_id)
