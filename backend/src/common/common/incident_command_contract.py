from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IncidentEvidenceCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latest_context_records: int = Field(ge=0)
    bound_snapshot_records: int = Field(ge=0)
    rca_bound_records: int = Field(ge=0)
    traceable_citations: int = Field(ge=0)
    unresolved_bindings: int = Field(ge=0)
    open_requirements: int = Field(ge=0)
    open_conflicts: int = Field(ge=0)


class IncidentEvidenceRatio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    percent: int | None = Field(default=None, ge=0, le=100)


class IncidentEvidenceScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Literal["context_quality", "grounding_coverage", "rca_readiness"]
    label: str = Field(min_length=1)
    percent: int | None = Field(default=None, ge=0, le=100)
    status: Literal["available", "blocked", "unavailable"]
    ratio: IncidentEvidenceRatio | None = None
    reason: str = Field(min_length=1)
    blockers: list[str] = Field(default_factory=list)


class IncidentEvidenceReadModel(BaseModel):
    """Backend-owned evidence calculations for one immutable workspace revision."""

    model_config = ConfigDict(extra="forbid")

    latest_snapshot_id: str | None = None
    bound_snapshot_id: str | None = None
    binding_consistent: bool
    counts: IncidentEvidenceCounts
    scores: list[IncidentEvidenceScore]
    blockers: list[str] = Field(default_factory=list)


