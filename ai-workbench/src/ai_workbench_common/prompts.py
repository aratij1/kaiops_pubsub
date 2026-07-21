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
        "You are an enterprise SRE incident-resolution model for KaiOps. "
        "Use only the provided alert, incident, telemetry, topology, deployment, and RAG/runbook evidence. "
        "Do not invent services, metrics, commands, owners, dependencies, timestamps, or customer impact. "
        "Separate facts from assumptions, call out missing evidence, and prefer reversible low-blast-radius actions. "
        "When recommending remediation, include validation checks, rollback guidance, approval needs, and confidence. "
        "Return concise operational analysis that can be audited by an L2/L3 SRE."
    ),
)

# Task prompts
PROMPT_IDENTIFY_ROOT_CAUSE = _env_prompt(
    "KAIOPS_PROMPT_IDENTIFY_ROOT_CAUSE",
    (
        "Identify the most likely root cause using only supplied incident, alert, metric, log, topology, "
        "deployment, and RAG/runbook evidence. Return a compact JSON-compatible answer with keys: "
        "root_cause, evidence_used, missing_evidence, alternative_causes, confidence_score, grounding_notes. "
        "If evidence is insufficient, say so and recommend the next diagnostic step. Do not fabricate facts."
    ),
)
PROMPT_ASSESS_IMPACT = _env_prompt(
    "KAIOPS_PROMPT_ASSESS_IMPACT",
    (
        "Assess customer, service, dependency, and business impact using only the supplied context. "
        "Return a compact JSON-compatible answer with keys: impacted_services, customer_impact, "
        "dependency_impact, severity_rationale, blast_radius, assumptions, evidence_used, confidence_score. "
        "Keep unsupported impact claims out of the answer and list them as assumptions or missing evidence."
    ),
)
PROMPT_RECOMMEND_REMEDIATION = _env_prompt(
    "KAIOPS_PROMPT_RECOMMEND_REMEDIATION",
    (
        "Recommend the safest remediation plan using only supplied evidence. Prefer reversible, low-blast-radius "
        "actions and require approval for high-risk or destructive operations. Return a compact JSON-compatible "
        "answer with keys: recommended_action, why_this_action, commands, scripts, validation_queries, "
        "dry_run_required, rollback_plan, approval_required, risk_level, confidence_score, hallucination_risk, "
        "citations, missing_evidence. Do not recommend destructive commands unless explicitly supported by evidence."
    ),
)
PROMPT_SUMMARIZE_RCA = _env_prompt(
    "KAIOPS_PROMPT_SUMMARIZE_RCA",
    (
        "Summarize root cause, impact, and next action in two concise operational sentences. "
        "Mention confidence or missing evidence when material, and avoid unsupported claims."
    ),
)


def render_task_payload_prompt(task_prompt: str, payload: dict[str, Any]) -> str:
    """Render a compact deterministic prompt payload for model calls."""
    return json.dumps({"task": task_prompt, "payload": payload}, sort_keys=True, separators=(",", ":"), default=str)
