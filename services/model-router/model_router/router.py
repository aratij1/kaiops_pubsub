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
from common.resilience import CircuitBreaker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process prompt response cache (client-side prompt caching)
# ---------------------------------------------------------------------------
_PROMPT_CACHE_MAX: int = 512
_PROMPT_CACHE_TTL: float = 300.0  # 5 minutes
_prompt_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()


def _make_prompt_cache_key(provider: str, task: str, prompt: str, payload: dict[str, Any]) -> str:
    """Stable SHA-256 key from provider+task+prompt+sorted payload."""
    payload_repr = json.dumps(payload, sort_keys=True, default=str)
    raw = f"{provider}|{task}|{prompt}|{payload_repr}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _prompt_cache_get(key: str) -> dict[str, Any] | None:
    if key not in _prompt_cache:
        return None
    ts, value = _prompt_cache[key]
    if _time.monotonic() - ts > _PROMPT_CACHE_TTL:
        del _prompt_cache[key]
        return None
    _prompt_cache.move_to_end(key)
    return value


def _prompt_cache_set(key: str, value: dict[str, Any]) -> None:
    _prompt_cache[key] = (_time.monotonic(), value)
    _prompt_cache.move_to_end(key)
    while len(_prompt_cache) > _PROMPT_CACHE_MAX:
        _prompt_cache.popitem(last=False)


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
                    "content": (
                        "You are an enterprise SRE incident-resolution model. "
                        "Use only the provided incident payload and return concise, actionable operational analysis."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"task": prompt, "payload": payload}, default=str),
                },
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/responses",
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
            "prompt": json.dumps({"task": prompt, "payload": payload}, default=str),
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
    failover_chain: dict[str, list[str]] = field(
        default_factory=lambda: {
            "gpt-5": ["gpt-4o", "local-llama"],
            "local-llama": ["gpt-4o"],
            "gpt-4o": ["gpt-5", "local-llama"],
        }
    )

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
        cache_key = _make_prompt_cache_key(primary, task.value, prompt, payload)
        cached = _prompt_cache_get(cache_key)
        if cached is not None:
            logger.debug("Prompt cache hit: %s", cache_key[:12])
            return {**cached, "cached": True}
        candidates = list(dict.fromkeys([primary, *self.failover_chain.get(primary, [])]))
        candidate_tasks = {
            name: asyncio.create_task(self.providers[name].generate(prompt, payload))
            for name in candidates
        }
        errors: list[str] = []
        try:
            pending = set(candidate_tasks.values())
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for completed in done:
                    provider_name = next(name for name, task_obj in candidate_tasks.items() if task_obj is completed)
                    try:
                        response = completed.result()
                        usage = response.usage.as_dict()
                        usage["task"] = task.value
                        result = {"model": provider_name, "content": response.content, "usage": usage}
                        _prompt_cache_set(cache_key, result)
                        return result
                    except Exception as exc:
                        errors.append(f"{provider_name}: {exc}")
            raise RuntimeError("; ".join(errors))
        finally:
            for task_obj in candidate_tasks.values():
                if not task_obj.done():
                    task_obj.cancel()

    async def route_provider(
        self,
        *,
        provider_name: str,
        task: ModelTask,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        cache_key = _make_prompt_cache_key(provider_name, task.value, prompt, payload)
        cached = _prompt_cache_get(cache_key)
        if cached is not None:
            logger.debug("Prompt cache hit (provider): %s", cache_key[:12])
            return {**cached, "cached": True}
        provider = self.providers.get(provider_name)
        if provider is None:
            raise RuntimeError(f"{provider_name} provider is not registered")
        response = await provider.generate(prompt, payload)
        usage = response.usage.as_dict()
        usage["task"] = task.value
        result = {"model": provider_name, "content": response.content, "usage": usage}
        _prompt_cache_set(cache_key, result)
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
