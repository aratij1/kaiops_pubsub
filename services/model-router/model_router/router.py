from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time as _time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx
from common.config import Settings, get_settings
from common.models import AlertSeverity
from common.prompts import SYSTEM_PROMPT_SRE, render_task_payload_prompt
from common.resilience import CircuitBreaker

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_HASH = hashlib.sha256(SYSTEM_PROMPT_SRE.encode("utf-8")).hexdigest()[:16]


def _normalize_prompt(prompt: str) -> str:
    return " ".join(prompt.split()).strip()


def _provider_cache_identity(provider: str, model: str = "", base_url: str = "") -> str:
    normalized_base_url = base_url.rstrip("/")
    return f"{provider}|{model}|{normalized_base_url}|{_SYSTEM_PROMPT_HASH}"


def _make_prompt_cache_key(provider: str, task: str, prompt: str, payload: dict[str, Any]) -> str:
    """Stable SHA-256 key from provider+task+prompt+sorted payload."""
    payload_repr = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    raw = f"{provider}|{task}|{_normalize_prompt(prompt)}|{payload_repr}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _prompt_cache_get(key: str, *, cache: OrderedDict[str, tuple[float, dict[str, Any]]], ttl_seconds: float) -> dict[str, Any] | None:
    if key not in cache:
        return None
    ts, value = cache[key]
    if _time.monotonic() - ts > ttl_seconds:
        del cache[key]
        return None
    cache.move_to_end(key)
    return value


def _prompt_cache_set(
    key: str,
    value: dict[str, Any],
    *,
    cache: OrderedDict[str, tuple[float, dict[str, Any]]],
    max_entries: int,
) -> None:
    cache[key] = (_time.monotonic(), value)
    cache.move_to_end(key)
    while len(cache) > max_entries:
        cache.popitem(last=False)


def _mark_usage_as_cached(result: dict[str, Any]) -> dict[str, Any]:
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    cached_usage = dict(usage)
    cached_usage["cached"] = True
    cached_usage["cache_hit"] = True
    cached_usage["input_cost_usd"] = 0.0
    cached_usage["output_cost_usd"] = 0.0
    cached_usage["total_cost_usd"] = 0.0
    return {**result, "usage": cached_usage, "cached": True}


class ModelTask(StrEnum):
    RCA = "rca"
    IMPACT = "impact"
    FIX = "fix"
    SUMMARIZATION = "summarization"
    GENERAL = "general"


@dataclass
class ModelUsage:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    estimated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "input_cost_per_million": self.input_cost_per_million,
            "output_cost_per_million": self.output_cost_per_million,
            "input_cost_usd": round(self.input_cost_usd, 8),
            "output_cost_usd": round(self.output_cost_usd, 8),
            "total_cost_usd": round(self.total_cost_usd, 8),
            "estimated": self.estimated,
        }


@dataclass
class ModelResponse:
    content: str
    usage: ModelUsage


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def build_usage(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    input_cost_per_million: float,
    output_cost_per_million: float,
    estimated: bool = False,
) -> ModelUsage:
    input_cost = (input_tokens / 1_000_000) * input_cost_per_million
    output_cost = (output_tokens / 1_000_000) * output_cost_per_million
    return ModelUsage(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_cost_per_million=input_cost_per_million,
        output_cost_per_million=output_cost_per_million,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=input_cost + output_cost,
        estimated=estimated,
    )


def provider_error_message(provider: str, model: str, response: httpx.Response) -> str:
    url_without_query = str(response.request.url).split("?", 1)[0]
    body = response.text[:500]
    return f"{provider} model {model} returned HTTP {response.status_code} for {url_without_query}. Response: {body}"


@dataclass
class ModelProvider:
    name: str
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    healthy: bool = True

    async def generate(self, prompt: str, payload: dict[str, Any]) -> ModelResponse:
        raise NotImplementedError

    def _ensure_available(self) -> None:
        if not self.healthy or not self.breaker.allow():
            self.breaker.record_failure()
            raise RuntimeError(f"{self.name} unavailable")


@dataclass
class UnconfiguredModelProvider(ModelProvider):
    reason: str = "provider is not configured"

    async def generate(self, prompt: str, payload: dict[str, Any]) -> ModelResponse:
        self.breaker.record_failure()
        raise RuntimeError(f"{self.name} unavailable: {self.reason}")


