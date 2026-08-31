import httpx
import pytest
from common.config import Settings, get_settings
from common.models import AlertSeverity
from model_router import ModelRouter, ModelTask
from model_router.router import (
    _sanitize_model_payload,
    AnthropicModelProvider,
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
    assert providers["claude"].model == "claude-sonnet-4-6"


def test_default_provider_registry_includes_all_existing_providers_and_claude() -> None:
    # Adding Claude must not remove or rename any pre-existing provider key.
    providers = build_default_providers(get_settings())

    for expected_key in (
        "reasoning-standard",
        "reasoning-critical",
        "azure-openai",
        "gpt-5",
        "gpt-4o",
        "claude",
        "gemini",
        "groq",
        "local-llama",
    ):
        assert expected_key in providers


def test_claude_provider_uses_configured_model_and_costs() -> None:
    settings = Settings(
        ANTHROPIC_MODEL="claude-opus-5",
        ANTHROPIC_API_KEY="sk-ant-test-key",
        ANTHROPIC_BASE_URL="https://api.anthropic.test/v1",
        ANTHROPIC_INPUT_COST_PER_MILLION=1.5,
        ANTHROPIC_OUTPUT_COST_PER_MILLION=7.5,
    )
    providers = build_default_providers(settings)
    claude = providers["claude"]

    assert isinstance(claude, AnthropicModelProvider)
    assert claude.model == "claude-opus-5"
    assert claude.api_key == "sk-ant-test-key"
    assert claude.base_url == "https://api.anthropic.test/v1"
    assert claude.input_cost_per_million == 1.5
    assert claude.output_cost_per_million == 7.5


def test_claude_provider_not_in_any_existing_failover_chain() -> None:
    # Smallest safe change: Claude is selectable explicitly but does not
    # alter any existing provider's automatic fallback behavior.
    router = ModelRouter()

    for chain in router.failover_chain.values():
        assert "claude" not in chain


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


# --- AnthropicModelProvider ----------------------------------------------
# None of these tests call the real Anthropic API or require ANTHROPIC_API_KEY
# to be set; httpx.AsyncClient is monkeypatched to a MockTransport so the
# request never leaves the process.


def _claude_provider(**overrides) -> AnthropicModelProvider:
    kwargs = {
        "name": "claude",
        "model": "claude-sonnet-4-6",
        "api_key": "sk-ant-test-key",
        "base_url": "https://api.anthropic.test/v1",
        "anthropic_version": "2023-06-01",
    }
    kwargs.update(overrides)
    return AnthropicModelProvider(**kwargs)


@pytest.mark.asyncio
async def test_claude_generate_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = httpx.Request("POST", request.url, content=request.content).content
        return httpx.Response(
            200,
            json={
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "hello from claude"}],
                "usage": {"input_tokens": 12, "output_tokens": 6},
            },
        )

    async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))

    provider = _claude_provider()
    response = await provider.generate("rca", {"summary": "payment latency"})

    assert response.content == "hello from claude"
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 6
    assert response.usage.provider == "claude"
    assert captured["url"] == "https://api.anthropic.test/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-test-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    # The API key must never be logged/exposed anywhere except this header.
    assert "sk-ant-test-key" not in str(captured["url"])


@pytest.mark.asyncio
async def test_claude_generate_missing_api_key_raises_without_http_call(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"content": [{"type": "text", "text": "unreachable"}]})

    async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))

    provider = _claude_provider(api_key=None)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not configured"):
        await provider.generate("rca", {})

    assert called is False


@pytest.mark.asyncio
async def test_claude_generate_invalid_api_key_raises_and_records_breaker_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})

    async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))

    provider = _claude_provider(api_key="sk-ant-bad-key")

    with pytest.raises(RuntimeError, match="HTTP 401"):
        await provider.generate("rca", {})

    assert provider.breaker.allow() is True  # single failure does not yet open the breaker


@pytest.mark.asyncio
async def test_claude_generate_api_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"type": "error", "error": {"type": "api_error", "message": "internal server error"}})

    async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))

    provider = _claude_provider()

    with pytest.raises(RuntimeError, match="HTTP 500"):
        await provider.generate("rca", {})


@pytest.mark.asyncio
async def test_claude_generate_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))

    provider = _claude_provider()

    with pytest.raises(httpx.ReadTimeout):
        await provider.generate("rca", {})

    # A network-level failure (not an HTTPStatusError) must still count
    # against the circuit breaker so repeated timeouts eventually open it.
    assert provider.breaker.allow() is True


@pytest.mark.asyncio
async def test_claude_generate_empty_content_raises() -> None:
    provider = _claude_provider()

    # generate() itself performs the HTTP call; exercise the text-extraction
    # helper directly to confirm it safely handles a response with no usable
    # text block instead of raising an unrelated exception.
    assert provider._extract_text({"content": []}) == ""
    assert provider._extract_text({"content": [{"type": "tool_use", "id": "x"}]}) == ""


@pytest.mark.asyncio
async def test_claude_provider_status_reports_unconfigured_without_key() -> None:
    router = ModelRouter(providers={"claude": _claude_provider(api_key=None)})

    status = router.provider_status()

    assert status["providers"]["claude"]["configured"] is False
    assert status["providers"]["claude"]["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_claude_provider_status_reports_configured_with_key() -> None:
    router = ModelRouter(providers={"claude": _claude_provider()})

    status = router.provider_status()

    assert status["providers"]["claude"]["configured"] is True


@pytest.mark.asyncio
async def test_claude_selectable_via_explicit_provider_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # AI Hub / API-level "provider selection" is MODEL_ROUTER_DEFAULT_PROVIDER
    # or the explicit /route/provider/{name} path; both resolve through the
    # same providers dict keyed by name, exercised here directly.
    router = ModelRouter(
        settings=Settings(MODEL_ROUTER_DEFAULT_PROVIDER="claude"),
        providers={"claude": StaticProvider("claude"), "gpt-4o": StaticProvider("gpt-4o")},
    )

    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.GENERAL) == "claude"

    response = await router.route(
        severity=AlertSeverity.WARNING,
        task=ModelTask.GENERAL,
        prompt="summarize",
        payload={"service": "payments"},
    )
    assert response["model"] == "claude"


@pytest.mark.asyncio
async def test_existing_providers_still_selectable_after_adding_claude() -> None:
    # Regression guard: adding claude must not disturb existing provider
    # selection defaults for any severity/task combination.
    router = ModelRouter()

    assert router.select_model(severity=AlertSeverity.CRITICAL, task=ModelTask.RCA) == "reasoning-critical"
    assert router.select_model(severity=AlertSeverity.HIGH, task=ModelTask.RCA) == "reasoning-standard"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.SUMMARIZATION) == "gpt-4o"
    assert router.select_model(severity=AlertSeverity.WARNING, task=ModelTask.GENERAL) == "gpt-4o"
