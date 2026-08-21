from __future__ import annotations

from typing import Any

from common.models import Approval, RemediationAction
from common.orchestration.execution_plan_contract import canonical_plan_fingerprint, verify_plan_fingerprint


CONTRACT_VERSION = "kaims.remediation.v3"


def canonical_digest(value: Any) -> str:
    """Compatibility alias; all governed plan/envelope hashes use one canonical algorithm."""
    return canonical_plan_fingerprint(value if isinstance(value, dict) else {"value": value})


def bind_execution_contract(action: RemediationAction, approval: Approval) -> dict[str, Any]:
    """Bind approval to an immutable plan and concrete target identity.

    The digest deliberately excludes runtime connector results so reconciliation
    may append observations without changing what the operator approved.
    """
    plan = approval.metadata.get("execution_plan")
    plan = plan if isinstance(plan, dict) else {}
    if not verify_plan_fingerprint(plan):
        raise ValueError("A valid immutable kaims.execution-plan.v2 plan is required")
    plan_fingerprint = str(plan.get("plan_fingerprint") or "")
    if str(approval.plan_id or "") != str(plan.get("plan_id") or ""):
        raise ValueError("Approval plan identity does not match the immutable execution plan")
    if str(approval.plan_fingerprint or "") != plan_fingerprint:
        raise ValueError("Approval fingerprint does not match the immutable execution plan")
    profile = action.parameters.get("connection_profile")
    profile = profile if isinstance(profile, dict) else {}
    runbook = {
        "id": str(action.parameters.get("runbook_id") or action.parameters.get("resolution_id") or action.action_type),
        "version": str(action.parameters.get("runbook_version") or "unversioned"),
        "checksum": str(action.parameters.get("runbook_checksum") or ""),
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
        "plan_id": str(plan.get("plan_id") or ""),
        "plan_fingerprint": plan_fingerprint,
        "runbook": runbook,
        "target": target,
        "plan": plan,
        "idempotency_key": str(action.idempotency_key or ""),
        "policy_decision_id": str(action.parameters.get("policy_decision_id") or ""),
    }
    approved["binding_fingerprint"] = canonical_digest(approved)
    action.parameters["execution_contract"] = approved
    return approved


def verify_execution_contract(action: RemediationAction) -> None:
    contract = action.parameters.get("execution_contract")
    if not isinstance(contract, dict) or contract.get("schema_version") != CONTRACT_VERSION:
        raise ValueError("A kaims.remediation.v3 execution contract is required")
    supplied = str(contract.get("binding_fingerprint") or "")
    unsigned = {key: value for key, value in contract.items() if key != "binding_fingerprint"}
    if not supplied or supplied != canonical_digest(unsigned):
        raise ValueError("Approved remediation plan digest does not match the execution contract")
    plan = contract.get("plan") if isinstance(contract.get("plan"), dict) else {}
    if not verify_plan_fingerprint(plan):
        raise ValueError("Execution contract contains a modified or invalid execution plan")
    if str(contract.get("plan_fingerprint") or "") != str(plan.get("plan_fingerprint") or ""):
        raise ValueError("Execution contract fingerprint does not match its immutable plan")
    if str(contract.get("execution_id") or "") != str(action.id):
        raise ValueError("Execution contract identity does not match the remediation action")
    if str((contract.get("target") or {}).get("name") or "") != str(action.target):
        raise ValueError("Execution contract target does not match the remediation action")
