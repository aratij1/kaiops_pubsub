from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from common.models import RemediationAction


class ExecutionSafetyDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


@dataclass(frozen=True)
class ExecutionSafetyAssessment:
    decision: ExecutionSafetyDecision
    reason: str
    snapshot: dict[str, Any]
    snapshot_hash: str
    idempotency_key: str


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def build_pre_execution_snapshot(action: RemediationAction) -> dict[str, Any]:
    return {
        "action_id": str(action.id),
        "incident_id": str(action.incident_id),
        "approval_id": str(action.approval_id) if action.approval_id else None,
        "action_type": str(action.action_type or "").strip().lower(),
        "target": str(action.target or "").strip(),
        "parameters": action.parameters,
        "metadata": action.metadata,
    }


def hash_snapshot(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(snapshot).encode("utf-8")).hexdigest()


def build_idempotency_key(action: RemediationAction, snapshot_hash: str) -> str:
    approval_id = str(action.approval_id) if action.approval_id else "unapproved"
    return f"remediation:{action.incident_id}:{approval_id}:{snapshot_hash}"


def assess_execution_safety(action: RemediationAction, *, allowlisted_actions: set[str]) -> ExecutionSafetyAssessment:
    snapshot = build_pre_execution_snapshot(action)
    snapshot_hash = hash_snapshot(snapshot)
    idempotency_key = build_idempotency_key(action, snapshot_hash)

    action_type = snapshot["action_type"]
    if not action_type or action_type not in allowlisted_actions:
        return ExecutionSafetyAssessment(
            ExecutionSafetyDecision.BLOCK,
            "ACTION_TYPE_NOT_ALLOWLISTED",
            snapshot,
            snapshot_hash,
            idempotency_key,
        )
    if not snapshot["target"]:
        return ExecutionSafetyAssessment(
            ExecutionSafetyDecision.BLOCK,
            "EXECUTION_TARGET_MISSING",
            snapshot,
            snapshot_hash,
            idempotency_key,
        )
    if action.approval_id is None and not bool(action.metadata.get("auto_execution_authorized")):
        return ExecutionSafetyAssessment(
            ExecutionSafetyDecision.BLOCK,
            "APPROVAL_OR_AUTO_AUTHORIZATION_REQUIRED",
            snapshot,
            snapshot_hash,
            idempotency_key,
        )
    return ExecutionSafetyAssessment(
        ExecutionSafetyDecision.ALLOW,
        "execution safety checks passed",
        snapshot,
        snapshot_hash,
        idempotency_key,
    )