@dataclass
class OpenAIModelProvider(ModelProvider):
    model: str = "gpt-4o"
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 45.0
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    async def generate(self, prompt: str, payload: dict[str, Any]) -> ModelResponse:
        self._ensure_available()
        if not self.api_key:
            self.breaker.record_failure()
            raise RuntimeError(f"{self.name} unavailable: OPENAI_API_KEY is not configured")

        request_payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_SRE,
                },
                {
                    "role": "user",
                    "content": render_task_payload_prompt(prompt, payload),
                },
            ],
        }
        base_url = self.base_url.rstrip("/")
        is_azure_openai = ".openai.azure.com" in base_url.lower()
        if is_azure_openai and not base_url.lower().endswith("/openai/v1"):
            base_url = f"{base_url}/openai/v1"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if is_azure_openai:
            headers["api-key"] = self.api_key
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{base_url}/responses",
                    headers=headers,
                    json=request_payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            self.breaker.record_failure()
            raise RuntimeError(provider_error_message(self.name, self.model, exc.response)) from exc
        except Exception:
            self.breaker.record_failure()
            raise

        self.breaker.record_success()
        content = data.get("output_text")
        content_text = str(content) if content else self._extract_response_text(data)
        usage = data.get("usage", {})
        model_usage = build_usage(
            provider=self.name,
            model=self.model,
            input_tokens=int(usage.get("input_tokens", estimate_tokens(json.dumps(request_payload)))),
            output_tokens=int(usage.get("output_tokens", estimate_tokens(content_text))),
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
            estimated=not bool(usage),
        )
        return ModelResponse(content=content_text, usage=model_usage)

    def _extract_response_text(self, data: dict[str, Any]) -> str:
        output = data.get("output", [])
        for item in output:
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    return str(text)
        raise RuntimeError(f"{self.name} returned no text")


@dataclass
class OllamaModelProvider(ModelProvider):
    endpoint: str = "http://ollama:11434"
    model: str = "llama3.1"
    timeout_seconds: float = 45.0

    async def generate(self, prompt: str, payload: dict[str, Any]) -> ModelResponse:
        self._ensure_available()
        request_payload = {
            "model": self.model,
            "prompt": render_task_payload_prompt(prompt, payload),
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.endpoint.rstrip('/')}/api/generate", json=request_payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            self.breaker.record_failure()
            raise RuntimeError(provider_error_message(self.name, self.model, exc.response)) from exc
        except Exception:
            self.breaker.record_failure()
            raise

        self.breaker.record_success()
        content = data.get("response")
        if not content:
            raise RuntimeError(f"{self.name} returned no text")
        content_text = str(content)
        usage = build_usage(
            provider=self.name,
            model=self.model,
            input_tokens=int(data.get("prompt_eval_count", estimate_tokens(request_payload["prompt"]))),
            output_tokens=int(data.get("eval_count", estimate_tokens(content_text))),
            input_cost_per_million=0.0,
            output_cost_per_million=0.0,
            estimated=not bool(data.get("prompt_eval_count")),
        )
        return ModelResponse(content=content_text, usage=usage)


