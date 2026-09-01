from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time as _time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from ai_workbench_common.model_evaluation import VertexEvaluationClient
from ai_workbench_common.prompts import SYSTEM_PROMPT_SRE, render_task_payload_prompt
from common.config import Settings, get_settings
from common.models import AlertSeverity
from common.resilience import CircuitBreaker
from common.telemetry import (
    LLM_CACHE_REQUESTS,
    LLM_COST_USD,
    LLM_FALLBACKS,
    LLM_GUARDRAIL_EVENTS,
    LLM_LATENCY,
    LLM_TOKENS,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_HASH = hashlib.sha256(SYSTEM_PROMPT_SRE.encode("utf-8")).hexdigest()[:16]
_SENSITIVE_KEY_PARTS = (
    "api_key", "apikey", "authorization", "credential", "password", "private_key",
    "secret", "session_cookie", "token",
)


def normalize_azure_openai_endpoint(value: str) -> str:
    endpoint = str(value or "").strip()
    if not endpoint:
        return ""
    parsed = urlsplit(endpoint)
    hostname = str(parsed.hostname or "").lower()
    if parsed.scheme != "https" or not hostname.endswith((".openai.azure.com", ".openai.azure.us", ".openai.azure.cn")):
        raise ValueError("AZURE_OPENAI_ENDPOINT must be an HTTPS Azure OpenAI resource root")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("AZURE_OPENAI_ENDPOINT must not contain credentials, query parameters, or fragments")
    if parsed.path not in {"", "/"}:
        raise ValueError("AZURE_OPENAI_ENDPOINT must not contain deployment or chat-completion paths")
    return urlunsplit(("https", parsed.netloc.lower(), "", "", ""))


def is_azure_openai_endpoint(value: str) -> bool:
    parsed = urlsplit(str(value or "").strip())
    hostname = str(parsed.hostname or "").lower()
    return hostname.endswith((".openai.azure.com", ".openai.azure.us", ".openai.azure.cn"))


def _sanitize_model_payload(value: Any) -> Any:
    """Remove secret values before evidence is cached or sent to any model provider."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.lower().replace("-", "_")
            sanitized[key] = (
                "[REDACTED]"
                if any(part in normalized for part in _SENSITIVE_KEY_PARTS)
                else _sanitize_model_payload(item)
            )
        return sanitized
    if isinstance(value, list):
        return [_sanitize_model_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_model_payload(item) for item in value]
    return value


def _guard_model_request(*, prompt: str, payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    if len(prompt) > settings.model_router_max_prompt_chars:
        LLM_GUARDRAIL_EVENTS.labels("prompt_too_large").inc()
        raise ValueError(f"prompt exceeds {settings.model_router_max_prompt_chars} characters")
    sanitized = _sanitize_model_payload(payload)
    payload_size = len(json.dumps(sanitized, sort_keys=True, default=str).encode("utf-8"))
    if payload_size > settings.model_router_max_payload_bytes:
        LLM_GUARDRAIL_EVENTS.labels("payload_too_large").inc()
        raise ValueError(f"payload exceeds {settings.model_router_max_payload_bytes} bytes")
    if sanitized != payload:
        LLM_GUARDRAIL_EVENTS.labels("secret_redacted").inc()
    return sanitized


def _observe_model_usage(provider: str, usage: dict[str, Any]) -> None:
    LLM_TOKENS.labels(provider, "input").inc(max(0, int(usage.get("input_tokens") or 0)))
    LLM_TOKENS.labels(provider, "output").inc(max(0, int(usage.get("output_tokens") or 0)))
    LLM_COST_USD.labels(provider).inc(max(0.0, float(usage.get("total_cost_usd") or 0.0)))


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


def _configured_evaluation_metrics(settings: Settings) -> list[str]:
    raw = str(getattr(settings, "azure_ai_evaluation_metrics", "") or "").strip()
    if not raw:
        # Backward-compatible default: behave exactly as the single-metric setting always has.
        return [str(getattr(settings, "azure_ai_evaluation_metric", "coherence") or "coherence").strip().lower()]
    metrics = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return metrics or [str(getattr(settings, "azure_ai_evaluation_metric", "coherence") or "coherence").strip().lower()]


def _configured_provider_name(value: str, fallback: str) -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


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
class GroqModelProvider(ModelProvider):
    model: str = "llama-3.3-70b-versatile"
    api_key: str | None = None
    base_url: str = "https://api.groq.com/openai/v1"
    timeout_seconds: float = 45.0
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    async def generate(self, prompt: str, payload: dict[str, Any]) -> ModelResponse:
        self._ensure_available()
        if not self.api_key:
            self.breaker.record_failure()
            raise RuntimeError(f"{self.name} unavailable: GROQ_API_KEY is not configured")

        prompt_text = render_task_payload_prompt(prompt, payload)
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_SRE},
                {"role": "user", "content": prompt_text},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
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
        choices = data.get("choices") if isinstance(data.get("choices"), list) else []
        content_text = ""
        if choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else {}
            content_text = str(message.get("content") or "")
        if not content_text:
            raise RuntimeError(f"{self.name} returned no text")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        model_usage = build_usage(
            provider=self.name,
            model=str(data.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens", estimate_tokens(prompt_text))),
            output_tokens=int(usage.get("completion_tokens", estimate_tokens(content_text))),
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
            estimated=not bool(usage),
        )
        return ModelResponse(content=content_text, usage=model_usage)


@dataclass
class AnthropicModelProvider(ModelProvider):
    """Anthropic Messages API. Distinct from the OpenAI-compatible providers:
    auth header is x-api-key (not Bearer), a required anthropic-version
    header, and the system prompt is a top-level "system" field rather than
    a message in the messages array."""

    model: str = "claude-sonnet-4-6"
    api_key: str | None = None
    base_url: str = "https://api.anthropic.com/v1"
    anthropic_version: str = "2023-06-01"
    max_tokens: int = 1024
    timeout_seconds: float = 45.0
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    async def generate(self, prompt: str, payload: dict[str, Any]) -> ModelResponse:
        self._ensure_available()
        if not self.api_key:
            self.breaker.record_failure()
            raise RuntimeError(f"{self.name} unavailable: ANTHROPIC_API_KEY is not configured")

        prompt_text = render_task_payload_prompt(prompt, payload)
        request_payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT_SRE,
            "messages": [
                {"role": "user", "content": prompt_text},
            ],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/messages",
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
        content_text = self._extract_text(data)
        if not content_text:
            raise RuntimeError(f"{self.name} returned no text")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        model_usage = build_usage(
            provider=self.name,
            model=str(data.get("model") or self.model),
            input_tokens=int(usage.get("input_tokens", estimate_tokens(prompt_text))),
            output_tokens=int(usage.get("output_tokens", estimate_tokens(content_text))),
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
            estimated=not bool(usage),
        )
        return ModelResponse(content=content_text, usage=model_usage)

    def _extract_text(self, data: dict[str, Any]) -> str:
        content = data.get("content") if isinstance(data.get("content"), list) else []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                return str(block.get("text"))
        return ""


@dataclass
class GeminiModelProvider(ModelProvider):
    model: str = "gemini-2.5-flash"
    api_key: str | None = None
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    timeout_seconds: float = 45.0
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    async def generate(self, prompt: str, payload: dict[str, Any]) -> ModelResponse:
        self._ensure_available()
        if not self.api_key:
            self.breaker.record_failure()
            raise RuntimeError(f"{self.name} unavailable: GEMINI_API_KEY is not configured")

        prompt_text = render_task_payload_prompt(prompt, payload)
        model_path = self.model if self.model.startswith("models/") else f"models/{self.model}"
        request_payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT_SRE}]},
            "contents": [{"parts": [{"text": prompt_text}]}],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/{model_path}:generateContent",
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
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
        content_text = self._extract_text(data)
        if not content_text:
            raise RuntimeError(f"{self.name} returned no text")
        usage_meta = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
        model_usage = build_usage(
            provider=self.name,
            model=self.model,
            input_tokens=int(usage_meta.get("promptTokenCount", estimate_tokens(prompt_text))),
            output_tokens=int(usage_meta.get("candidatesTokenCount", estimate_tokens(content_text))),
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
            estimated=not bool(usage_meta),
        )
        total_tokens = usage_meta.get("totalTokenCount")
        if isinstance(total_tokens, int):
            model_usage.total_tokens = total_tokens
        return ModelResponse(content=content_text, usage=model_usage)

    def _extract_text(self, data: dict[str, Any]) -> str:
        candidates = data.get("candidates") if isinstance(data.get("candidates"), list) else []
        for candidate in candidates:
            content = candidate.get("content") if isinstance(candidate, dict) else {}
            parts = content.get("parts") if isinstance(content, dict) else []
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict) and part.get("text"):
                    return str(part.get("text"))
        return ""


@dataclass
class AzureOpenAIModelProvider(ModelProvider):
    """Azure OpenAI chat-completions, distinct from OpenAIModelProvider: different
    auth header (api-key, not Bearer), different URL shape (deployment-scoped,
    not model-scoped), and Azure's response is the standard chat/completions
    shape rather than OpenAI's newer /responses shape."""

    model: str = "gpt-4o"
    api_key: str | None = None
    base_url: str = ""
    api_version: str = "2024-06-01"
    timeout_seconds: float = 45.0
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    async def generate(self, prompt: str, payload: dict[str, Any]) -> ModelResponse:
        self._ensure_available()
        if not self.api_key or not self.base_url:
            self.breaker.record_failure()
            raise RuntimeError(f"{self.name} unavailable: AZURE_OPENAI_ENDPOINT/AZURE_OPENAI_API_KEY are not configured")

        prompt_text = render_task_payload_prompt(prompt, payload)
        request_payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_SRE},
                {"role": "user", "content": prompt_text},
            ],
            "temperature": 0.2,
        }
        url = f"{self.base_url.rstrip('/')}/openai/deployments/{self.model}/chat/completions"
        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    url, params={"api-version": self.api_version}, headers=headers, json=request_payload
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
        choices = data.get("choices") if isinstance(data.get("choices"), list) else []
        content_text = ""
        if choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else {}
            content_text = str(message.get("content") or "")
        if not content_text:
            raise RuntimeError(f"{self.name} returned no text")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        model_usage = build_usage(
            provider=self.name,
            model=str(data.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens", estimate_tokens(prompt_text))),
            output_tokens=int(usage.get("completion_tokens", estimate_tokens(content_text))),
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
            estimated=not bool(usage),
        )
        return ModelResponse(content=content_text, usage=model_usage)


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
            "reasoning-critical": ["reasoning-standard", "gpt-5", "azure-openai", "gpt-4o", "gemini", "groq", "local-llama"],
            "reasoning-standard": ["reasoning-critical", "gpt-5", "azure-openai", "gpt-4o", "gemini", "groq", "local-llama"],
            "azure-openai": ["gpt-4o", "gpt-5", "gemini", "groq", "local-llama"],
            "gpt-5": ["azure-openai", "gpt-4o", "gemini", "groq", "local-llama"],
            "gpt-4o": ["azure-openai", "gpt-5", "gemini", "groq", "local-llama"],
            "gemini": ["azure-openai", "gpt-4o", "gpt-5", "groq", "local-llama"],
            "groq": ["azure-openai", "gpt-4o", "gemini", "local-llama"],
            "local-llama": ["azure-openai", "gpt-4o", "gemini", "groq"],
        }
    )
    prompt_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = field(default_factory=OrderedDict)
    evaluation_client: VertexEvaluationClient = field(default_factory=lambda: VertexEvaluationClient(get_settings()))
    _background_tasks: set[asyncio.Task[None]] = field(default_factory=set, repr=False, compare=False)
    _policy_cache: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    _policy_cache_path: str = field(default="", repr=False, compare=False)
    _policy_cache_mtime_ns: int = field(default=-1, repr=False, compare=False)

    def provider_status(self) -> dict[str, Any]:
        providers: dict[str, dict[str, Any]] = {}
        for name, provider in self.providers.items():
            breaker = provider.breaker
            configured = not isinstance(provider, UnconfiguredModelProvider)
            if hasattr(provider, "api_key"):
                configured = configured and bool(str(getattr(provider, "api_key") or "").strip())
            if hasattr(provider, "endpoint"):
                configured = configured and bool(str(getattr(provider, "endpoint") or "").strip())
            providers[name] = {
                "configured": configured,
                "healthy": bool(provider.healthy),
                "model": str(getattr(provider, "model", name) or name),
                "base_url": str(getattr(provider, "base_url", getattr(provider, "endpoint", "")) or ""),
                "circuit_open": not breaker.allow(),
                "failure_count": int(getattr(breaker, "_failures", 0) or 0),
                "reason": str(getattr(provider, "reason", "") or "") or None,
            }
        return {
            "providers": providers,
            "selected": {
                "critical": self.select_model(severity=AlertSeverity.CRITICAL, task=ModelTask.RCA),
                "rca": self.select_model(severity=AlertSeverity.WARNING, task=ModelTask.RCA),
                "default": self.select_model(severity=AlertSeverity.WARNING, task=ModelTask.GENERAL),
            },
            "prompt_cache": {
                "enabled": bool(self.settings.model_router_prompt_cache_enabled),
                "entries": len(self.prompt_cache),
                "ttl_seconds": self.settings.model_router_prompt_cache_ttl_seconds,
            },
        }

    async def _attach_evaluation(self, result: dict[str, Any], *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Best-effort: scores the response via Azure AI evaluation path.
        No-op unless Azure evaluation settings are enabled and configured."""
        if not self.evaluation_client.enabled:
            return result
        content = str(result.get("content") or "")
        if not content:
            return result
        metrics = _configured_evaluation_metrics(self.settings)
        evaluation_results = await asyncio.to_thread(
            self.evaluation_client.evaluate_many, content, metrics=metrics, context=None
        )
        if not evaluation_results:
            return result
        evaluations = [
            {
                "metric": item.metric,
                "score": item.score,
                "explanation": item.explanation,
                "confidence": item.confidence,
            }
            for item in evaluation_results
        ]
        # Kept singular for backward compatibility with existing /route response consumers;
        # "evaluations" (plural, full list) is new and additive.
        result["evaluation"] = evaluations[0]
        result["evaluations"] = evaluations
        self._publish_evaluation(result=result, payload=payload or {})
        return result

    async def _post_evaluation(self, body: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{self.settings.evaluation_service_url.rstrip('/')}/evaluations", json=body)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("evaluation_service_publish_failed", extra={"error": str(exc)})

    def _publish_evaluation(self, *, result: dict[str, Any], payload: dict[str, Any]) -> None:
        """Fire-and-forget: never awaited, never allowed to affect route()'s result."""
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        report = {
            "contract_version": "kaiops.evaluation.judge.v1",
            "provider": "llm-judge",
            "metrics": result.get("evaluations", []),
        }
        body = {
            "report": report,
            "agent": "model-router",
            "incident_id": str(payload.get("incident_id")) if payload.get("incident_id") else None,
            "recommendation_id": str(payload.get("recommendation_id")) if payload.get("recommendation_id") else None,
            "model_provider": str(result.get("model") or "") or None,
            "model_name": str(usage.get("model") or "") or None,
        }
        task = asyncio.create_task(self._post_evaluation(body))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def select_model(self, *, severity: AlertSeverity, task: ModelTask) -> str:
        policy_provider = self._evaluation_policy_provider(severity=severity, task=task)
        if policy_provider:
            return policy_provider
        if severity == AlertSeverity.CRITICAL:
            return _configured_provider_name(self.settings.model_router_critical_provider, "reasoning-critical")
        if task == ModelTask.RCA:
            return _configured_provider_name(self.settings.model_router_rca_provider, "reasoning-standard")
        return _configured_provider_name(self.settings.model_router_default_provider, "gpt-4o")

    def _evaluation_policy_provider(self, *, severity: AlertSeverity, task: ModelTask) -> str | None:
        """Use only a benchmark-qualified routing override from confirmed incidents."""
        raw_path = str(self.settings.model_router_evaluation_policy_path or "").strip()
        if not raw_path:
            return None
        try:
            path = Path(raw_path)
            mtime_ns = path.stat().st_mtime_ns
            if raw_path != self._policy_cache_path or mtime_ns != self._policy_cache_mtime_ns:
                self._policy_cache = json.loads(path.read_text(encoding="utf-8"))
                self._policy_cache_path = raw_path
                self._policy_cache_mtime_ns = mtime_ns
            policy = self._policy_cache
            if policy.get("contract_version") != "kaims.model-routing-policy.v1":
                return None
            routes = policy.get("routes") if isinstance(policy.get("routes"), dict) else {}
            keys = (f"{severity.value}:{task.value}", f"*:{task.value}", "default")
            route = next((routes[key] for key in keys if isinstance(routes.get(key), dict)), None)
            if not route or not route.get("eligible"):
                return None
            if int(route.get("cases") or 0) < self.settings.model_router_evaluation_min_cases:
                return None
            provider = str(route.get("provider") or "").strip()
            return provider if provider in self.providers else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("model_routing_policy_ignored", extra={"error_type": type(exc).__name__})
            return None

    async def route(
        self,
        *,
        severity: AlertSeverity,
        task: ModelTask,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        payload = _guard_model_request(prompt=prompt, payload=payload, settings=self.settings)
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
            LLM_CACHE_REQUESTS.labels("hit").inc()
            logger.debug("Prompt cache hit: %s", cache_key[:12])
            return _mark_usage_as_cached(cached)
        LLM_CACHE_REQUESTS.labels("miss").inc()
        candidates = list(dict.fromkeys([primary, *self.failover_chain.get(primary, [])]))
        errors: list[str] = []
        for provider_name in candidates:
            provider = self.providers.get(provider_name)
            if provider is None:
                errors.append(f"{provider_name}: provider is not registered")
                continue
            started = _time.monotonic()
            try:
                response = await provider.generate(prompt, payload)
                usage = response.usage.as_dict()
                usage["task"] = task.value
                usage["prompt_version"] = _SYSTEM_PROMPT_HASH
                LLM_LATENCY.labels(provider_name, task.value, "ok").observe(_time.monotonic() - started)
                _observe_model_usage(provider_name, usage)
                if provider_name != primary:
                    LLM_FALLBACKS.labels(primary, provider_name).inc()
                result = {"model": provider_name, "content": response.content, "usage": usage}
                result = await self._attach_evaluation(result, payload=payload)
                if self.settings.model_router_prompt_cache_enabled:
                    _prompt_cache_set(
                        cache_key,
                        result,
                        cache=self.prompt_cache,
                        max_entries=self.settings.model_router_prompt_cache_max_entries,
                    )
                return result
            except Exception as exc:
                LLM_LATENCY.labels(provider_name, task.value, "error").observe(_time.monotonic() - started)
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
        payload = _guard_model_request(prompt=prompt, payload=payload, settings=self.settings)
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
            LLM_CACHE_REQUESTS.labels("hit").inc()
            logger.debug("Prompt cache hit (provider): %s", cache_key[:12])
            return _mark_usage_as_cached(cached)
        LLM_CACHE_REQUESTS.labels("miss").inc()
        started = _time.monotonic()
        try:
            response = await provider.generate(prompt, payload)
        except Exception:
            LLM_LATENCY.labels(provider_name, task.value, "error").observe(_time.monotonic() - started)
            raise
        usage = response.usage.as_dict()
        usage["task"] = task.value
        usage["prompt_version"] = _SYSTEM_PROMPT_HASH
        LLM_LATENCY.labels(provider_name, task.value, "ok").observe(_time.monotonic() - started)
        _observe_model_usage(provider_name, usage)
        result = {"model": provider_name, "content": response.content, "usage": usage}
        result = await self._attach_evaluation(result, payload=payload)
        if self.settings.model_router_prompt_cache_enabled:
            _prompt_cache_set(
                cache_key,
                result,
                cache=self.prompt_cache,
                max_entries=self.settings.model_router_prompt_cache_max_entries,
            )
        return result


def build_default_providers(settings: Settings) -> dict[str, ModelProvider]:
    # Some existing installations stored an Azure OpenAI endpoint/key in the
    # legacy OPENAI_* variables. Detect the endpoint rather than sending an
    # Azure key to api.openai.com with Bearer authentication. This keeps the
    # migration backward compatible and selects the adapter with the correct
    # deployment URL and api-key header.
    legacy_openai_is_azure = is_azure_openai_endpoint(settings.openai_base_url)
    configured_azure_endpoint = settings.azure_openai_endpoint or (
        settings.openai_base_url if legacy_openai_is_azure else ""
    )
    azure_endpoint = normalize_azure_openai_endpoint(configured_azure_endpoint)
    azure_api_key = settings.azure_openai_api_key or (
        settings.openai_api_key if legacy_openai_is_azure else None
    )
    azure_deployment = settings.azure_openai_chat_deployment or settings.openai_gpt4o_model
    azure_selected = bool(azure_endpoint) or (
        settings.model_router_reasoning_backend.strip().lower() == "azure-openai"
        or settings.model_router_default_provider.strip().lower() == "azure-openai"
    )
    standard_azure_deployment = (
        settings.azure_openai_reasoning_standard_deployment or azure_deployment
    )
    critical_azure_deployment = (
        settings.azure_openai_reasoning_critical_deployment or azure_deployment
    )

    local_llama_provider: ModelProvider
    if settings.local_llm_enabled:
        local_llama_provider = OllamaModelProvider(
            name="local-llama",
            endpoint=settings.local_llm_endpoint,
            model=settings.local_llm_model,
            timeout_seconds=settings.llm_request_timeout_seconds,
        )
    else:
        local_llama_provider = UnconfiguredModelProvider(
            name="local-llama",
            reason="set LOCAL_LLM_ENABLED=true and LOCAL_LLM_ENDPOINT to use Ollama",
        )

    if azure_selected:
        standard_reasoning: ModelProvider = AzureOpenAIModelProvider(
            name="reasoning-standard", model=standard_azure_deployment,
            api_key=azure_api_key, base_url=azure_endpoint,
            api_version=settings.azure_openai_api_version, timeout_seconds=settings.llm_request_timeout_seconds,
        )
        critical_reasoning: ModelProvider = AzureOpenAIModelProvider(
            name="reasoning-critical", model=critical_azure_deployment,
            api_key=azure_api_key, base_url=azure_endpoint,
            api_version=settings.azure_openai_api_version, timeout_seconds=settings.llm_request_timeout_seconds,
        )
    else:
        standard_reasoning = OpenAIModelProvider(
            name="reasoning-standard", model=settings.reasoning_standard_model,
            api_key=settings.openai_api_key, base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            input_cost_per_million=settings.openai_gpt5_input_cost_per_million,
            output_cost_per_million=settings.openai_gpt5_output_cost_per_million,
        )
        critical_reasoning = OpenAIModelProvider(
            name="reasoning-critical", model=settings.reasoning_critical_model,
            api_key=settings.openai_api_key, base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            input_cost_per_million=settings.openai_gpt5_input_cost_per_million,
            output_cost_per_million=settings.openai_gpt5_output_cost_per_million,
        )

    return {
        "reasoning-standard": standard_reasoning,
        "reasoning-critical": critical_reasoning,
        "azure-openai": AzureOpenAIModelProvider(
            name="azure-openai",
            model=azure_deployment,
            api_key=azure_api_key,
            base_url=azure_endpoint,
            api_version=settings.azure_openai_api_version,
            timeout_seconds=settings.llm_request_timeout_seconds,
        ),
        "gpt-5": (AzureOpenAIModelProvider if azure_selected else OpenAIModelProvider)(
            name="gpt-5",
            model=azure_deployment if azure_selected else settings.openai_gpt5_model,
            api_key=azure_api_key if azure_selected else settings.openai_api_key,
            base_url=azure_endpoint if azure_selected else settings.openai_base_url,
            **({"api_version": settings.azure_openai_api_version} if azure_selected else {
                "input_cost_per_million": settings.openai_gpt5_input_cost_per_million,
                "output_cost_per_million": settings.openai_gpt5_output_cost_per_million,
            }),
            timeout_seconds=settings.llm_request_timeout_seconds,
        ),
        "gpt-4o": (AzureOpenAIModelProvider if azure_selected else OpenAIModelProvider)(
            name="gpt-4o",
            model=azure_deployment if azure_selected else settings.openai_gpt4o_model,
            api_key=azure_api_key if azure_selected else settings.openai_api_key,
            base_url=azure_endpoint if azure_selected else settings.openai_base_url,
            **({"api_version": settings.azure_openai_api_version} if azure_selected else {
                "input_cost_per_million": settings.openai_gpt4o_input_cost_per_million,
                "output_cost_per_million": settings.openai_gpt4o_output_cost_per_million,
            }),
            timeout_seconds=settings.llm_request_timeout_seconds,
        ),
        "claude": AnthropicModelProvider(
            name="claude",
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
            anthropic_version=settings.anthropic_version,
            timeout_seconds=settings.llm_request_timeout_seconds,
            input_cost_per_million=settings.anthropic_input_cost_per_million,
            output_cost_per_million=settings.anthropic_output_cost_per_million,
        ),
        "gemini": GeminiModelProvider(
            name="gemini",
            model=settings.gemini_model,
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            input_cost_per_million=settings.gemini_input_cost_per_million,
            output_cost_per_million=settings.gemini_output_cost_per_million,
        ),
        "groq": GroqModelProvider(
            name="groq",
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
            input_cost_per_million=settings.groq_input_cost_per_million,
            output_cost_per_million=settings.groq_output_cost_per_million,
        ),
        "local-llama": local_llama_provider,
    }
