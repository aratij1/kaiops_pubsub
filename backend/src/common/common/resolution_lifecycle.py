from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from common.orchestration.execution_plan_contract import canonical_plan_fingerprint
from common.tenant_identity import require_tenant_id

SCHEMA_VERSION = "kaims.resolution-lifecycle.v4"


class ResolutionState(StrEnum):
    ANALYZING = "analyzing"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    AWAITING_APPROVAL = "awaiting_approval"
    READY_TO_EXECUTE = "ready_to_execute"
    EXECUTING = "executing"
    BLOCKED_RETRYABLE = "blocked_retryable"
    VALIDATING = "validating"
    PENDING_STABILITY = "pending_stability"
    RECOVERED = "recovered"
    ROLLED_BACK = "rolled_back"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    REJECTED = "rejected"
    CLOSED = "closed"


class ResolutionDisposition(StrEnum):
    WATCH_ONLY = "watch_only"
    INVESTIGATE = "investigate"
    APPROVAL_REQUIRED = "approval_required"
    EXECUTION_READY = "execution_ready"


class LifecycleActor(StrEnum):
    """Components allowed to author lifecycle transitions.

    The actor is intentionally a service role, not a user identity. Human
    identity remains part of the approval/audit payload.
    """

    RESOLUTION = "resolution"
    APPROVAL = "approval"
    REMEDIATION = "remediation"
    CLOSURE = "closure"
    OPERATOR = "operator"
    RECONCILER = "reconciler"


class LifecycleTransitionError(ValueError):
    """Raised when a lifecycle transition violates the control contract."""


CONTROL_SCHEMA_VERSION = "kaims.resolution-control.v1"
_WATCH_ONLY_TOKENS = {"watch_only", "monitor_only", "observation_only", "observe_only"}


def _explicit_watch_only(*sources: Any) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        if source.get("watch_only") is True:
            return True
        # A generic model outcome such as "no_action" is not authorization to
        # close. Only dedicated policy/mode fields can opt into watch-only.
        for key in ("disposition", "resolution_mode", "handling_mode", "action_mode"):
            token = str(source.get(key) or "").strip().lower().replace("-", "_").replace(" ", "_")
            if token in _WATCH_ONLY_TOKENS:
                return True
    return False


def decide_resolution_control(plan: dict[str, Any] | None, *, requires_approval: bool, sources: tuple[Any, ...] = ()) -> dict[str, Any]:
    """Produce the single authoritative routing decision for a resolution plan."""
    plan = plan if isinstance(plan, dict) else {}
    executable = [*(plan.get("commands") or []), *(plan.get("scripts") or [])]
    has_executable = bool(plan.get("execution_ready") is True and any(str(item).strip() for item in executable))
    watch_only = _explicit_watch_only(*sources)
    conflicts: list[str] = []
    if watch_only and has_executable:
        conflicts.append("watch_only_cannot_include_executable_actions")
    if conflicts:
        disposition = ResolutionDisposition.INVESTIGATE
        state = ResolutionState.DIAGNOSTIC_ONLY
        reason = "control_contract_conflict"
    elif watch_only:
        disposition = ResolutionDisposition.WATCH_ONLY
        state = ResolutionState.DIAGNOSTIC_ONLY
        reason = "explicit_watch_only"
    elif not has_executable:
        disposition = ResolutionDisposition.INVESTIGATE
        state = ResolutionState.DIAGNOSTIC_ONLY
        reason = "no_corrective_capability"
    elif requires_approval:
        disposition = ResolutionDisposition.APPROVAL_REQUIRED
        state = ResolutionState.AWAITING_APPROVAL
        reason = "human_approval_required"
    else:
        disposition = ResolutionDisposition.EXECUTION_READY
        state = ResolutionState.READY_TO_EXECUTE
        reason = "policy_authorized"
    return {
        "schema_version": CONTROL_SCHEMA_VERSION,
        "disposition": disposition.value,
        "initial_state": state.value,
        "reason_code": reason,
        # Diagnostic completion may close the workflow without execution. The
        # closure report must still distinguish that outcome from validated
        # alert clearance and service recovery.
        # A missing corrective capability means "investigate", not "resolved".
        # Only an explicit watch-only policy may authorize closure without
        # execution and recovery validation.
        "auto_close": disposition == ResolutionDisposition.WATCH_ONLY and not conflicts,
        "watch_only_authorized": disposition == ResolutionDisposition.WATCH_ONLY and not conflicts,
        "approval_required": disposition == ResolutionDisposition.APPROVAL_REQUIRED,
        "execution_allowed": disposition == ResolutionDisposition.EXECUTION_READY,
        "conflicts": conflicts,
    }