@dataclass
class ModelRouter:
    providers: dict[str, ModelProvider] = field(default_factory=lambda: build_default_providers(get_settings()))
    settings: Settings = field(default_factory=get_settings)
    failover_chain: dict[str, list[str]] = field(
        default_factory=lambda: {
            "gpt-5": ["gpt-4o", "local-llama"],
            "local-llama": ["gpt-4o"],
            "gpt-4o": ["gpt-5", "local-llama"],
        }
    )
    prompt_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = field(default_factory=OrderedDict)

    def select_model(self, *, severity: AlertSeverity, task: ModelTask) -> str:
        if severity == AlertSeverity.CRITICAL:
            return "gpt-5"
        if task == ModelTask.RCA:
            return "gpt-4o"
        return "gpt-4o"

    async def route(
        self,
        *,
        severity: AlertSeverity,
        task: ModelTask,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        primary = self.select_model(severity=severity, task=task)
        primary_provider = self.providers.get(primary)
        provider_identity = _provider_cache_identity(
            primary,
            getattr(primary_provider, "model", primary) if primary_provider is not None else primary,
            getattr(primary_provider, "base_url", getattr(primary_provider, "endpoint", "")) if primary_provider is not None else "",
        )
        cache_key = _make_prompt_cache_key(provider_identity, task.value, prompt, payload)
        cached = None
        if self.settings.model_router_prompt_cache_enabled:
            cached = _prompt_cache_get(
                cache_key,
                cache=self.prompt_cache,
                ttl_seconds=self.settings.model_router_prompt_cache_ttl_seconds,
            )
        if cached is not None:
            logger.debug("Prompt cache hit: %s", cache_key[:12])
            return _mark_usage_as_cached(cached)
        candidates = list(dict.fromkeys([primary, *self.failover_chain.get(primary, [])]))
        errors: list[str] = []
        for provider_name in candidates:
            provider = self.providers.get(provider_name)
            if provider is None:
                errors.append(f"{provider_name}: provider is not registered")
                continue
            try:
                response = await provider.generate(prompt, payload)
                usage = response.usage.as_dict()
                usage["task"] = task.value
                result = {"model": provider_name, "content": response.content, "usage": usage}
                if self.settings.model_router_prompt_cache_enabled:
                    _prompt_cache_set(
                        cache_key,
                        result,
                        cache=self.prompt_cache,
                        max_entries=self.settings.model_router_prompt_cache_max_entries,
                    )
                return result
            except Exception as exc:
                errors.append(f"{provider_name}: {exc}")

        raise RuntimeError("; ".join(errors))

    async def route_provider(
        self,
        *,
        provider_name: str,
        task: ModelTask,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        provider = self.providers.get(provider_name)
        if provider is None:
            raise RuntimeError(f"{provider_name} provider is not registered")
        provider_identity = _provider_cache_identity(
            provider.name,
            getattr(provider, "model", provider.name),
            getattr(provider, "base_url", getattr(provider, "endpoint", "")),
        )
        cache_key = _make_prompt_cache_key(provider_identity, task.value, prompt, payload)
        cached = None
        if self.settings.model_router_prompt_cache_enabled:
            cached = _prompt_cache_get(
                cache_key,
                cache=self.prompt_cache,
                ttl_seconds=self.settings.model_router_prompt_cache_ttl_seconds,
            )
        if cached is not None:
            logger.debug("Prompt cache hit (provider): %s", cache_key[:12])
            return _mark_usage_as_cached(cached)
        response = await provider.generate(prompt, payload)
        usage = response.usage.as_dict()
        usage["task"] = task.value
        result = {"model": provider_name, "content": response.content, "usage": usage}
        if self.settings.model_router_prompt_cache_enabled:
            _prompt_cache_set(
                cache_key,
                result,
                cache=self.prompt_cache,
                max_entries=self.settings.model_router_prompt_cache_max_entries,
            )
        return result


def build_default_providers(settings: Settings) -> dict[str, ModelProvider]:
    local_llama_provider: ModelProvider
    if settings.local_llm_enabled:
        local_llama_provider = OllamaModelProvider(
            name="local-llama",
            endpoint=settings.local_llm_endpoint,
            timeout_seconds=settings.llm_request_timeout_seconds,
        )
    else:
        local_llama_provider = UnconfiguredModelProvider(
            name="local-llama",
            reason="set LOCAL_LLM_ENABLED=true and LOCAL_LLM_ENDPOINT to use Ollama",
        )

    return {
        "gpt-5": OpenAIModelProvider(
            name="gpt-5",
            model=settings.openai_gpt5_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            input_cost_per_million=settings.openai_gpt5_input_cost_per_million,
            output_cost_per_million=settings.openai_gpt5_output_cost_per_million,
        ),
        "gpt-4o": OpenAIModelProvider(
            name="gpt-4o",
            model=settings.openai_gpt4o_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            input_cost_per_million=settings.openai_gpt4o_input_cost_per_million,
            output_cost_per_million=settings.openai_gpt4o_output_cost_per_million,
        ),
        "claude": UnconfiguredModelProvider(
            name="claude",
            reason="set ANTHROPIC_API_KEY and add a Claude provider implementation",
        ),
        "local-llama": local_llama_provider,
    }
