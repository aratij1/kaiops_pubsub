from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from common.context_enrichment_contract import TicketClosurePolicy

JiraAction = Literal["updated", "approved", "rejected", "resolved", "closed", "reopened"]


def jira_webhook_event_id(payload: dict[str, Any]) -> str:
    issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
    changelog = payload.get("changelog") if isinstance(payload.get("changelog"), dict) else {}
    material = {
        "timestamp": payload.get("timestamp"), "webhookEvent": payload.get("webhookEvent"),
        "issue_id": issue.get("id"), "issue_key": issue.get("key"),
        "changelog_id": changelog.get("id"),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def jira_actor_id(payload: dict[str, Any]) -> str:
    actor = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    return str(actor.get("accountId") or actor.get("key") or "").strip()


def jira_issue_status(payload: dict[str, Any]) -> str:
    issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
    return str(status.get("id") or status.get("name") or "").strip()


def governed_jira_action(status: str, transition_mapping: dict[str, str]) -> JiraAction:
    normalized = str(status or "").strip().lower()
    for action in ("approved", "rejected", "resolved", "closed", "reopened"):
        configured = str(transition_mapping.get(action) or "").strip().lower()
        if configured and normalized == configured:
            return action  # type: ignore[return-value]
    return "updated"


def validate_jira_approval(
    *,
    binding: dict[str, Any],
    actor_id: str,
    action: JiraAction,
    current_identity: dict[str, Any],
    now: datetime | None = None,
) -> tuple[bool, str]:
    if action not in {"approved", "rejected"}:
        return False, "transition is not an approval decision"
    if actor_id != str(binding.get("assignee_id") or ""):
        return False, "Jira actor is not the assigned authorized HITL resource"
    for key in (
        "recommendation_id", "rca_version", "context_snapshot_id", "context_fingerprint",
        "execution_plan_id", "plan_fingerprint",
    ):
        if str(binding.get(key) or "") != str(current_identity.get(key) or ""):
            return False, f"stale Jira binding: {key} changed"
    expires_at = binding.get("approval_expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if (now or datetime.now(UTC)) >= expires_at:
            return False, "Jira approval has expired"
    return True, "authorized current Jira decision"


def kaims_may_close_ticket(
    policy: TicketClosurePolicy,
    state: dict[str, Any],
) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if policy.ownership != "kaims" or not policy.kaims_may_close:
        blockers.append("ticket closure is not owned by KaiMS")
    required = {
        "remediation_status": "succeeded", "validation_status": "passed",
        "required_validators_complete": True, "alerts_cleared": True,
        "stability_window_passed": True, "rollback_not_active": True,
        "current_plan_matches_approved_plan": True,
    }
    for key, expected in required.items():
        if state.get(key) != expected:
            blockers.append(f"{key} must be {expected}")
    if list(state.get("critical_contradictions") or []):
        blockers.append("critical contradictions remain")
    if policy.requires_human_confirmation and not state.get("human_confirmation"):
        blockers.append("human closure confirmation is required")
    return not blockers, blockers
