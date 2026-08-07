"""Phase 0 Copilot: deterministic intent matching and answer composition.

No LLM/model-router calls here by design -- these three intents are direct
data lookups against data the existing Capacity/Assignment/Onboarding APIs
already expose. This module is pure (no I/O, no FastAPI imports) so intent
matching and answer text can be unit tested without a running app or DB.
"""

from __future__ import annotations

import re
from typing import Any, Literal

Intent = Literal["capacity", "assignment", "onboarding"]

_CAPACITY_PATTERNS = (
    re.compile(r"\bcapacity\b", re.IGNORECASE),
    re.compile(r"\bwho\s+(has|have)\s+(capacity|availability|bandwidth)\b", re.IGNORECASE),
    re.compile(r"\bavailab(le|ility)\b", re.IGNORECASE),
)
_ASSIGNMENT_PATTERNS = (
    re.compile(r"\bwhy\s+.*\bassign", re.IGNORECASE),
    re.compile(r"\bassign(ed|ment)?\b", re.IGNORECASE),
)
_ONBOARDING_PATTERNS = (
    re.compile(r"\bonboard(ing)?\b", re.IGNORECASE),
    re.compile(r"\bpending\s+.*\bsetup\b", re.IGNORECASE),
)

# An incident/ticket id in this codebase's test data and UI is either a UUID
# or a short alphanumeric ticket key (e.g. INC-123, OPS-42). Matched loosely
# on purpose: this only narrows which assignment row to look up, and falls
# back to "no id supplied" gracefully rather than raising on a partial match.
_INCIDENT_ID_PATTERN = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Za-z]{2,10}-\d{1,8})\b"
)


def classify_intent(query: str) -> Intent | None:
    """Returns the matched intent, or None if the question isn't recognized.

    Order matters: assignment questions often also contain the word
    "capacity" isn't true here, but they can be phrased close to onboarding
    language ("assign this onboarding task") -- assignment is checked before
    onboarding/capacity since "why wasn't X assigned" is the most specific,
    least ambiguous phrasing among the three.
    """
    text = str(query or "").strip()
    if not text:
        return None
    if any(pattern.search(text) for pattern in _ASSIGNMENT_PATTERNS):
        return "assignment"
    if any(pattern.search(text) for pattern in _CAPACITY_PATTERNS):
        return "capacity"
    if any(pattern.search(text) for pattern in _ONBOARDING_PATTERNS):
        return "onboarding"
    return None


def extract_incident_id(query: str) -> str | None:
    match = _INCIDENT_ID_PATTERN.search(str(query or ""))
    return match.group(1) if match else None


def compose_capacity_answer(rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = sorted(
        (row for row in rows if row.get("active") and int(row.get("remaining_hours") or 0) > 0),
        key=lambda row: int(row.get("remaining_hours") or 0),
        reverse=True,
    )
    if not available:
        text = "No responder currently has remaining capacity this week."
    else:
        top = available[:5]
        parts = [f"{row.get('username')} ({int(row.get('remaining_hours') or 0)}h remaining)" for row in top]
        text = "Responders with capacity this week: " + ", ".join(parts) + "."
    return {
        "intent": "capacity",
        "answer": text,
        "data": {"rows": available},
        "links": [{"label": "Open Capacity & Assignments", "path": "/approvals"}],
    }


def compose_assignment_answer(rows: list[dict[str, Any]], incident_id: str | None) -> dict[str, Any]:
    if not incident_id:
        return {
            "intent": "assignment",
            "answer": "I couldn't find an incident or ticket ID in your question. "
            "Ask again with the specific ID, e.g. \"why wasn't INC-123 assigned?\"",
            "data": {"rows": []},
            "links": [{"label": "Open Capacity & Assignments", "path": "/approvals"}],
        }
    matched = next((row for row in rows if str(row.get("incident_id") or "") == incident_id), None)
    if matched is None:
        text = (
            f"No assignment record exists for {incident_id}. It may not have been submitted for "
            "auto-assignment yet, or no on-duty responder had matching resources and remaining "
            "capacity when it was last attempted."
        )
        data: dict[str, Any] = {"rows": []}
    elif matched.get("status") == "unassigned":
        text = f"{incident_id} is unassigned: {matched.get('assignment_reason') or 'no reason recorded'}."
        data = {"rows": [matched]}
    else:
        text = (
            f"{incident_id} is assigned to {matched.get('assignee')} "
            f"({matched.get('status')}). {matched.get('assignment_reason') or ''}".strip()
        )
        data = {"rows": [matched]}
    return {
        "intent": "assignment",
        "answer": text,
        "data": data,
        "links": [{"label": "Open Capacity & Assignments", "path": "/approvals"}],
    }


def compose_onboarding_answer(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pending = [row for row in rows if str(row.get("test_status") or "") != "connected"]
    if not pending:
        text = "Nothing is pending -- every onboarded monitoring source is connected."
    else:
        parts = [
            f"{row.get('project_name')} ({row.get('test_status') or 'not tested'})"
            for row in pending[:8]
        ]
        text = f"{len(pending)} onboarding item(s) pending: " + ", ".join(parts) + "."
    return {
        "intent": "onboarding",
        "answer": text,
        "data": {"rows": pending},
        "links": [{"label": "Open Onboarding", "path": "/applications?workspace=onboarding"}],
    }


def compose_unsupported_answer(query: str) -> dict[str, Any]:
    return {
        "intent": None,
        "answer": (
            "I can currently help with three things: who has capacity this week, "
            "why a specific ticket wasn't assigned, and what's pending in onboarding. "
            "Try rephrasing your question around one of those."
        ),
        "data": {},
        "links": [
            {"label": "Open Capacity & Assignments", "path": "/approvals"},
            {"label": "Open Onboarding", "path": "/applications?workspace=onboarding"},
        ],
    }


def compose_forbidden_onboarding_answer() -> dict[str, Any]:
    return {
        "intent": "onboarding",
        "answer": "Onboarding status is only available to Administrators.",
        "data": {},
        "links": [],
    }
