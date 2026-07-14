from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    NEW = "new"
    INVESTIGATING = "investigating"
    ANALYZING = "analyzing"
    APPROVAL = "approval"
    EXECUTING = "executing"
    VALIDATING = "validating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class WorkflowStateMachine:
    _transitions: dict[WorkflowState, set[WorkflowState]] = {
        WorkflowState.NEW: {WorkflowState.INVESTIGATING},
        WorkflowState.INVESTIGATING: {WorkflowState.ANALYZING, WorkflowState.APPROVAL},
        WorkflowState.ANALYZING: {WorkflowState.APPROVAL, WorkflowState.EXECUTING},
        WorkflowState.APPROVAL: {WorkflowState.EXECUTING, WorkflowState.CLOSED},
        WorkflowState.EXECUTING: {WorkflowState.VALIDATING, WorkflowState.CLOSED},
        WorkflowState.VALIDATING: {WorkflowState.RESOLVED, WorkflowState.CLOSED},
        WorkflowState.RESOLVED: {WorkflowState.CLOSED},
        WorkflowState.CLOSED: set(),
    }

    def can_transition(self, current: WorkflowState, target: WorkflowState) -> bool:
        return target in self._transitions.get(current, set())
