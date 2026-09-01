from uuid import uuid4

import pytest

from resolution_agent.workflow import ResolutionWorkflowState, transition_idempotency_key, validate_workflow_transition


def test_target_resolution_state_machine_allows_happy_hitl_path() -> None:
    path = [
        ResolutionWorkflowState.EVIDENCE_PENDING,
        ResolutionWorkflowState.EVIDENCE_READY,
        ResolutionWorkflowState.HYPOTHESES_READY,
        ResolutionWorkflowState.PLAN_SELECTED,
        ResolutionWorkflowState.POLICY_CHECKED,
        ResolutionWorkflowState.AWAITING_APPROVAL,
        ResolutionWorkflowState.READY_TO_EXECUTE,
        ResolutionWorkflowState.EXECUTING,
        ResolutionWorkflowState.VALIDATING,
        ResolutionWorkflowState.RESOLVED,
    ]
    for previous, new in zip(path, path[1:]):
        validate_workflow_transition(previous, new)


def test_target_resolution_state_machine_rejects_skipped_validation() -> None:
    with pytest.raises(ValueError, match="illegal"):
        validate_workflow_transition(ResolutionWorkflowState.EXECUTING, ResolutionWorkflowState.RESOLVED)


def test_transition_idempotency_is_stable() -> None:
    event_id = uuid4()
    first = transition_idempotency_key("incident-1", event_id, ResolutionWorkflowState.EVIDENCE_READY)
    second = transition_idempotency_key("incident-1", event_id, ResolutionWorkflowState.EVIDENCE_READY)
    assert first == second
