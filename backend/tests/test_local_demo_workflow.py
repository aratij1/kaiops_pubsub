import importlib.util
from pathlib import Path

import pytest
from context_agent import ContextIntelligenceAgent
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


def static_router() -> ModelRouter:
    return ModelRouter(
        providers={
            "gpt-5": StaticProvider("gpt-5"),
            "gpt-4o": StaticProvider("gpt-4o"),
            "claude": StaticProvider("claude"),
            "local-llama": StaticProvider("local-llama"),
        }
    )


class FailingRouter(ModelRouter):
    async def route(self, **kwargs):
        raise RuntimeError("all providers failed")

    async def route_provider(self, **kwargs):
        raise RuntimeError(f"{kwargs['provider_name']} failed")


def load_monitoring_app_module():
    module_path = Path("backend/src/monitoring-adapter/app.py")
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InProcessAiLayerClient:
    def __init__(self, router: ModelRouter) -> None:
        self.context_agent = ContextIntelligenceAgent()
        self.resolution_agent = ResolutionIntelligenceAgent(model_router=router)

    async def collect_context(self, *, alert, incident, decision=None):
        return await self.context_agent.collect(alert, incident)

    async def resolve(self, *, context):
        return await self.resolution_agent.resolve(context)


@pytest.mark.asyncio
async def test_local_payment_workflow_generates_recommendation() -> None:
    module = load_monitoring_app_module()
    module.settings.database_enabled = False
    router = static_router()
    module.AiLayerClient = lambda _settings: InProcessAiLayerClient(router)

    workflow = await module.run_local_payment_workflow(trace_id="trace-123", model_router=router, run_comparison=False)

    assert workflow["mode"] == "local-no-kafka"
    assert workflow["alert"]["trace_id"] == "trace-123"
    assert workflow["recommendation"]["trace_id"] == "trace-123"
    assert workflow["alert"]["severity"] == "critical"
    assert workflow["incident"]["service"] == "payments"
    assert workflow["decision"]["workflow"] == "critical-auto-remediation"
    assert workflow["decision"]["policy_version"] == "policy-v1"
    assert workflow["decision"]["policy_reason"]
    assert workflow["context"]["deployment"] == "Deployment 2.5"
    assert workflow["recommendation"]["recommended_action"] == "Rollback deployment"
    assert workflow["recommendation"]["metadata"]["policy_version"] == workflow["decision"]["policy_version"]
    assert workflow["approval"]["metadata"]["policy_version"] == workflow["decision"]["policy_version"]
    assert workflow["remediation_action"]["parameters"]["policy_version"] == workflow["decision"]["policy_version"]
    assert workflow["metrics"]["agent_handoffs"] == 6
    assert 0.5 <= workflow["metrics"]["recommendation_confidence"] < 0.9
    assert isinstance(workflow["closure_report"]["health_restored"], bool)
    assert workflow["remediation_action"]["status"] in {"succeeded", "failed", "skipped"}
    assert workflow["finops"]["totals"]["calls"] >= 1
    assert workflow["finops"]["totals"]["total_tokens"] > 0
    assert workflow["finops"]["totals"]["total_cost_usd"] > 0
    providers = {row["provider"] for row in workflow["finops"]["by_provider"]}
    assert "gpt-5" in providers or "gpt-4o" in providers
    resolution_event = next(event for event in workflow["events"] if event["agent"] == "Resolution Intelligence Agent")
    assert resolution_event["llm_calls"]
    assert {"prompt", "payload", "response", "usage"}.issubset(resolution_event["llm_calls"][0])
    assert [event["agent"] for event in workflow["events"]] == [
        "Alert Intelligence Agent",
        "Orchestrator Agent",
        "Context Intelligence Agent",
        "Resolution Intelligence Agent",
        "Human Approval Layer",
        "Remediation Automation Engine",
        "Closure & Validation",
    ]


def test_sample_flow_catalog_has_ten_scenarios() -> None:
    module = load_monitoring_app_module()

    flows = module.list_scenarios()

    assert len(flows) >= 10
    assert {flow["id"] for flow in flows} >= {"payment-latency", "database-replica-lag"}


@pytest.mark.asyncio
async def test_local_workflow_returns_finops_errors_when_models_fail() -> None:
    module = load_monitoring_app_module()
    module.settings.database_enabled = False
    router = FailingRouter()
    module.AiLayerClient = lambda _settings: InProcessAiLayerClient(router)

    workflow = await module.run_local_payment_workflow(
        trace_id="trace-fail",
        flow_id="checkout-pod-crash",
        model_router=router,
        run_comparison=False,
    )

    assert workflow["recommendation"]["recommended_action"] == "Restart pod"
    assert workflow["recommendation"]["metadata"]["fallback_used"] is True
    assert isinstance(workflow["closure_report"]["health_restored"], bool)