PERMITTED_ACTIONS = {
    ResolutionState.ANALYZING: ["generate_plan", "operator_close"],
    ResolutionState.DIAGNOSTIC_ONLY: ["regenerate_plan", "escalate", "operator_close"],
    ResolutionState.AWAITING_APPROVAL: ["approve", "reject", "edit_plan", "operator_close"],
    ResolutionState.READY_TO_EXECUTE: ["execute", "edit_plan", "operator_close"],
    ResolutionState.EXECUTING: ["observe", "cancel"],
    ResolutionState.BLOCKED_RETRYABLE: ["retry", "edit_plan", "escalate", "operator_close"],
    ResolutionState.VALIDATING: ["validate", "rollback"],
    ResolutionState.PENDING_STABILITY: ["observe", "rollback"],
    ResolutionState.RECOVERED: ["close", "revalidate", "operator_close"],
    ResolutionState.ROLLED_BACK: ["regenerate_plan", "escalate", "operator_close"],
    ResolutionState.FAILED_RETRYABLE: ["retry", "regenerate_plan", "rollback", "escalate", "operator_close"],
    ResolutionState.FAILED_TERMINAL: ["escalate", "operator_close"],
    ResolutionState.REJECTED: ["regenerate_plan", "operator_close"],
    ResolutionState.CLOSED: [],
}


# This is the executable form of the lifecycle table in
# docs/architecture/resolution-lifecycle-v4.md. Keeping it here prevents a
# consumer from advancing an incident merely because it received a stale or
# contradictory event.
ALLOWED_TRANSITIONS: dict[ResolutionState, frozenset[ResolutionState]] = {
    ResolutionState.ANALYZING: frozenset({
        ResolutionState.DIAGNOSTIC_ONLY,
        ResolutionState.AWAITING_APPROVAL,
        ResolutionState.READY_TO_EXECUTE,
        ResolutionState.CLOSED,
    }),
    ResolutionState.DIAGNOSTIC_ONLY: frozenset({ResolutionState.ANALYZING, ResolutionState.CLOSED}),
    ResolutionState.AWAITING_APPROVAL: frozenset({
        ResolutionState.READY_TO_EXECUTE,
        ResolutionState.REJECTED,
        ResolutionState.ANALYZING,
        ResolutionState.BLOCKED_RETRYABLE,
        ResolutionState.CLOSED,
    }),
    ResolutionState.READY_TO_EXECUTE: frozenset({
        ResolutionState.EXECUTING,
        ResolutionState.BLOCKED_RETRYABLE,
        ResolutionState.CLOSED,
    }),
    ResolutionState.EXECUTING: frozenset({
        ResolutionState.VALIDATING,
        ResolutionState.FAILED_RETRYABLE,
        ResolutionState.FAILED_TERMINAL,
        ResolutionState.ROLLED_BACK,
        ResolutionState.BLOCKED_RETRYABLE,
    }),
    ResolutionState.BLOCKED_RETRYABLE: frozenset({
        ResolutionState.AWAITING_APPROVAL,
        ResolutionState.READY_TO_EXECUTE,
        ResolutionState.ANALYZING,
        ResolutionState.CLOSED,
    }),
    ResolutionState.VALIDATING: frozenset({
        ResolutionState.PENDING_STABILITY,
        ResolutionState.RECOVERED,
        ResolutionState.FAILED_RETRYABLE,
        ResolutionState.ROLLED_BACK,
    }),
    ResolutionState.PENDING_STABILITY: frozenset({
        ResolutionState.PENDING_STABILITY,
        ResolutionState.RECOVERED,
        ResolutionState.FAILED_RETRYABLE,
        ResolutionState.ROLLED_BACK,
    }),
    ResolutionState.RECOVERED: frozenset({ResolutionState.CLOSED}),
    ResolutionState.ROLLED_BACK: frozenset({
        ResolutionState.VALIDATING,
        ResolutionState.FAILED_TERMINAL,
        ResolutionState.CLOSED,
    }),
    ResolutionState.FAILED_RETRYABLE: frozenset({
        ResolutionState.READY_TO_EXECUTE,
        ResolutionState.EXECUTING,
        ResolutionState.ROLLED_BACK,
        ResolutionState.ANALYZING,
        ResolutionState.BLOCKED_RETRYABLE,
        ResolutionState.CLOSED,
    }),
    ResolutionState.FAILED_TERMINAL: frozenset({ResolutionState.ANALYZING, ResolutionState.CLOSED}),
    ResolutionState.REJECTED: frozenset({ResolutionState.ANALYZING, ResolutionState.CLOSED}),
    ResolutionState.CLOSED: frozenset(),
}