class IncidentCommandWorkspace(BaseModel):
    """Canonical read contract for the operator incident command page."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="kaiops.incident-command.v2")
    incident_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    incident: dict[str, Any]
    operations: dict[str, Any]
    evidence: IncidentEvidenceReadModel

    @model_validator(mode="after")
    def validate_identity(self) -> IncidentCommandWorkspace:
        incident_identity = str(
            self.incident.get("incident_id") or self.incident.get("id") or ""
        ).strip()
        operations_identity = str(self.operations.get("incident_id") or "").strip()
        if incident_identity != self.incident_id:
            raise ValueError("incident projection identity does not match command workspace")
        if operations_identity != self.incident_id:
            raise ValueError("operations identity does not match command workspace")
        return self


def build_incident_command_workspace(
    *, incident_id: str, incident: dict[str, Any], operations: dict[str, Any]
) -> IncidentCommandWorkspace:
    normalized_incident_id = str(incident_id or "").strip()
    workspace = operations.get("investigation_workspace")
    workspace = workspace if isinstance(workspace, dict) else {}
    binding = workspace.get("binding")
    binding = binding if isinstance(binding, dict) else {}
    summary = workspace.get("evidence_summary")
    summary = summary if isinstance(summary, dict) else {}
    rca = workspace.get("rca")
    rca = rca if isinstance(rca, dict) else {}
    context = operations.get("context")
    context = context if isinstance(context, dict) else {}
    resolution = workspace.get("resolution")
    resolution = resolution if isinstance(resolution, dict) else {}
    requirements = workspace.get("requirements")
    requirements = requirements if isinstance(requirements, list) else []

    def count(name: str) -> int:
        try:
            return max(0, int(summary.get(name) or 0))
        except (TypeError, ValueError):
            return 0

    latest_snapshot_id = str(context.get("snapshot_id") or "").strip() or None
    bound_snapshot_id = str(
        binding.get("context_snapshot_id") or binding.get("snapshot_id") or ""
    ).strip() or None
    unresolved_bindings = count("unresolved_bindings")
    traceable_citations = count("traceable_citations")
    rca_bound_records = count("rca_bound_records")
    open_requirements = sum(
        1 for row in requirements
        if isinstance(row, dict)
        and str(row.get("status") or "").lower() not in {"collected", "answered", "resolved", "cancelled"}
    )
    conflicts = rca.get("conflicting_evidence")
    open_conflicts = len(conflicts) if isinstance(conflicts, list) else 0
    binding_consistent = bool(
        latest_snapshot_id and bound_snapshot_id and latest_snapshot_id == bound_snapshot_id
    )

    blockers: list[str] = []
    if not bound_snapshot_id:
        blockers.append("RCA_SNAPSHOT_NOT_BOUND")
    elif latest_snapshot_id != bound_snapshot_id:
        blockers.append("RCA_SNAPSHOT_STALE")
    if unresolved_bindings:
        blockers.append("RCA_EVIDENCE_BINDING_UNRESOLVED")
    if not traceable_citations:
        blockers.append("RCA_CITATIONS_MISSING")
    if open_requirements:
        blockers.append("EVIDENCE_REQUIREMENTS_OPEN")
    if open_conflicts:
        blockers.append("EVIDENCE_CONFLICTS_OPEN")
    if str(rca.get("status") or "").lower() != "grounded":
        blockers.append("RCA_NOT_GROUNDED")
    if str(resolution.get("status") or "").lower() != "ready":
        blockers.append("RESOLUTION_NOT_READY")

    quality = context.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    quality_value = quality.get("quality_score", quality.get("overall"))
    try:
        quality_percent = round(float(quality_value) * 100) if quality_value is not None else None
    except (TypeError, ValueError):
        quality_percent = None
    if quality_percent is not None:
        quality_percent = max(0, min(100, quality_percent))

    grounding_denominator = rca_bound_records
    grounding_percent = (
        round(min(traceable_citations, grounding_denominator) * 100 / grounding_denominator)
        if grounding_denominator else None
    )
    readiness_checks = [
        str(rca.get("status") or "").lower() == "grounded",
        traceable_citations > 0,
        unresolved_bindings == 0,
        open_requirements == 0,
        open_conflicts == 0,
        str(resolution.get("status") or "").lower() == "ready",
    ]
    readiness_passed = sum(readiness_checks)
    evidence = IncidentEvidenceReadModel(
        latest_snapshot_id=latest_snapshot_id,
        bound_snapshot_id=bound_snapshot_id,
        binding_consistent=binding_consistent,
        counts=IncidentEvidenceCounts(
            latest_context_records=count("latest_context_records"),
            bound_snapshot_records=count("bound_snapshot_records"),
            rca_bound_records=rca_bound_records,
            traceable_citations=traceable_citations,
            unresolved_bindings=unresolved_bindings,
            open_requirements=open_requirements,
            open_conflicts=open_conflicts,
        ),
        scores=[
            IncidentEvidenceScore(
                key="context_quality", label="Context quality", percent=quality_percent,
                status="available" if quality_percent is not None else "unavailable",
                reason=(
                    "Persisted context quality assessment"
                    if quality_percent is not None
                    else "Context quality was not published"
                ),
            ),
            IncidentEvidenceScore(
                key="grounding_coverage", label="Grounding coverage", percent=grounding_percent,
                status=(
                    "available"
                    if grounding_percent is not None and not unresolved_bindings
                    else "blocked" if unresolved_bindings else "unavailable"
                ),
                ratio=IncidentEvidenceRatio(
                    numerator=min(traceable_citations, grounding_denominator),
                    denominator=grounding_denominator,
                    percent=grounding_percent,
                ),
                reason=(
                    "Traceable citations divided by RCA-bound evidence records"
                    if grounding_denominator
                    else "No evidence records are bound to the RCA"
                ),
                blockers=["RCA_EVIDENCE_BINDING_UNRESOLVED"] if unresolved_bindings else [],
            ),
            IncidentEvidenceScore(
                key="rca_readiness", label="RCA readiness",
                percent=round(readiness_passed * 100 / len(readiness_checks)),
                status="available" if not blockers else "blocked",
                ratio=IncidentEvidenceRatio(
                    numerator=readiness_passed, denominator=len(readiness_checks),
                    percent=round(readiness_passed * 100 / len(readiness_checks)),
                ),
                reason="Passed governed RCA and resolution readiness checks",
                blockers=blockers,
            ),
        ],
        blockers=blockers,
    )
    revision_payload = {
        "incident_id": normalized_incident_id,
        "incident": incident,
        "operations": operations,
        "evidence": evidence.model_dump(mode="json"),
    }
    revision = hashlib.sha256(
        json.dumps(revision_payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    return IncidentCommandWorkspace(
        incident_id=normalized_incident_id,
        revision=revision,
        incident=incident,
        operations=operations,
        evidence=evidence,
    )
