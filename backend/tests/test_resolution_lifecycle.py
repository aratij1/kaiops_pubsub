from common.resolution_lifecycle import (
    LifecycleActor,
    LifecycleTransitionError,
    ResolutionState,
    create_lifecycle,
    initial_plan_state,
    plan_fingerprint,
    transition_lifecycle,
    decide_resolution_control,
    select_current_lifecycle,
)
import pytest


def test_plan_identity_is_canonical_and_stable():
    assert plan_fingerprint({"commands": ["restart"], "risk": "low"}) == plan_fingerprint(
        {"risk": "low", "commands": ["restart"]}
    )


def test_diagnostic_plan_is_not_approvable_execution():
    assert initial_plan_state({"queries": ["up"]}, requires_approval=True) == ResolutionState.DIAGNOSTIC_ONLY


def test_resolution_control_only_auto_closes_explicit_watch_only_diagnostics():
    plan = {"plan_kind": "diagnostic", "execution_ready": False, "queries": ["up"]}
    investigate = decide_resolution_control(plan, requires_approval=True)
    watch = decide_resolution_control(plan, requires_approval=True, sources=({"resolution_mode": "watch-only"},))
    assert investigate["disposition"] == "investigate"
    assert investigate["auto_close"] is False
    assert watch["disposition"] == "watch_only"
    assert watch["auto_close"] is True


def test_resolution_control_rejects_watch_only_executable_conflict():
    plan = {"execution_ready": True, "commands": ["kubectl rollout restart deployment/api"]}
    control = decide_resolution_control(plan, requires_approval=False, sources=({"watch_only": True},))
    assert control["disposition"] == "investigate"
    assert control["execution_allowed"] is False
    assert control["auto_close"] is False
    assert control["conflicts"] == ["watch_only_cannot_include_executable_actions"]


def test_retryable_block_preserves_identity_and_increments_version():
    lifecycle = create_lifecycle(
        tenant_id="acme", incident_id="incident-1", recommendation_id="recommendation-1",
        plan={"commands": ["restart"]}, state=ResolutionState.AWAITING_APPROVAL,
    )
    blocked = transition_lifecycle(
        lifecycle,
        ResolutionState.BLOCKED_RETRYABLE,
        actor=LifecycleActor.REMEDIATION,
        reason_code="connector_unavailable",
    )
    assert blocked["state"] == "blocked_retryable"
    assert blocked["retryable"] is True
    assert blocked["state_version"] == lifecycle["state_version"] + 1
    assert blocked["plan_fingerprint"] == lifecycle["plan_fingerprint"]
    assert "retry" in blocked["permitted_actions"]


def test_illegal_transition_is_rejected():
    lifecycle = create_lifecycle(
        tenant_id="acme", incident_id="incident-1", recommendation_id="recommendation-1",
        plan={"commands": ["restart"]}, state=ResolutionState.AWAITING_APPROVAL,
    )
    with pytest.raises(LifecycleTransitionError, match="illegal"):
        transition_lifecycle(lifecycle, ResolutionState.CLOSED, actor=LifecycleActor.CLOSURE)


def test_only_closure_can_declare_recovery():
    lifecycle = create_lifecycle(
        tenant_id="acme", incident_id="incident-1", recommendation_id="recommendation-1",
        plan={"commands": ["restart"]}, state=ResolutionState.VALIDATING,
    )
    with pytest.raises(LifecycleTransitionError, match="actor remediation"):
        transition_lifecycle(lifecycle, ResolutionState.RECOVERED, actor=LifecycleActor.REMEDIATION)


def test_idempotent_same_state_update_does_not_increment_version():
    lifecycle = create_lifecycle(
        tenant_id="acme", incident_id="incident-1", recommendation_id="recommendation-1",
        plan={"queries": ["up"]}, state=ResolutionState.DIAGNOSTIC_ONLY,
        reason_code="no_corrective_capability",
    )
    updated = transition_lifecycle(
        lifecycle,
        ResolutionState.DIAGNOSTIC_ONLY,
        actor=LifecycleActor.REMEDIATION,
        execution={"status": "skipped"},
    )
    assert updated["state_version"] == lifecycle["state_version"]
    assert updated["reason_code"] == "no_corrective_capability"
    assert updated["execution"]["status"] == "skipped"


def test_stale_version_and_wrong_plan_are_rejected():
    lifecycle = create_lifecycle(
        tenant_id="acme", incident_id="incident-1", recommendation_id="recommendation-1",
        plan={"commands": ["restart"]}, state=ResolutionState.READY_TO_EXECUTE,
    )
    with pytest.raises(LifecycleTransitionError, match="stale lifecycle version"):
        transition_lifecycle(
            lifecycle, ResolutionState.EXECUTING, actor=LifecycleActor.REMEDIATION, expected_version=9
        )
    with pytest.raises(LifecycleTransitionError, match="fingerprint"):
        transition_lifecycle(
            lifecycle,
            ResolutionState.EXECUTING,
            actor=LifecycleActor.REMEDIATION,
            expected_plan_fingerprint="sha256:not-the-approved-plan",
        )


def test_current_lifecycle_selection_uses_version_not_source_order():
    older = create_lifecycle(
        tenant_id="acme", incident_id="incident-1", recommendation_id="recommendation-1",
        plan={"commands": ["restart"]}, state=ResolutionState.READY_TO_EXECUTE,
    )
    newer = transition_lifecycle(older, ResolutionState.EXECUTING, actor=LifecycleActor.REMEDIATION)
    selected = select_current_lifecycle(
        {"metadata": {"resolution_lifecycle": older}},
        {"parameters": {"resolution_lifecycle": newer}},
    )
    assert selected == newer
