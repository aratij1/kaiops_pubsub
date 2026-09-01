from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ResolutionWorkflowState(StrEnum):
    EVIDENCE_PENDING = "evidence_pending"
    EVIDENCE_READY = "evidence_ready"
    HYPOTHESES_READY = "hypotheses_ready"
    PLAN_SELECTED = "plan_selected"
    POLICY_CHECKED = "policy_checked"
    AWAITING_APPROVAL = "awaiting_approval"
    READY_TO_EXECUTE = "ready_to_execute"
    EXECUTING = "executing"
    VALIDATING = "validating"
    RESOLVED = "resolved"
    ROLLED_BACK = "rolled_back"
    ESCALATED = "escalated"


ALLOWED_WORKFLOW_TRANSITIONS = {
    ResolutionWorkflowState.EVIDENCE_PENDING: {ResolutionWorkflowState.EVIDENCE_READY, ResolutionWorkflowState.ESCALATED},
    ResolutionWorkflowState.EVIDENCE_READY: {ResolutionWorkflowState.HYPOTHESES_READY, ResolutionWorkflowState.ESCALATED},
    ResolutionWorkflowState.HYPOTHESES_READY: {ResolutionWorkflowState.PLAN_SELECTED, ResolutionWorkflowState.EVIDENCE_PENDING, ResolutionWorkflowState.ESCALATED},
    ResolutionWorkflowState.PLAN_SELECTED: {ResolutionWorkflowState.POLICY_CHECKED, ResolutionWorkflowState.ESCALATED},
    ResolutionWorkflowState.POLICY_CHECKED: {ResolutionWorkflowState.AWAITING_APPROVAL, ResolutionWorkflowState.READY_TO_EXECUTE, ResolutionWorkflowState.EVIDENCE_PENDING, ResolutionWorkflowState.ESCALATED},
    ResolutionWorkflowState.AWAITING_APPROVAL: {ResolutionWorkflowState.READY_TO_EXECUTE, ResolutionWorkflowState.ESCALATED},
    ResolutionWorkflowState.READY_TO_EXECUTE: {ResolutionWorkflowState.EXECUTING, ResolutionWorkflowState.ESCALATED},
    ResolutionWorkflowState.EXECUTING: {ResolutionWorkflowState.VALIDATING, ResolutionWorkflowState.ROLLED_BACK, ResolutionWorkflowState.ESCALATED},
    ResolutionWorkflowState.VALIDATING: {ResolutionWorkflowState.RESOLVED, ResolutionWorkflowState.ROLLED_BACK, ResolutionWorkflowState.ESCALATED},
    ResolutionWorkflowState.ROLLED_BACK: {ResolutionWorkflowState.ESCALATED},
    ResolutionWorkflowState.RESOLVED: set(),
    ResolutionWorkflowState.ESCALATED: set(),
}


class ResolutionTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    transition_id: UUID = Field(default_factory=uuid4)
    tenant_id: str = "default"
    incident_id: str
    recommendation_id: UUID | None = None
    execution_plan_id: UUID | None = None
    previous_state: ResolutionWorkflowState
    new_state: ResolutionWorkflowState
    event_id: UUID
    correlation_id: str | None = None
    causation_id: str | None = None
    idempotency_key: str
    actor: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason_code: str
    evidence_ids: list[str] = Field(default_factory=list)
    policy_decision: dict[str, Any] = Field(default_factory=dict)


def transition_idempotency_key(
    incident_id: str, event_id: UUID | str, new_state: ResolutionWorkflowState | str
) -> str:
    canonical = f"{incident_id}:{event_id}:{new_state}".lower()
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_workflow_transition(previous: ResolutionWorkflowState, new: ResolutionWorkflowState) -> None:
    if new not in ALLOWED_WORKFLOW_TRANSITIONS[previous]:
        raise ValueError(f"illegal resolution workflow transition: {previous.value} -> {new.value}")