# Transition authority is edge-oriented: remediation can report that an
# attempt is ready for validation, but only closure can declare recovery or
# closure. Reconciler is restricted to closure-owned terminal edges and must
# still present recovery proof before calling the reducer.
TRANSITION_ACTORS: dict[tuple[ResolutionState, ResolutionState], frozenset[LifecycleActor]] = {
    (ResolutionState.ANALYZING, ResolutionState.DIAGNOSTIC_ONLY): frozenset({LifecycleActor.RESOLUTION}),
    (ResolutionState.ANALYZING, ResolutionState.AWAITING_APPROVAL): frozenset({LifecycleActor.RESOLUTION}),
    (ResolutionState.ANALYZING, ResolutionState.READY_TO_EXECUTE): frozenset({LifecycleActor.RESOLUTION}),
    (ResolutionState.ANALYZING, ResolutionState.CLOSED): frozenset({LifecycleActor.OPERATOR}),
    (ResolutionState.DIAGNOSTIC_ONLY, ResolutionState.ANALYZING): frozenset({LifecycleActor.RESOLUTION, LifecycleActor.OPERATOR}),
    (ResolutionState.DIAGNOSTIC_ONLY, ResolutionState.CLOSED): frozenset({LifecycleActor.CLOSURE, LifecycleActor.OPERATOR, LifecycleActor.RECONCILER}),
    (ResolutionState.AWAITING_APPROVAL, ResolutionState.READY_TO_EXECUTE): frozenset({LifecycleActor.APPROVAL}),
    (ResolutionState.AWAITING_APPROVAL, ResolutionState.REJECTED): frozenset({LifecycleActor.APPROVAL}),
    (ResolutionState.AWAITING_APPROVAL, ResolutionState.ANALYZING): frozenset({LifecycleActor.RESOLUTION, LifecycleActor.OPERATOR}),
    (ResolutionState.AWAITING_APPROVAL, ResolutionState.BLOCKED_RETRYABLE): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.AWAITING_APPROVAL, ResolutionState.CLOSED): frozenset({LifecycleActor.OPERATOR}),
    (ResolutionState.READY_TO_EXECUTE, ResolutionState.EXECUTING): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.READY_TO_EXECUTE, ResolutionState.BLOCKED_RETRYABLE): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.READY_TO_EXECUTE, ResolutionState.CLOSED): frozenset({LifecycleActor.OPERATOR}),
    (ResolutionState.EXECUTING, ResolutionState.VALIDATING): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.EXECUTING, ResolutionState.FAILED_RETRYABLE): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.EXECUTING, ResolutionState.FAILED_TERMINAL): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.EXECUTING, ResolutionState.ROLLED_BACK): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.EXECUTING, ResolutionState.BLOCKED_RETRYABLE): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.BLOCKED_RETRYABLE, ResolutionState.AWAITING_APPROVAL): frozenset({LifecycleActor.APPROVAL, LifecycleActor.REMEDIATION}),
    (ResolutionState.BLOCKED_RETRYABLE, ResolutionState.READY_TO_EXECUTE): frozenset({LifecycleActor.APPROVAL, LifecycleActor.REMEDIATION}),
    (ResolutionState.BLOCKED_RETRYABLE, ResolutionState.ANALYZING): frozenset({LifecycleActor.RESOLUTION, LifecycleActor.OPERATOR}),
    (ResolutionState.BLOCKED_RETRYABLE, ResolutionState.CLOSED): frozenset({LifecycleActor.OPERATOR}),
    (ResolutionState.VALIDATING, ResolutionState.RECOVERED): frozenset({LifecycleActor.CLOSURE, LifecycleActor.RECONCILER}),
    (ResolutionState.VALIDATING, ResolutionState.PENDING_STABILITY): frozenset({LifecycleActor.CLOSURE, LifecycleActor.RECONCILER}),
    (ResolutionState.PENDING_STABILITY, ResolutionState.PENDING_STABILITY): frozenset({LifecycleActor.CLOSURE, LifecycleActor.RECONCILER}),
    (ResolutionState.PENDING_STABILITY, ResolutionState.RECOVERED): frozenset({LifecycleActor.CLOSURE, LifecycleActor.RECONCILER}),
    (ResolutionState.PENDING_STABILITY, ResolutionState.FAILED_RETRYABLE): frozenset({LifecycleActor.CLOSURE, LifecycleActor.RECONCILER}),
    (ResolutionState.PENDING_STABILITY, ResolutionState.ROLLED_BACK): frozenset({LifecycleActor.CLOSURE}),
    (ResolutionState.VALIDATING, ResolutionState.FAILED_RETRYABLE): frozenset({LifecycleActor.CLOSURE, LifecycleActor.RECONCILER}),
    (ResolutionState.VALIDATING, ResolutionState.ROLLED_BACK): frozenset({LifecycleActor.CLOSURE}),
    (ResolutionState.RECOVERED, ResolutionState.CLOSED): frozenset({LifecycleActor.CLOSURE, LifecycleActor.OPERATOR, LifecycleActor.RECONCILER}),
    (ResolutionState.ROLLED_BACK, ResolutionState.VALIDATING): frozenset({LifecycleActor.CLOSURE, LifecycleActor.REMEDIATION}),
    (ResolutionState.ROLLED_BACK, ResolutionState.FAILED_TERMINAL): frozenset({LifecycleActor.CLOSURE, LifecycleActor.REMEDIATION}),
    (ResolutionState.ROLLED_BACK, ResolutionState.CLOSED): frozenset({LifecycleActor.OPERATOR}),
    (ResolutionState.FAILED_RETRYABLE, ResolutionState.READY_TO_EXECUTE): frozenset({LifecycleActor.APPROVAL, LifecycleActor.REMEDIATION}),
    (ResolutionState.FAILED_RETRYABLE, ResolutionState.EXECUTING): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.FAILED_RETRYABLE, ResolutionState.ROLLED_BACK): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.FAILED_RETRYABLE, ResolutionState.ANALYZING): frozenset({LifecycleActor.RESOLUTION, LifecycleActor.OPERATOR}),
    (ResolutionState.FAILED_RETRYABLE, ResolutionState.BLOCKED_RETRYABLE): frozenset({LifecycleActor.REMEDIATION}),
    (ResolutionState.FAILED_RETRYABLE, ResolutionState.CLOSED): frozenset({LifecycleActor.OPERATOR}),
    (ResolutionState.FAILED_TERMINAL, ResolutionState.ANALYZING): frozenset({LifecycleActor.OPERATOR}),
    (ResolutionState.FAILED_TERMINAL, ResolutionState.CLOSED): frozenset({LifecycleActor.OPERATOR}),
    (ResolutionState.REJECTED, ResolutionState.ANALYZING): frozenset({LifecycleActor.RESOLUTION, LifecycleActor.OPERATOR}),
    (ResolutionState.REJECTED, ResolutionState.CLOSED): frozenset({LifecycleActor.OPERATOR}),
}


