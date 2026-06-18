import pytest
from common.models import AlertSeverity
from model_router import ModelRouter, ModelTask
from model_router.router import ModelProvider


class StaticProvider(ModelProvider):
    async def generate(self, prompt: str, payload: dict) -> str:
        self._ensure_available()
        self.breaker.record_success()
        return f"{self.name}:{prompt}:{payload.get('summary', payload.get('service', 'incident'))}"


class FailingProvider(ModelProvider):
    async def generate(self, prompt: str, payload: dict) -> str:
        self.breaker.record_failure()
        raise RuntimeError(f"{self.name} unavailable")


def test_model_router_selection_rules() -> None:
    router = ModelRouter()

    assert router.select_model(severity=AlertSeverity.CRITICAL, task=ModelTask.RCA) == "gpt-5"
    assert router.select_model(severity=AlertSeverity.HIGH, task=ModelTask.RCA) == "claude"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.SUMMARIZATION) == "gemini"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.GENERAL) == "local-llama"


@pytest.mark.asyncio
async def test_model_router_failover() -> None:
    router = ModelRouter(
        providers={
            "gpt-5": FailingProvider("gpt-5"),
            "gpt-4o": StaticProvider("gpt-4o"),
            "claude": StaticProvider("claude"),
            "gemini": StaticProvider("gemini"),
            "local-llama": StaticProvider("local-llama"),
        }
    )

    response = await router.route(
        severity=AlertSeverity.CRITICAL,
        task=ModelTask.RCA,
        prompt="rca",
        payload={"summary": "payment latency"},
    )

    assert response["model"] == "gpt-4o"
