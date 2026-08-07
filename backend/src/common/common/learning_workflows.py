from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from common.continuous_learning import (
    ApprovalRequirement,
    ExecutionPolicy,
    FailurePattern,
    FailurePatternAnalyzer,
    HybridRunbookMatcher,
    IncidentDecision,
    IncidentEvidence,
    RunbookVersion,
)


class ReadOnlyEvidenceConnector(Protocol):
    """Authenticated connector contract; implementations must not mutate sources."""

    connector_id: str
    source_type: str
    read_only: bool

    async def collect(self, *, since_cursor: str | None = None) -> tuple[list[IncidentEvidence], str | None]: ...


class LearningStore(Protocol):
    async def save_evidence(self, evidence: IncidentEvidence) -> None: ...
    async def list_evidence(self) -> list[IncidentEvidence]: ...
    async def replace_patterns(self, patterns: Sequence[FailurePattern]) -> None: ...
    async def list_approved_runbooks(self, *, service: str) -> list[RunbookVersion]: ...
    async def record_connector_cursor(self, connector_id: str, cursor: str | None) -> None: ...


@dataclass(slots=True)
class Mode02Result:
    collected: int
    patterns: list[FailurePattern]
    draftable_pattern_ids: list[str]


class Mode02Worker:
    def __init__(self, store: LearningStore, connectors: Iterable[ReadOnlyEvidenceConnector]) -> None:
        self.store = store
        self.connectors = list(connectors)
        self.analyzer = FailurePatternAnalyzer()

    async def run_once(self) -> Mode02Result:
        collected = 0
        for connector in self.connectors:
            if not connector.read_only:
                raise ValueError(f"connector {connector.connector_id} is not read-only")
            evidence_rows, cursor = await connector.collect()
            for evidence in evidence_rows:
                await self.store.save_evidence(evidence)
                collected += 1
            await self.store.record_connector_cursor(connector.connector_id, cursor)
        patterns = self.analyzer.analyze(await self.store.list_evidence())
        await self.store.replace_patterns(patterns)
        return Mode02Result(
            collected=collected,
            patterns=patterns,
            draftable_pattern_ids=[p.pattern_id for p in patterns if self.analyzer.can_draft(p)],
        )


RootCauseValidator = Callable[[IncidentEvidence], Awaitable[dict[str, object]]]


class Mode01Workflow:
    """Selects knowledge and policy; execution remains in KaiMS orchestration."""

    def __init__(self, store: LearningStore, validate_root_cause: RootCauseValidator) -> None:
        self.store = store
        self.validate_root_cause = validate_root_cause
        self.matcher = HybridRunbookMatcher()

    async def resolve(self, evidence: IncidentEvidence) -> IncidentDecision:
        matches = self.matcher.rank(
            evidence,
            await self.store.list_approved_runbooks(service=evidence.service),
        )
        analysis = await self.validate_root_cause(evidence)
        confidence = float(analysis.get("confidence", 0.0))
        risk = str(analysis.get("risk", "medium")).lower()
        blast_radius = str(analysis.get("blast_radius", "unknown")).lower()
        conflict = bool(analysis.get("conflicting_evidence", False))
        selected = matches[0].runbook if matches and matches[0].deterministic_score > 0 else None
        approval = ExecutionPolicy.decide(
            confidence=confidence,
            risk=risk,
            blast_radius=blast_radius,
            approved_runbook=selected is not None,
            destructive=bool(analysis.get("destructive", False)),
            production_database=bool(analysis.get("production_database", False)),
            security_incident=bool(analysis.get("security_incident", False)),
            conflicting_evidence=conflict,
        )
        abstained = approval == ApprovalRequirement.ESCALATE
        return IncidentDecision(
            incident_id=evidence.incident_id,
            classification=str(analysis.get("classification", evidence.alert_type)),
            severity=str(analysis.get("severity", "unknown")),
            root_cause=str(analysis.get("root_cause", "insufficient evidence")),
            confidence=confidence,
            supporting_evidence=evidence.references,
            affected_services=[evidence.service, *evidence.dependencies],
            dependency_impact=str(analysis.get("dependency_impact", "unknown")),
            user_impact=str(analysis.get("user_impact", "unknown")),
            business_impact=str(analysis.get("business_impact", "unknown")),
            selected_runbook=selected.runbook_id if selected else None,
            recommended_action=(
                "escalate for evidence review"
                if abstained
                else str(analysis.get("recommended_action", "follow selected runbook"))
            ),
            risk=risk,
            blast_radius=blast_radius,
            approval_requirement=approval,
            abstained=abstained,
            rationale=[
                "Root cause was independently validated; semantic similarity alone cannot authorize execution.",
                f"Policy selected {approval.value} at confidence {confidence:.2f}.",
            ],
        )
