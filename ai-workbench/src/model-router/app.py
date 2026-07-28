from __future__ import annotations

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


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_detected_error_messages(payload: dict[str, Any]) -> list[str]:
    detected = payload.get("detected_errors")
    if not isinstance(detected, list):
        return []
    messages: list[str] = []
    for item in detected:
        if isinstance(item, dict):
            message = _first_non_empty(item.get("message"), item.get("error"), item.get("summary"))
            if message:
                messages.append(message)
        elif isinstance(item, (str, int, float)):
            text = str(item).strip()
            if text:
                messages.append(text)
    return _normalize_items(messages)


def _extract_recent_changes(payload: dict[str, Any]) -> list[str]:
    rows = payload.get("recent_changes")
    if not isinstance(rows, list):
        return []
    values: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            text = _first_non_empty(row.get("message"), row.get("title"), row.get("change"))
            if text:
                values.append(text)
        elif isinstance(row, (str, int, float)):
            text = str(row).strip()
            if text:
                values.append(text)
    return _normalize_items(values)


def _first_sentence(text: str) -> str:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    return parts[0] if parts else text.strip()


def _build_fallback_content(request: RouteRequest, error_message: str) -> str:
    payload = request.payload if isinstance(request.payload, dict) else {}
    user_prompt = str(payload.get("user_prompt") or request.prompt or "").strip()
    task = str(request.task.value if hasattr(request.task, "value") else request.task or "general").strip().lower()
    kind = str(payload.get("kind") or "incident").strip().lower()
    services = _first_non_empty(payload.get("services"), payload.get("service"))
    alert_type = str(payload.get("alert_type") or "").strip() or "availability"
    alert_summary = _first_non_empty(payload.get("summary"), payload.get("description"), payload.get("alert_description"), user_prompt)
    detected_errors = _extract_detected_error_messages(payload)
    recent_changes = _extract_recent_changes(payload)
    dependencies = _normalize_items(payload.get("dependencies") or [])
    service_display = services or "the affected service"

    summary = _first_sentence(user_prompt)[:260] if user_prompt else "Generated fallback SRE draft."
    title_seed = re.sub(r"^[-*#\d.\s]+", "", user_prompt).split()
    title = " ".join(title_seed[:8]).strip()[:160] if title_seed else f"{kind.title()} Draft"

    commands = _extract_tagged_values(user_prompt, "cmd|command")
    scripts = _extract_tagged_values(user_prompt, "script|ps1|sh|bash")
    queries = _extract_tagged_values(user_prompt, "query|sql")

    likely_cause = _first_non_empty(
        detected_errors[0] if detected_errors else "",
        recent_changes[0] if recent_changes else "",
        f"{service_display} shows a {alert_type} degradation signal",
    )
    impact_hint = (
        f"{service_display} may be affecting dependent services: {', '.join(dependencies[:3])}."
        if dependencies
        else f"{service_display} may degrade user-facing availability or latency until mitigated."
    )
    action_hint = (
        f"Start with low-risk mitigation for {service_display} and validate key SLOs after each change."
    )

    if task == "rca":
        content_lines = [
            "Fallback RCA (model unavailable)",
            f"Signal: {alert_summary or summary or 'Service alert condition detected.'}",
            f"Most likely cause: {likely_cause}.",
            "Confidence: low until model provider recovers and evidence-cited RCA is regenerated.",
        ]
    elif task == "impact":
        content_lines = [
            "Fallback impact analysis (model unavailable)",
            f"Signal: {alert_summary or summary or 'Service alert condition detected.'}",
            f"Impact estimate: {impact_hint}",
            "Confidence: low because impact could not be validated with model-backed synthesis.",
        ]
    elif task == "fix":
        content_lines = [
            "Fallback remediation guidance (model unavailable)",
            f"Signal: {alert_summary or summary or 'Service alert condition detected.'}",
            f"Recommended action: {action_hint}",
            "Follow approved runbook/rollback SOP and record each validation step.",
        ]
    else:
        content_lines = [
            "Fallback response (model unavailable)",
            f"Scenario: {alert_summary or summary or 'Service alert condition detected.'}",
            f"Service: {service_display}",
            f"Best-effort hypothesis: {likely_cause}.",
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
    # Return plain, human-readable text (not the raw JSON blob) so that any caller that
    # forwards this content verbatim -- e.g. an approval-requested email -- shows a clean
    # message instead of a dumped dict.
    return doc["content"]


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
