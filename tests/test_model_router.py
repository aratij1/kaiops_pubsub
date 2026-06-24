import httpx
import pytest
from common.config import get_settings
from common.models import AlertSeverity
from model_router import ModelRouter, ModelTask
from model_router.router import (
    ModelProvider,
    ModelResponse,
    build_default_providers,
    build_usage,
    provider_error_message,
)


class StaticProvider(ModelProvider):
    async def generate(self, prompt: str, payload: dict) -> ModelResponse:
        self._ensure_available()
        self.breaker.record_success()
        content = f"{self.name}:{prompt}:{payload.get('summary', payload.get('service', 'incident'))}"
        return ModelResponse(
            content=content,
            usage=build_usage(
                provider=self.name,
                model=f"{self.name}-model",
                input_tokens=100,
                output_tokens=50,
                input_cost_per_million=1.0,
                output_cost_per_million=2.0,
            ),
        )


class FailingProvider(ModelProvider):
    async def generate(self, prompt: str, payload: dict) -> ModelResponse:
        self.breaker.record_failure()
        raise RuntimeError(f"{self.name} unavailable")


def test_model_router_selection_rules() -> None:
    router = ModelRouter()

    assert router.select_model(severity=AlertSeverity.CRITICAL, task=ModelTask.RCA) == "gpt-5"
    assert router.select_model(severity=AlertSeverity.HIGH, task=ModelTask.RCA) == "claude"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.SUMMARIZATION) == "gpt-4o"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.GENERAL) == "gpt-4o"


def test_default_gpt_provider_model_names() -> None:
    providers = build_default_providers(get_settings())

    assert providers["gpt-5"].model == "gpt-5"
    assert providers["gpt-4o"].model == "gpt-4o"
    assert "gemini" not in providers
    assert "groq" not in providers


def test_provider_error_message_redacts_query_string() -> None:
    request = httpx.Request("POST", "https://example.test/models/gemini:generateContent?key=secret")
    response = httpx.Response(404, request=request, text="not found")

    message = provider_error_message("gemini", "gemini-2.5-flash", response)

    assert "secret" not in message
    assert "?" not in message


@pytest.mark.asyncio
async def test_model_router_failover() -> None:
    router = ModelRouter(
        providers={
            "gpt-5": FailingProvider("gpt-5"),
            "gpt-4o": StaticProvider("gpt-4o"),
            "claude": StaticProvider("claude"),
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
    assert response["usage"]["total_tokens"] == 150
    assert response["usage"]["total_cost_usd"] > 0
