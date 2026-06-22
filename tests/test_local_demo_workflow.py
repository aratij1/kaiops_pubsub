import importlib.util
from pathlib import Path

import pytest
from common.models import RemediationStatus
from model_router import ModelRouter
from model_router.router import ModelProvider, ModelResponse, build_usage


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
            "gemini": StaticProvider("gemini"),
            "groq": StaticProvider("groq"),
            "local-llama": StaticProvider("local-llama"),
        }
    )


class FailingRouter(ModelRouter):
    async def route(self, **kwargs):
        raise RuntimeError("all providers failed")

    async def route_provider(self, **kwargs):
        raise RuntimeError(f"{kwargs['provider_name']} failed")


def load_monitoring_app_module():
    module_path = Path("services/monitoring-adapter/app.py")
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_local_payment_workflow_generates_recommendation() -> None:
    module = load_monitoring_app_module()

    workflow = await module.run_local_payment_workflow(trace_id="trace-123", model_router=static_router())

    assert workflow["mode"] == "local-no-kafka"
    assert workflow["alert"].trace_id == "trace-123"
    assert workflow["recommendation"].trace_id == "trace-123"
    assert workflow["alert"].severity == "critical"
    assert workflow["incident"].service == "payments"
    assert workflow["decision"]["workflow"] == "critical-auto-remediation"
    assert workflow["context"].deployment == "Deployment 2.5"
    assert workflow["recommendation"].recommended_action == "Rollback deployment"
    assert workflow["metrics"]["agent_handoffs"] == 6
    assert workflow["metrics"]["recommendation_confidence"] >= 0.9
    assert workflow["closure_report"].health_restored is True
    assert workflow["remediation_action"].status == RemediationStatus.SUCCEEDED
    assert workflow["finops"]["totals"]["calls"] >= 4
    assert workflow["finops"]["totals"]["total_tokens"] > 0
    assert workflow["finops"]["totals"]["total_cost_usd"] > 0
    providers = {row["provider"] for row in workflow["finops"]["by_provider"]}
    assert {"gemini", "groq"}.issubset(providers)
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

    assert len(flows) == 10
    assert {flow["id"] for flow in flows} >= {"payment-latency", "database-replica-lag"}


@pytest.mark.asyncio
async def test_local_workflow_returns_finops_errors_when_models_fail() -> None:
    module = load_monitoring_app_module()

    workflow = await module.run_local_payment_workflow(
        trace_id="trace-fail",
        flow_id="checkout-pod-crash",
        model_router=FailingRouter(),
    )

    assert workflow["recommendation"].recommended_action == "Restart pod"
    assert workflow["finops"]["totals"]["failed_calls"] >= 3
    assert workflow["closure_report"].health_restored is True
