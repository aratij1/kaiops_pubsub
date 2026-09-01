from __future__ import annotations

import re
from pathlib import Path


def _resolution_service_block() -> str:
    compose = (Path(__file__).parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^  resolution-agent:\s*$\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\s*$|\Z)",
        compose,
    )
    assert match is not None, "docker-compose.yml must define resolution-agent"
    return match.group("body")


def _default_seconds(block: str, variable: str) -> int:
    match = re.search(rf"\$\{{{re.escape(variable)}:-(\d+)\}}", block)
    assert match is not None, f"resolution-agent must configure {variable} with a numeric default"
    return int(match.group(1))


def test_resolution_model_timeout_leaves_time_for_fallback_and_acknowledgement() -> None:
    block = _resolution_service_block()
    model_timeout = _default_seconds(block, "RESOLUTION_LLM_REQUEST_TIMEOUT_SECONDS")
    investigation_timeout = _default_seconds(block, "RESOLUTION_INVESTIGATION_MAX_DURATION_SECONDS")
    handler_timeout = _default_seconds(block, "RESOLUTION_HANDLER_TIMEOUT_SECONDS")

    assert model_timeout < handler_timeout
    assert handler_timeout - investigation_timeout - model_timeout >= 30


def test_synchronous_resolution_defaults_to_one_model_synthesis_path() -> None:
    block = _resolution_service_block()

    assert "RESOLUTION_DEEP_ANALYSIS_ENABLED: ${RESOLUTION_DEEP_ANALYSIS_ENABLED:-false}" in block
