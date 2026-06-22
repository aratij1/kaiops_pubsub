import httpx
import pytest
from common.config import Settings, get_settings
from common.models import AlertSeverity
from model_router import ModelRouter, ModelTask
from model_router.router import (
    GeminiModelProvider,
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
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.SUMMARIZATION) == "gemini"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.GENERAL) == "groq"


def test_default_multi_provider_model_names() -> None:
    providers = build_default_providers(get_settings())

    assert providers["gemini"].model == "gemini-2.5-flash"
    assert providers["groq"].model == "llama-3.3-70b-versatile"


def test_provider_error_message_redacts_query_string() -> None:
    request = httpx.Request("POST", "https://example.test/models/gemini:generateContent?key=secret")
    response = httpx.Response(404, request=request, text="not found")

    message = provider_error_message("gemini", "gemini-2.5-flash", response)

    assert "secret" not in message
    assert "?" not in message


def test_warns_for_deprecated_gemini_model(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        build_default_providers(Settings(GEMINI_MODEL="gemini-2.0-flash"))

    assert "GEMINI_MODEL 'gemini-2.0-flash' may be retired" in caplog.text


@pytest.mark.asyncio
async def test_gemini_retires_model_retries_once_with_fallback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            request = httpx.Request("POST", url)
            if "gemini-2.0-flash" in url:
                return httpx.Response(
                    404,
                    request=request,
                    json={
                        "error": {
                            "code": 404,
                            "message": "This model models/gemini-2.0-flash is no longer available.",
                            "status": "NOT_FOUND",
                        }
                    },
                )
            return httpx.Response(
                200,
                request=request,
                json={
                    "candidates": [{"content": {"parts": [{"text": "fallback-success"}]}}],
                    "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 7},
                },
            )

    monkeypatch.setattr("model_router.router.httpx.AsyncClient", FakeAsyncClient)

    provider = GeminiModelProvider(name="gemini", model="gemini-2.0-flash", api_key="test-key")
    with caplog.at_level("WARNING"):
        response = await provider.generate("summarize", {"service": "payments"})

    assert response.content == "fallback-success"
    assert response.usage.model == "gemini-2.5-flash"
    assert "appears retired; retrying once" in caplog.text


@pytest.mark.asyncio
async def test_model_router_failover() -> None:
    router = ModelRouter(
        providers={
            "gpt-5": FailingProvider("gpt-5"),
            "gpt-4o": StaticProvider("gpt-4o"),
            "claude": StaticProvider("claude"),
            "gemini": StaticProvider("gemini"),
            "groq": StaticProvider("groq"),
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
