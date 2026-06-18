import pytest
from common.models import Alert, AlertSeverity, Incident
from context_agent import ContextIntelligenceAgent
from model_router import ModelRouter
from model_router.router import ModelProvider
from resolution_agent import ResolutionIntelligenceAgent


class StaticProvider(ModelProvider):
    async def generate(self, prompt: str, payload: dict) -> str:
        self._ensure_available()
        self.breaker.record_success()
        return f"{self.name}:{prompt}:{payload.get('summary', payload.get('service', 'incident'))}"


def static_router() -> ModelRouter:
    return ModelRouter(
        providers={
            "gpt-5": StaticProvider("gpt-5"),
            "gpt-4o": StaticProvider("gpt-4o"),
            "claude": StaticProvider("claude"),
            "gemini": StaticProvider("gemini"),
            "local-llama": StaticProvider("local-llama"),
        }
    )


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
    assert context.dependency_services == ["checkout", "ledger", "fraud"]
    assert context.recent_changes


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
