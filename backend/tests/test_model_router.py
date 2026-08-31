import httpx
import pytest
from common.config import get_settings
from common.models import AlertSeverity
from model_router import ModelRouter, ModelTask
from model_router.router import (
    AzureOpenAIModelProvider,
    ModelProvider,
    ModelResponse,
    OpenAIModelProvider,
    _sanitize_model_payload,
    build_default_providers,
    build_usage,
    normalize_azure_openai_endpoint,
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

    assert router.select_model(severity=AlertSeverity.CRITICAL, task=ModelTask.RCA) == "reasoning-critical"
    assert router.select_model(severity=AlertSeverity.HIGH, task=ModelTask.RCA) == "reasoning-standard"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.SUMMARIZATION) == "gpt-4o"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.GENERAL) == "gpt-4o"


def test_default_gpt_provider_model_names() -> None:
    providers = build_default_providers(get_settings())

    assert providers["reasoning-standard"].model == "gpt-5.6-terra"
    assert providers["reasoning-critical"].model == "gpt-5.6-sol"
    assert providers["gpt-5"].model == "gpt-5"
    assert providers["gpt-4o"].model == "gpt-4o"
    assert providers["gemini"].model == "gemini-2.5-flash"
    assert providers["groq"].model == "llama-3.3-70b-versatile"


def test_legacy_openai_variables_select_azure_adapter_for_azure_endpoint() -> None:
    from common.config import Settings

    providers = build_default_providers(Settings(
        OPENAI_BASE_URL="https://example.openai.azure.com",
        OPENAI_API_KEY="azure-style-key",
        OPENAI_GPT4O_MODEL="production-gpt4o",
        AZURE_OPENAI_CHAT_DEPLOYMENT="production-gpt4o",
    ))

    for name in ("reasoning-standard", "reasoning-critical", "azure-openai", "gpt-5", "gpt-4o"):
        assert isinstance(providers[name], AzureOpenAIModelProvider)
        assert providers[name].base_url == "https://example.openai.azure.com"
        assert providers[name].api_key == "azure-style-key"
        assert providers[name].model == "production-gpt4o"


@pytest.mark.parametrize(
    ("settings_kwargs", "azure_aliases", "expected_key"),
    [
        ({"OPENAI_API_KEY": "openai-key"}, {"azure-openai"}, "openai-key"),
        (
            {
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_KEY": "azure-key",
            },
            {"reasoning-standard", "reasoning-critical", "azure-openai", "gpt-5", "gpt-4o"},
            "azure-key",
        ),
        (
            {
                "OPENAI_BASE_URL": "https://legacy.openai.azure.com",
                "OPENAI_API_KEY": "legacy-azure-key",
            },
            {"reasoning-standard", "reasoning-critical", "azure-openai", "gpt-5", "gpt-4o"},
            "legacy-azure-key",
        ),
        (
            {
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
                "AZURE_OPENAI_API_KEY": "azure-key",
                "OPENAI_API_KEY": "openai-key",
            },
            {"reasoning-standard", "reasoning-critical", "azure-openai", "gpt-5", "gpt-4o"},
            "azure-key",
        ),
        (
            {
                "OPENAI_BASE_URL": "https://models.example.test/v1",
                "OPENAI_API_KEY": "openai-compatible-key",
                "AZURE_OPENAI_API_KEY": "azure-key-must-not-leak",
            },
            {"azure-openai"},
            "openai-compatible-key",
        ),
    ],
)
def test_provider_credential_routing_matrix(settings_kwargs, azure_aliases, expected_key) -> None:
    from common.config import Settings

    providers = build_default_providers(Settings(**settings_kwargs))

    for name in ("reasoning-standard", "reasoning-critical", "azure-openai", "gpt-5", "gpt-4o"):
        if name in azure_aliases:
            assert isinstance(providers[name], AzureOpenAIModelProvider)
        else:
            assert isinstance(providers[name], OpenAIModelProvider)
    assert providers["gpt-4o"].api_key == expected_key
    assert providers["gpt-4o"].api_key != "azure-key-must-not-leak"


def test_azure_key_without_endpoint_is_not_sent_to_native_openai() -> None:
    from common.config import Settings

    providers = build_default_providers(Settings(AZURE_OPENAI_API_KEY="azure-only-key"))

    assert isinstance(providers["gpt-4o"], OpenAIModelProvider)
    assert providers["gpt-4o"].api_key is None
    assert providers["azure-openai"].api_key == "azure-only-key"
    assert providers["azure-openai"].base_url == ""


def test_legacy_azure_endpoint_with_azure_only_key_keeps_default_provider_usable() -> None:
    from common.config import Settings

    settings = Settings(
        OPENAI_BASE_URL="https://example.openai.azure.com",
        AZURE_OPENAI_API_KEY="azure-only-key",
        OPENAI_API_KEY=None,
    )
    providers = build_default_providers(settings)
    default_provider = providers[settings.model_router_default_provider]

    assert isinstance(default_provider, AzureOpenAIModelProvider)
    assert default_provider.api_key == "azure-only-key"
    assert default_provider.base_url == "https://example.openai.azure.com"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.openai.azure.com",
        "https://api.openai.com/v1",
        "https://example.openai.azure.com/openai/deployments/prod",
        "https://example.openai.azure.com/chat/completions",
        "https://example.openai.azure.com?api-version=secret",
        "https://example.openai.azure.com.evil.test",
    ],
)
def test_azure_endpoint_rejects_non_resource_roots(endpoint: str) -> None:
    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        normalize_azure_openai_endpoint(endpoint)


