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


def test_synchronous_resolution_defaults_to_agent_generated_analysis() -> None:
    block = _resolution_service_block()

    assert "RESOLUTION_DEEP_ANALYSIS_ENABLED: ${RESOLUTION_DEEP_ANALYSIS_ENABLED:-true}" in block


def test_local_investigation_budget_can_query_every_evidence_plane_once() -> None:
    block = _resolution_service_block()
    step_budget = _default_seconds(block, "RESOLUTION_INVESTIGATION_MAX_STEPS")
    tool_call_budget = _default_seconds(block, "RESOLUTION_INVESTIGATION_MAX_TOOL_CALLS")

    # IterativeInvestigator has ten bounded source planes. The runtime must not
    # stop before each required plane has had one read-only collection attempt.
    assert step_budget >= 10
    assert tool_call_budget >= step_budget