def plan_fingerprint(plan: dict[str, Any] | None) -> str:
    return canonical_plan_fingerprint(plan or {})


def create_lifecycle(*, tenant_id: str, incident_id: Any, recommendation_id: Any,
                     plan: dict[str, Any] | None, state: ResolutionState | str,
                     reason_code: str | None = None, supersedes: str | None = None,
                     control: dict[str, Any] | None = None) -> dict[str, Any]:
    state = ResolutionState(state)
    now = datetime.now(UTC).isoformat()
    verified_tenant_id = require_tenant_id(tenant_id, source="resolution lifecycle identity")
    return {
        "schema_version": SCHEMA_VERSION, "tenant_id": verified_tenant_id,
        "incident_id": str(incident_id), "recommendation_id": str(recommendation_id),
        "plan_fingerprint": plan_fingerprint(plan), "state": state.value, "state_version": 1,
        "reason_code": reason_code, "retryable": state in {ResolutionState.BLOCKED_RETRYABLE, ResolutionState.FAILED_RETRYABLE},
        "supersedes": supersedes, "approval": {}, "execution": {"attempt": 0}, "validation": {},
        "control": dict(control or {}),
        "permitted_actions": PERMITTED_ACTIONS[state], "created_at": now, "updated_at": now,
    }


def select_current_lifecycle(
    *sources: Any,
    recommendation_id: Any | None = None,
    expected_plan_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Return the newest matching v4 envelope, independent of source order."""

    matches: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        candidates = [source.get("resolution_lifecycle")]
        candidates.extend(source.get(key, {}).get("resolution_lifecycle") for key in ("metadata", "parameters") if isinstance(source.get(key), dict))
        for candidate in candidates:
            if not isinstance(candidate, dict) or candidate.get("schema_version") != SCHEMA_VERSION:
                continue
            if recommendation_id is not None and str(candidate.get("recommendation_id")) != str(recommendation_id):
                continue
            if expected_plan_fingerprint is not None and candidate.get("plan_fingerprint") != expected_plan_fingerprint:
                continue
            matches.append(dict(candidate))
    if not matches:
        return None

    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        try:
            version = int(item.get("state_version") or 0)
        except (TypeError, ValueError):
            version = 0
        return version, str(item.get("updated_at") or "")

    return max(matches, key=sort_key)


def extract_lifecycle(*sources: Any) -> dict[str, Any] | None:
    """Backward-compatible alias for selecting the newest lifecycle."""

    return select_current_lifecycle(*sources)


def validate_transition(
    lifecycle: dict[str, Any],
    state: ResolutionState | str,
    *,
    actor: LifecycleActor | str,
    expected_version: int | None = None,
    expected_plan_fingerprint: str | None = None,
) -> tuple[ResolutionState, ResolutionState, LifecycleActor]:
    if lifecycle.get("schema_version") != SCHEMA_VERSION:
        raise LifecycleTransitionError("unsupported resolution lifecycle schema")
    try:
        current = ResolutionState(str(lifecycle.get("state") or ""))
        target = ResolutionState(state)
        transition_actor = LifecycleActor(actor)
    except ValueError as exc:
        raise LifecycleTransitionError(str(exc)) from exc
    try:
        current_version = int(lifecycle.get("state_version") or 0)
    except (TypeError, ValueError) as exc:
        raise LifecycleTransitionError("invalid lifecycle state_version") from exc
    if expected_version is not None and current_version != int(expected_version):
        raise LifecycleTransitionError(
            f"stale lifecycle version: expected {expected_version}, found {current_version}"
        )
    if expected_plan_fingerprint is not None and lifecycle.get("plan_fingerprint") != expected_plan_fingerprint:
        raise LifecycleTransitionError("lifecycle plan fingerprint does not match the approved plan")
    if current == target:
        return current, target, transition_actor
    if target not in ALLOWED_TRANSITIONS[current]:
        raise LifecycleTransitionError(f"illegal resolution lifecycle transition: {current.value} -> {target.value}")
    allowed_actors = TRANSITION_ACTORS.get((current, target), frozenset())
    if transition_actor not in allowed_actors:
        raise LifecycleTransitionError(
            f"actor {transition_actor.value} cannot transition {current.value} -> {target.value}"
        )
    return current, target, transition_actor


def _record_transition_metric(
    current: ResolutionState,
    target: ResolutionState,
    actor: LifecycleActor,
    outcome: str,
) -> None:
    # Import lazily so the pure lifecycle model remains usable by migrations
    # and command-line tooling that do not initialize observability exporters.
    try:
        from common.telemetry import LIFECYCLE_TRANSITIONS

        LIFECYCLE_TRANSITIONS.labels(current.value, target.value, actor.value, outcome).inc()
    except Exception:
        return


def transition_lifecycle(lifecycle: dict[str, Any], state: ResolutionState | str, *, actor: LifecycleActor | str,
                         reason_code: str | None = None,
                         approval: dict[str, Any] | None = None, execution: dict[str, Any] | None = None,
                         validation: dict[str, Any] | None = None,
                         expected_version: int | None = None,
                         expected_plan_fingerprint: str | None = None) -> dict[str, Any]:
    result = dict(lifecycle)
    state = ResolutionState(state)
    current_state = ResolutionState(str(result.get("state") or state.value))
    try:
        current_state, state, transition_actor = validate_transition(
            result,
            state,
            actor=actor,
            expected_version=expected_version,
            expected_plan_fingerprint=expected_plan_fingerprint,
        )
    except LifecycleTransitionError:
        try:
            current = ResolutionState(str(result.get("state") or ""))
            target = ResolutionState(state)
            transition_actor = LifecycleActor(actor)
            _record_transition_metric(current, target, transition_actor, "rejected")
        except ValueError:
            pass
        raise
    version = int(result.get("state_version") or 0)
    if current_state != state:
        version += 1
    result.update({"schema_version": SCHEMA_VERSION, "state": state.value,
                   "state_version": version,
                   "reason_code": reason_code if reason_code is not None else result.get("reason_code"),
                   "retryable": state in {ResolutionState.BLOCKED_RETRYABLE, ResolutionState.FAILED_RETRYABLE},
                   "permitted_actions": PERMITTED_ACTIONS[state], "updated_at": datetime.now(UTC).isoformat()})
    for key, update in (("approval", approval), ("execution", execution), ("validation", validation)):
        if update is not None:
            result[key] = {**(result.get(key) if isinstance(result.get(key), dict) else {}), **update}
    result["last_transition_actor"] = transition_actor.value
    _record_transition_metric(
        current_state,
        state,
        transition_actor,
        "idempotent" if current_state == state else "accepted",
    )
    return result


def initial_plan_state(plan: dict[str, Any], *, requires_approval: bool) -> ResolutionState:
    executable = [*(plan.get("commands") or []), *(plan.get("scripts") or [])]
    if not any(str(item).strip() for item in executable):
        return ResolutionState.DIAGNOSTIC_ONLY
    return ResolutionState.AWAITING_APPROVAL if requires_approval else ResolutionState.READY_TO_EXECUTE
