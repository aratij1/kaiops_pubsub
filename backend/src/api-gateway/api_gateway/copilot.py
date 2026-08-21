"""Phase 0/1 Copilot: deterministic intent matching and answer composition.

No LLM/model-router calls here by design -- every intent is a direct data
lookup against data an existing API already exposes. This module is pure
(no I/O, no FastAPI imports) so intent matching and answer text can be unit
tested without a running app or DB.
"""

from __future__ import annotations

import re
from typing import Any, Literal

Intent = Literal[
    "capacity",
    "assignment",
    "onboarding",
    "rca",
    "approval_status",
    "incident_summary",
]

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
    re.compile(r"\bneeds?\s+setup\b", re.IGNORECASE),
)
_RCA_PATTERNS = (
    re.compile(r"\brca\b", re.IGNORECASE),
    re.compile(r"\broot\s+cause\b", re.IGNORECASE),
    re.compile(r"\bexplain\b.*\b(incident|ticket|alert)\b", re.IGNORECASE),
    re.compile(r"\bconfidence\b", re.IGNORECASE),
)
_APPROVAL_STATUS_PATTERNS = (
    re.compile(r"\bapproval\s+status\b", re.IGNORECASE),
    re.compile(r"\bwaiting\s+for\s+approval\b", re.IGNORECASE),
    re.compile(r"\b(is|was)\b.*\bapproved\b", re.IGNORECASE),
    re.compile(r"\brequires?\s+approval\b", re.IGNORECASE),
)
_INCIDENT_SUMMARY_PATTERNS = (
    re.compile(r"\bwhat\s+needs\s+attention\b", re.IGNORECASE),
    re.compile(r"\brecent\s+incidents?\b", re.IGNORECASE),
    re.compile(r"\bopen\s+incidents?\b", re.IGNORECASE),
    re.compile(r"\bincident\s+summary\b", re.IGNORECASE),
    re.compile(r"\bservice\s+health\b", re.IGNORECASE),
    re.compile(r"\bsummarize\b", re.IGNORECASE),
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
    least ambiguous phrasing among the three. The three newer intents (rca,
    approval_status, incident_summary) use vocabulary that doesn't overlap
    with the original three or each other, so their relative order doesn't
    change behavior -- checked last only to keep the original three's
    priority unchanged for existing callers.
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
    if any(pattern.search(text) for pattern in _RCA_PATTERNS):
        return "rca"
    if any(pattern.search(text) for pattern in _APPROVAL_STATUS_PATTERNS):
        return "approval_status"
    if any(pattern.search(text) for pattern in _INCIDENT_SUMMARY_PATTERNS):
        return "incident_summary"
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


def compose_rca_answer(
    incident: dict[str, Any] | None, incident_id: str | None, *, was_auto_selected: bool = False
) -> dict[str, Any]:
    """RCA/root-cause explanation for one incident.

    Reads the same enriched payload the Approvals workspace already shows
    (GET /approval/incident/{id}), which carries the resolution-agent's
    recommendation (root_cause, confidence, recommended_action) alongside
    the incident record -- one call, no separate RCA-store lookup.

    incident_id is the incident this call resolved to explaining -- this is
    either an ID the user typed, or one auto-selected by the caller (e.g.
    the lowest-confidence candidate for a question with no ID of its own).
    was_auto_selected controls whether the answer explains that choice.
    """
    if not incident_id:
        return {
            "intent": "rca",
            "answer": "I couldn't find an incident or ticket ID in your question, and no recommendation "
            "history is available to pick one automatically. Ask again with the specific ID, "
            "e.g. \"explain the RCA for INC-123\".",
            "data": {},
            "links": [],
        }
    recommendation = incident.get("recommendation") if isinstance(incident, dict) else None
    if not incident or not incident.get("id") or not isinstance(recommendation, dict) or not recommendation:
        text = (
            f"No completed root-cause analysis exists yet for {incident_id}. "
            "It may still be collecting evidence, or the incident ID/ticket wasn't found."
        )
        return {
            "intent": "rca",
            "answer": text,
            "data": {},
            "links": [{"label": "Open Alerts & Incidents", "path": "/incidents"}],
        }
    root_cause = str(recommendation.get("root_cause") or "").strip()
    confidence = recommendation.get("confidence")
    recommended_action = str(recommendation.get("recommended_action") or "").strip()
    confidence_text = f"{float(confidence) * 100:.0f}% confidence" if isinstance(confidence, (int, float)) else "confidence not recorded"
    parts = []
    if was_auto_selected:
        parts.append(f"The lowest-confidence recommendation I could find is for {incident_id} ({confidence_text}).")
    parts.append(f"{incident_id}: {root_cause}" if root_cause else f"{incident_id} has a recommendation but no root cause text was recorded.")
    if not was_auto_selected:
        parts.append(f"({confidence_text}.)")
    if recommended_action:
        parts.append(f"Recommended action: {recommended_action}.")
    return {
        "intent": "rca",
        "answer": " ".join(parts),
        "data": {"recommendation": recommendation},
        "links": [{"label": "Open Alerts & Incidents", "path": "/incidents"}],
    }


def compose_approval_status_answer(incident: dict[str, Any] | None, incident_id: str | None) -> dict[str, Any]:
    """Approval status for one incident, from the same enriched incident payload as compose_rca_answer."""
    if not incident_id:
        return {
            "intent": "approval_status",
            "answer": "I couldn't find an incident or ticket ID in your question. "
            "Ask again with the specific ID, e.g. \"what's the approval status of INC-123?\".",
            "data": {},
            "links": [{"label": "Open Approvals", "path": "/approvals"}],
        }
    if not incident or not incident.get("id"):
        text = f"No incident record was found for {incident_id}."
        return {
            "intent": "approval_status",
            "answer": text,
            "data": {},
            "links": [{"label": "Open Approvals", "path": "/approvals"}],
        }
    status = str(incident.get("status") or "unknown")
    recommendation = incident.get("recommendation") if isinstance(incident.get("recommendation"), dict) else None
    if status == "awaiting_approval":
        text = f"{incident_id} is awaiting approval."
        if recommendation and recommendation.get("recommended_action"):
            text += f" Recommended action: {recommendation.get('recommended_action')}."
    elif recommendation is None:
        text = f"{incident_id} is currently \"{status}\" and has no recommendation yet, so nothing is pending approval."
    else:
        text = f"{incident_id} is currently \"{status}\" -- it is not waiting on an approval decision right now."
    return {
        "intent": "approval_status",
        "answer": text,
        "data": {"status": status},
        "links": [{"label": "Open Approvals", "path": "/approvals"}],
    }


def compose_incident_summary_answer(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """"What needs attention" -- incidents that are open and not yet closed/failed.

    Reads GET /incidents/metadata, the same source the Alerts & Incidents
    page uses. Ranks the open incidents' risk_tier so the most urgent ones
    are named first rather than just the most recent.
    """
    _RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    open_rows = [row for row in rows if str(row.get("status") or "").lower() not in {"closed", "failed"}]
    if not open_rows:
        text = "Nothing needs attention right now -- no open incidents were found."
        return {
            "intent": "incident_summary",
            "answer": text,
            "data": {"rows": []},
            "links": [{"label": "Open Alerts & Incidents", "path": "/incidents"}],
        }
    ranked = sorted(
        open_rows,
        key=lambda row: _RISK_ORDER.get(str(row.get("risk_tier") or "").lower(), 4),
    )
    top = ranked[:5]
    parts = [
        f"{row.get('service') or 'unknown service'} ({row.get('risk_tier') or 'unranked'} risk, {row.get('status') or 'unknown status'})"
        for row in top
    ]
    text = f"{len(open_rows)} incident(s) need attention: " + ", ".join(parts) + "."
    return {
        "intent": "incident_summary",
        "answer": text,
        "data": {"rows": top},
        "links": [{"label": "Open Alerts & Incidents", "path": "/incidents"}],
    }


def compose_unsupported_answer(query: str) -> dict[str, Any]:
    return {
        "intent": None,
        "answer": (
            "I can currently help with: who has capacity this week, why a specific ticket "
            "wasn't assigned, what's pending in onboarding, root cause and confidence for a "
            "specific incident, whether an incident is waiting on approval, and what open "
            "incidents need attention. Try rephrasing your question around one of those."
        ),
        "data": {},
        "links": [
            {"label": "Open Capacity & Assignments", "path": "/approvals"},
            {"label": "Open Onboarding", "path": "/applications?workspace=onboarding"},
            {"label": "Open Alerts & Incidents", "path": "/incidents"},
        ],
    }


def compose_forbidden_onboarding_answer() -> dict[str, Any]:
    return {
        "intent": "onboarding",
        "answer": "Onboarding status is only available to Administrators.",
        "data": {},
        "links": [],
    }
