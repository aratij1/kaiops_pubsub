from __future__ import annotations

import json
import re
from typing import Any

from common.config import get_settings
from common.models import AlertSeverity
from common.service import create_app
from model_router import ModelRouter, ModelTask
from pydantic import BaseModel

settings = get_settings()
settings.service_name = "model-router"
router = ModelRouter()
app = create_app(title="KaiMS Model Router", settings=settings)


class RouteRequest(BaseModel):
    severity: AlertSeverity
    task: ModelTask
    prompt: str
    payload: dict = {}


def _normalize_items(value: Any) -> list[str]:
    if isinstance(value, list):
        values = [str(item or "").strip() for item in value]
    else:
        values = [part.strip() for part in str(value or "").splitlines()]
    out: list[str] = []
    for item in values:
        cleaned = re.sub(r"^[-*]\s*", "", item).strip()
        if cleaned and not any(existing.lower() == cleaned.lower() for existing in out):
            out.append(cleaned)
    return out


def _extract_tagged_values(text: str, tags: str) -> list[str]:
    regex = re.compile(rf"\b(?:{tags})\s*[:\-]\s*([^\n;|]+)", re.IGNORECASE)
    return _normalize_items([match.group(1) for match in regex.finditer(text)])


def _first_sentence(text: str) -> str:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    return parts[0] if parts else text.strip()


def _build_fallback_content(request: RouteRequest, error_message: str) -> str:
    payload = request.payload if isinstance(request.payload, dict) else {}
    user_prompt = str(payload.get("user_prompt") or request.prompt or "").strip()
    kind = str(payload.get("kind") or "incident").strip().lower()
    services = str(payload.get("services") or "").strip()
    alert_type = str(payload.get("alert_type") or "").strip() or "availability"

    summary = _first_sentence(user_prompt)[:260] if user_prompt else "Generated fallback SRE draft."
    title_seed = re.sub(r"^[-*#\d.\s]+", "", user_prompt).split()
    title = " ".join(title_seed[:8]).strip()[:160] if title_seed else f"{kind.title()} Draft"

    commands = _extract_tagged_values(user_prompt, "cmd|command")
    scripts = _extract_tagged_values(user_prompt, "script|ps1|sh|bash")
    queries = _extract_tagged_values(user_prompt, "query|sql")

    content_lines = [
        f"Scenario: {summary or 'Service alert condition detected.'}",
        "",
        "Immediate Triage:",
        "1) Validate alert signal, scope, and impacted user journey.",
        "2) Check recent deployment/config changes in affected services.",
        "3) Capture current health indicators before remediation.",
        "",
        "Remediation:",
        "1) Apply a low-risk mitigation (rollback, scale, or route shift).",
        "2) Re-validate error rate/latency/saturation after each action.",
        "3) Escalate to service owner if SLO remains breached.",
        "",
        "Verification:",
        "1) Confirm recovery in dashboards and logs.",
        "2) Confirm incident ticket timeline with actions taken.",
        "3) Document residual risk and follow-up work.",
    ]

    doc = {
        "title": title or f"{kind.title()} Draft",
        "summary": summary or "Generated fallback SRE draft.",
        "content": "\n".join(content_lines).strip(),
        "commands": commands,
        "scripts": scripts,
        "queries": queries,
        "metadata": {
            "kind": kind,
            "alert_type": alert_type,
            "services": services,
            "fallback": True,
            "fallback_reason": error_message[:400],
        },
    }
    return json.dumps(doc)


@app.post("/route")
async def route(request: RouteRequest) -> dict[str, Any]:
    try:
        return await router.route(
            severity=request.severity,
            task=request.task,
            prompt=request.prompt,
            payload=request.payload,
        )
    except Exception as exc:
        return {
            "model": "heuristic-fallback",
            "content": _build_fallback_content(request, str(exc)),
            "usage": {
                "provider": "heuristic-fallback",
                "model": "heuristic-fallback",
                "task": request.task.value,
                "estimated": True,
                "fallback": True,
            },
        }


@app.post("/route/provider/{provider_name}")
async def route_provider(provider_name: str, request: RouteRequest) -> dict[str, Any]:
    try:
        return await router.route_provider(
            provider_name=provider_name,
            task=request.task,
            prompt=request.prompt,
            payload=request.payload,
        )
    except Exception as exc:
        return {
            "model": "provider-error",
            "content": "",
            "error": str(exc),
            "usage": {
                "provider": provider_name,
                "model": "provider-error",
                "task": request.task.value,
                "estimated": True,
                "fallback": False,
            },
        }


@app.get("/providers/status")
async def providers_status() -> dict[str, Any]:
    return router.provider_status()
