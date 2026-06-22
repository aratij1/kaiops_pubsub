from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx
from common.config import Settings, get_settings
from common.models import AlertSeverity
from common.resilience import CircuitBreaker


logger = logging.getLogger(__name__)


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
class GeminiModelProvider(ModelProvider):
    model: str = "gemini-2.5-flash"
    api_key: str | None = None
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    timeout_seconds: float = 45.0
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    retired_model_fallback: str = "gemini-2.5-flash"

    async def generate(self, prompt: str, payload: dict[str, Any]) -> ModelResponse:
        self._ensure_available()
        if not self.api_key:
            self.breaker.record_failure()
            raise RuntimeError(f"{self.name} unavailable: GEMINI_API_KEY is not configured")

        text_payload = json.dumps({"task": prompt, "payload": payload}, default=str)
        request_payload = {"contents": [{"parts": [{"text": text_payload}]}]}
        headers = {"x-goog-api-key": self.api_key}
        try:
            data, model_used = await self._generate_with_retry(
                request_payload=request_payload,
                headers=headers,
            )
        except httpx.HTTPStatusError as exc:
            self.breaker.record_failure()
            raise RuntimeError(provider_error_message(self.name, self.model, exc.response)) from exc
        except Exception:
            self.breaker.record_failure()
            raise

        self.breaker.record_success()
        content_text = self._extract_gemini_text(data)
        usage_metadata = data.get("usageMetadata", {})
        usage = build_usage(
            provider=self.name,
            model=model_used,
            input_tokens=int(usage_metadata.get("promptTokenCount", estimate_tokens(text_payload))),
            output_tokens=int(usage_metadata.get("candidatesTokenCount", estimate_tokens(content_text))),
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
            estimated=not bool(usage_metadata),
        )
        return ModelResponse(content=content_text, usage=usage)

    async def _generate_with_retry(
        self,
        *,
        request_payload: dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], str]:
        try:
            data = await self._call_generate(model=self.model, request_payload=request_payload, headers=headers)
            return data, self.model
        except httpx.HTTPStatusError as exc:
            if not self._should_retry_retired_model(exc):
                raise

            logger.warning(
                "Gemini model '%s' appears retired; retrying once with '%s'.",
                self.model,
                self.retired_model_fallback,
            )
            data = await self._call_generate(
                model=self.retired_model_fallback,
                request_payload=request_payload,
                headers=headers,
            )
            return data, self.retired_model_fallback

    async def _call_generate(
        self,
        *,
        model: str,
        request_payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/models/{model}:generateContent",
                headers=headers,
                json=request_payload,
            )
            response.raise_for_status()
            return response.json()

    def _should_retry_retired_model(self, exc: httpx.HTTPStatusError) -> bool:
        if exc.response.status_code != 404:
            return False
        if not self.model.startswith("gemini-2.0"):
            return False
        if self.model == self.retired_model_fallback:
            return False

        body = exc.response.text.lower()
        return "no longer available" in body or "not_found" in body

    def _extract_gemini_text(self, data: dict[str, Any]) -> str:
        candidates = data.get("candidates", [])
        for candidate in candidates:
            for part in candidate.get("content", {}).get("parts", []):
                if part.get("text"):
                    return str(part["text"])
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

        text_payload = json.dumps({"task": prompt, "payload": payload}, default=str)
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a concise SRE incident triage model."},
                {"role": "user", "content": text_payload},
            ],
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
        content_text = str(data["choices"][0]["message"]["content"])
        usage_data = data.get("usage", {})
        usage = build_usage(
            provider=self.name,
            model=self.model,
            input_tokens=int(usage_data.get("prompt_tokens", estimate_tokens(text_payload))),
            output_tokens=int(usage_data.get("completion_tokens", estimate_tokens(content_text))),
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
            estimated=not bool(usage_data),
        )
        return ModelResponse(content=content_text, usage=usage)


@dataclass
class ModelRouter:
    providers: dict[str, ModelProvider] = field(default_factory=lambda: build_default_providers(get_settings()))
    failover_chain: dict[str, list[str]] = field(
        default_factory=lambda: {
            "gpt-5": ["gpt-4o", "gemini", "groq", "local-llama", "claude"],
            "claude": ["gpt-5", "gpt-4o", "gemini", "groq", "local-llama"],
            "gemini": ["gpt-4o", "gpt-5", "groq", "local-llama"],
            "groq": ["gpt-4o", "gemini", "gpt-5", "local-llama"],
            "local-llama": ["groq", "gpt-4o"],
            "gpt-4o": ["gpt-5", "gemini", "groq", "local-llama"],
        }
    )

    def select_model(self, *, severity: AlertSeverity, task: ModelTask) -> str:
        if severity == AlertSeverity.CRITICAL:
            return "gpt-5"
        if task == ModelTask.RCA:
            return "claude"
        if task == ModelTask.SUMMARIZATION:
            return "gemini"
        return "groq"

    async def route(
        self,
        *,
        severity: AlertSeverity,
        task: ModelTask,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        primary = self.select_model(severity=severity, task=task)
        candidates = [primary, *self.failover_chain.get(primary, [])]
        errors: list[str] = []
        for name in candidates:
            try:
                response = await self.providers[name].generate(prompt, payload)
                usage = response.usage.as_dict()
                usage["task"] = task.value
                return {"model": name, "content": response.content, "usage": usage}
            except Exception as exc:
                errors.append(f"{name}: {exc}")
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
        response = await provider.generate(prompt, payload)
        usage = response.usage.as_dict()
        usage["task"] = task.value
        return {"model": provider_name, "content": response.content, "usage": usage}


def build_default_providers(settings: Settings) -> dict[str, ModelProvider]:
    if settings.gemini_model.startswith("gemini-2.0"):
        logger.warning(
            "Configured GEMINI_MODEL '%s' may be retired and can return HTTP 404. "
            "Use GEMINI_MODEL='gemini-2.5-flash' or another currently available Gemini model.",
            settings.gemini_model,
        )

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
