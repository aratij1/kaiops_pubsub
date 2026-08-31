from __future__ import annotations

import hashlib
import json
from typing import Any

from common.models import Approval, RemediationAction


CONTRACT_VERSION = "kaims.remediation.v3"


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def bind_execution_contract(action: RemediationAction, approval: Approval) -> dict[str, Any]:
    """Bind approval to an immutable plan and concrete target identity.

    The digest deliberately excludes runtime connector results so reconciliation
    may append observations without changing what the operator approved.
    """
    plan = action.parameters.get("execution_plan")
    plan = plan if isinstance(plan, dict) else {}
    profile = action.parameters.get("connection_profile")
    profile = profile if isinstance(profile, dict) else {}
    runbook = {
        "id": str(action.parameters.get("runbook_id") or action.parameters.get("resolution_id") or action.action_type),
        "version": str(action.parameters.get("runbook_version") or "unversioned"),
        "digest": canonical_digest(plan),
    }
    target = {
        "provider": str(profile.get("executor_type") or profile.get("connection_type") or "unknown"),
        "environment": str(action.parameters.get("environment") or ""),
        "namespace": str(action.parameters.get("namespace") or "default"),
        "service": str(action.parameters.get("service") or ""),
        "name": str(action.target),
    }
    approved = {
        "schema_version": CONTRACT_VERSION,
        "execution_id": str(action.id),
        "incident_id": str(action.incident_id),
        "approval_id": str(approval.id),
        "runbook": runbook,
        "target": target,
        "plan": plan,
        "idempotency_key": str(action.idempotency_key or ""),
        "policy_decision_id": str(action.parameters.get("policy_decision_id") or ""),
    }
    approved["approved_plan_digest"] = canonical_digest(approved)
    action.parameters["execution_contract"] = approved
    return approved


def verify_execution_contract(action: RemediationAction) -> None:
    contract = action.parameters.get("execution_contract")
    if not isinstance(contract, dict) or contract.get("schema_version") != CONTRACT_VERSION:
        raise ValueError("A kaims.remediation.v3 execution contract is required")
    supplied = str(contract.get("approved_plan_digest") or "")
    unsigned = {key: value for key, value in contract.items() if key != "approved_plan_digest"}
    if not supplied or supplied != canonical_digest(unsigned):
        raise ValueError("Approved remediation plan digest does not match the execution contract")
    if str(contract.get("execution_id") or "") != str(action.id):
        raise ValueError("Execution contract identity does not match the remediation action")
    if str((contract.get("target") or {}).get("name") or "") != str(action.target):
        raise ValueError("Execution contract target does not match the remediation action")
