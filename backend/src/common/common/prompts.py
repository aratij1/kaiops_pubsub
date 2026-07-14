from __future__ import annotations
import json
import os
from typing import Any


def _env_prompt(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip()
    return normalized or default

# Model instructions
SYSTEM_PROMPT_SRE = _env_prompt(
    "KAIOPS_SYSTEM_PROMPT_SRE",
    (
        "You are an enterprise SRE incident-resolution model. "
        "Use only the provided incident payload and return concise, actionable operational analysis."
    ),
)

# Task prompts
PROMPT_IDENTIFY_ROOT_CAUSE = _env_prompt("KAIOPS_PROMPT_IDENTIFY_ROOT_CAUSE", "Identify root cause")
PROMPT_ASSESS_IMPACT = _env_prompt("KAIOPS_PROMPT_ASSESS_IMPACT", "Assess customer and dependency impact")
PROMPT_RECOMMEND_REMEDIATION = _env_prompt("KAIOPS_PROMPT_RECOMMEND_REMEDIATION", "Recommend safest remediation")
PROMPT_SUMMARIZE_RCA = _env_prompt(
    "KAIOPS_PROMPT_SUMMARIZE_RCA",
    "Summarize root cause, impact, and next action in 2 concise operational sentences.",
)


def render_task_payload_prompt(task_prompt: str, payload: dict[str, Any]) -> str:
    """Render a compact deterministic prompt payload for model calls."""
    return json.dumps({"task": task_prompt, "payload": payload}, sort_keys=True, separators=(",", ":"), default=str)
