"""Manual, safe connectivity check for the Anthropic Claude provider.

Reads ANTHROPIC_API_KEY from the environment (or .env, via common.config.Settings)
and makes exactly one real request to the live Anthropic Messages API. Never
prints, logs, or otherwise exposes the key value.

Usage (from the repo root, with ANTHROPIC_API_KEY set in the environment or .env):
    python scripts/check_anthropic_connectivity.py

Exit code 0 on success, 1 on any failure (missing key, network error, API error).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src" / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai-workbench" / "src" / "model-router"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai-workbench" / "src"))

import httpx  # noqa: E402

from common.config import get_settings  # noqa: E402
from model_router.router import AnthropicModelProvider  # noqa: E402


async def main() -> int:
    settings = get_settings()

    if not settings.anthropic_api_key:
        print("Anthropic connectivity: FAIL")
        print("Reason: ANTHROPIC_API_KEY is not set (check your .env or environment)")
        return 1

    provider = AnthropicModelProvider(
        name="claude",
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
        anthropic_version=settings.anthropic_version,
        timeout_seconds=30.0,
        input_cost_per_million=settings.anthropic_input_cost_per_million,
        output_cost_per_million=settings.anthropic_output_cost_per_million,
    )

    try:
        response = await provider.generate("Hello, world", {})
    except httpx.TimeoutException:
        print("Anthropic connectivity: FAIL")
        print(f"Model: {settings.anthropic_model}")
        print("Reason: request timed out")
        return 1
    except RuntimeError as exc:
        print("Anthropic connectivity: FAIL")
        print(f"Model: {settings.anthropic_model}")
        # RuntimeError messages here come from provider_error_message(), which
        # already truncates the response body and never includes the API key.
        print(f"Reason: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - report any unexpected failure, still without the key
        print("Anthropic connectivity: FAIL")
        print(f"Model: {settings.anthropic_model}")
        print(f"Reason: {exc.__class__.__name__}: {exc}")
        return 1

    print("Anthropic connectivity: PASS")
    print(f"Model: {response.usage.model}")
    print(f"Response received: {'YES' if response.content else 'NO'}")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