def test_azure_reasoning_deployments_route_independently() -> None:
    from common.config import Settings

    providers = build_default_providers(
        Settings(
            AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com",
            AZURE_OPENAI_API_KEY="azure-key",
            AZURE_OPENAI_CHAT_DEPLOYMENT="chat",
            AZURE_OPENAI_REASONING_STANDARD_DEPLOYMENT="standard",
            AZURE_OPENAI_REASONING_CRITICAL_DEPLOYMENT="critical",
            MODEL_ROUTER_DEFAULT_PROVIDER="azure-openai",
        )
    )

    assert providers["reasoning-standard"].model == "standard"
    assert providers["reasoning-critical"].model == "critical"
    assert providers["azure-openai"].model == "chat"


def test_evaluation_policy_requires_eligible_confirmed_sample(tmp_path) -> None:
    from common.config import Settings

    policy_path = tmp_path / "routing-policy.json"
    policy_path.write_text(
        '{"contract_version":"kaims.model-routing-policy.v1","routes":'
        '{"*:rca":{"provider":"gpt-4o","eligible":true,"cases":75}}}',
        encoding="utf-8",
    )
    router = ModelRouter(
        settings=Settings(MODEL_ROUTER_EVALUATION_POLICY_PATH=str(policy_path)),
        providers={"gpt-4o": StaticProvider("gpt-4o")},
    )

    assert router.select_model(severity=AlertSeverity.HIGH, task=ModelTask.RCA) == "gpt-4o"

    policy_path.write_text(
        '{"contract_version":"kaims.model-routing-policy.v1","routes":'
        '{"*:rca":{"provider":"gpt-4o","eligible":true,"cases":10}}}',
        encoding="utf-8",
    )
    assert router.select_model(severity=AlertSeverity.HIGH, task=ModelTask.RCA) == "reasoning-standard"


def test_provider_error_message_redacts_query_string() -> None:
    request = httpx.Request("POST", "https://example.test/models/gemini:generateContent?key=secret")
    response = httpx.Response(404, request=request, text="not found")

    message = provider_error_message("gemini", "gemini-2.5-flash", response)

    assert "secret" not in message
    assert "?" not in message


def test_model_payload_redacts_nested_secrets_without_mutating_source() -> None:
    source = {
        "service": "payments",
        "authorization": "Bearer secret",
        "connection": {"api-key": "secret", "endpoint": "https://example.test"},
        "evidence": [{"password": "secret", "message": "database timeout"}],
    }

    sanitized = _sanitize_model_payload(source)

    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["connection"]["api-key"] == "[REDACTED]"
    assert sanitized["evidence"][0]["password"] == "[REDACTED]"
    assert sanitized["evidence"][0]["message"] == "database timeout"
    assert source["authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_model_router_rejects_oversized_prompt() -> None:
    from common.config import Settings

    settings = Settings(MODEL_ROUTER_MAX_PROMPT_CHARS=8)
    router = ModelRouter(settings=settings, providers={"gpt-4o": StaticProvider("gpt-4o")})

    with pytest.raises(ValueError, match="prompt exceeds"):
        await router.route(
            severity=AlertSeverity.WARNING,
            task=ModelTask.GENERAL,
            prompt="too many characters",
            payload={},
        )


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


@pytest.mark.asyncio
async def test_model_router_cache_hit_zeroes_billable_cost(monkeypatch) -> None:
    from common.config import Settings

    settings = Settings(
        MODEL_ROUTER_PROMPT_CACHE_ENABLED=True,
        MODEL_ROUTER_PROMPT_CACHE_TTL_SECONDS=300,
        MODEL_ROUTER_PROMPT_CACHE_MAX_ENTRIES=16,
    )
    provider = StaticProvider("gpt-4o")
    router = ModelRouter(
        settings=settings,
        providers={
            "gpt-5": StaticProvider("gpt-5"),
            "gpt-4o": provider,
            "local-llama": StaticProvider("local-llama"),
        },
    )

    first = await router.route(
        severity=AlertSeverity.WARNING,
        task=ModelTask.GENERAL,
        prompt="summarize",
        payload={"service": "payments"},
    )
    second = await router.route(
        severity=AlertSeverity.WARNING,
        task=ModelTask.GENERAL,
        prompt="summarize",
        payload={"service": "payments"},
    )

    assert first.get("cached") is None
    assert second["cached"] is True
    assert second["usage"]["cached"] is True
    assert second["usage"]["total_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_model_router_cache_can_be_disabled() -> None:
    from common.config import Settings

    settings = Settings(MODEL_ROUTER_PROMPT_CACHE_ENABLED=False)
    provider = StaticProvider("gpt-4o")
    router = ModelRouter(
        settings=settings,
        providers={
            "gpt-5": StaticProvider("gpt-5"),
            "gpt-4o": provider,
            "local-llama": StaticProvider("local-llama"),
        },
    )

    first = await router.route(
        severity=AlertSeverity.WARNING,
        task=ModelTask.GENERAL,
        prompt="summarize",
        payload={"service": "payments"},
    )
    second = await router.route(
        severity=AlertSeverity.WARNING,
        task=ModelTask.GENERAL,
        prompt="summarize",
        payload={"service": "payments"},
    )

    assert first.get("cached") is None
    assert second.get("cached") is None
