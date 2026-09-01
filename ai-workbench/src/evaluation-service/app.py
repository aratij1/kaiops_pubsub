from __future__ import annotations

from datetime import timedelta
from typing import Any

from common.config import get_settings
from common.repository import EvaluationRepository
from common.learning_contracts import AgentOpsTrace, IncidentMemoryRecord, PromotionEvidence, assess_autonomy_promotion
from common.differentiator_contracts import (
    CodePatchProposal,
    EvidenceCouncilDecision,
    PreventiveRecommendation,
    TemporalServiceGraph,
)
from common.service import create_app
from common.models import utc_now
from fastapi import Body, HTTPException
from pydantic import BaseModel, Field, model_validator

settings = get_settings()
settings.service_name = "evaluation-service"

app = create_app(title="KaiMS Evaluation Service", settings=settings)


class EvaluationCreateRequest(BaseModel):
    report: dict[str, Any]
    tenant_id: str = "default"
    retention_days: int = Field(default=90, ge=7, le=2555)
    artifact_signature: str | None = None
    agent: str
    incident_id: str | None = None
    recommendation_id: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    evaluation_id: str | None = None
    outcome_label: str | None = None
    incident_memory: IncidentMemoryRecord | None = None
    agent_trace: AgentOpsTrace | None = None
    code_patch_proposals: list[CodePatchProposal] = Field(default_factory=list)
    temporal_service_graph: TemporalServiceGraph | None = None
    evidence_council: EvidenceCouncilDecision | None = None
    preventive_recommendations: list[PreventiveRecommendation] = Field(default_factory=list)


class EvaluationFeedbackRequest(BaseModel):
    decision: str
    approver: str | None = None
    comment: str | None = None
    reason_category: str | None = None
    corrected_cause: str | None = None
    missing_evidence: str | None = None

    @model_validator(mode="after")
    def validate_structured_review(self) -> EvaluationFeedbackRequest:
        decision = self.decision.strip().lower()
        if decision in {"incorrect", "incomplete"} and not str(self.reason_category or "").strip():
            raise ValueError("reason_category is required when feedback is incorrect or incomplete")
        return self


class RetentionSweepRequest(BaseModel):
    tenant_id: str
    limit: int = Field(default=100, ge=1, le=1000)


def _require_storage() -> None:
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        raise HTTPException(status_code=503, detail="Database is required for the evaluation service")


@app.post("/evaluations", status_code=201)
async def create_evaluation(payload: EvaluationCreateRequest = Body(...)) -> dict[str, Any]:
    # Note: report is intentionally accepted as an opaque dict rather than strictly validated
    # against ai_workbench_common.model_evaluation.EvaluationReport. That contract describes
    # resolution-agent's deterministic quality-gate report specifically; model-router's
    # LLM-judge output (metric/score/confidence per requested metric) is a different, equally
    # valid evaluation shape. Both are accepted here; EvaluationRecord's promoted columns
    # (overall_score/quality_label/requires_review) simply stay unset for shapes that don't
    # define them.
    _require_storage()
    if not payload.report:
        raise HTTPException(status_code=422, detail="report must not be empty")

    try:
        async with app.state.session_factory() as session:
            repo = EvaluationRepository(session)
            enriched_report = dict(payload.report)
            if payload.outcome_label is not None:
                enriched_report["outcome_label"] = payload.outcome_label
            if payload.incident_memory is not None:
                enriched_report["incident_memory"] = payload.incident_memory.model_dump(mode="json")
            if payload.agent_trace is not None:
                enriched_report["agent_trace"] = payload.agent_trace.model_dump(mode="json")
            if payload.code_patch_proposals:
                enriched_report["code_patch_proposals"] = [item.model_dump(mode="json") for item in payload.code_patch_proposals]
            if payload.temporal_service_graph is not None:
                enriched_report["temporal_service_graph"] = payload.temporal_service_graph.model_dump(mode="json")
            if payload.evidence_council is not None:
                enriched_report["evidence_council"] = payload.evidence_council.model_dump(mode="json")
            if payload.preventive_recommendations:
                enriched_report["preventive_recommendations"] = [item.model_dump(mode="json") for item in payload.preventive_recommendations]
            evaluation_id = await repo.save_evaluation(
                report=enriched_report,
                agent=payload.agent,
                incident_id=payload.incident_id,
                recommendation_id=payload.recommendation_id,
                model_provider=payload.model_provider,
                model_name=payload.model_name,
                evaluation_id=payload.evaluation_id,
                tenant_id=payload.tenant_id,
                expires_at=utc_now() + timedelta(days=payload.retention_days),
                artifact_signature=payload.artifact_signature,
            )
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": evaluation_id}


@app.get("/evaluations/summary")
async def summarize_evaluations(agent: str | None = None, limit: int = 1000) -> dict[str, Any]:
    # Registered before /evaluations/{evaluation_id} so "summary" is never matched as an id.
    _require_storage()
    async with app.state.session_factory() as session:
        repo = EvaluationRepository(session)
        return await repo.summarize_evaluations(agent=agent, limit=limit)


@app.post("/evaluations/autonomy/assess")
async def assess_autonomy(payload: PromotionEvidence = Body(...)) -> dict[str, Any]:
    """Return an evidence-based recommendation; never mutates autonomy policy."""
    return assess_autonomy_promotion(payload).model_dump(mode="json")


@app.post("/evaluations/retention/sweep")
async def sweep_expired_evaluations(payload: RetentionSweepRequest = Body(...)) -> dict[str, Any]:
    """Delete one bounded tenant slice; the repository preserves an audit tombstone per row."""
    _require_storage()
    try:
        async with app.state.session_factory() as session:
            repo = EvaluationRepository(session)
            purged_ids = await repo.purge_expired_evaluations(
                tenant_id=payload.tenant_id,
                now=utc_now(),
                limit=payload.limit,
            )
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"purged_ids": purged_ids, "count": len(purged_ids)}


@app.get("/evaluations/{evaluation_id}")
async def get_evaluation(evaluation_id: str, tenant_id: str = "default") -> dict[str, Any]:
    _require_storage()
    try:
        async with app.state.session_factory() as session:
            repo = EvaluationRepository(session)
            record = await repo.get_evaluation(evaluation_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="evaluation not found")
    return record


@app.post("/evaluations/by-recommendation/{recommendation_id}/feedback")
async def attach_evaluation_feedback(
    recommendation_id: str,
    payload: EvaluationFeedbackRequest = Body(...),
) -> dict[str, Any]:
    """Links a human approval decision back to the evaluation for that recommendation.

    Returns {"updated": false} rather than a 404 when no evaluation exists yet for this
    recommendation -- e.g. evaluation-service was unreachable when it was generated -- since
    that is an expected, non-error outcome for a best-effort feedback loop.
    """
    _require_storage()
    feedback = {
        "decision": payload.decision,
        "approver": payload.approver,
        "comment": payload.comment,
    }
    for field in ("reason_category", "corrected_cause", "missing_evidence"):
        value = getattr(payload, field)
        if value is not None:
            feedback[field] = value
    try:
        async with app.state.session_factory() as session:
            repo = EvaluationRepository(session)
            updated = await repo.attach_feedback_by_recommendation(recommendation_id, feedback)
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"updated": updated}


@app.get("/evaluations")
async def list_evaluations(
    incident_id: str | None = None,
    agent: str | None = None,
    min_score: float | None = None,
    limit: int = 100,
    tenant_id: str = "default",
) -> dict[str, Any]:
    _require_storage()
    try:
        async with app.state.session_factory() as session:
            repo = EvaluationRepository(session)
            rows = await repo.list_evaluations(
                incident_id=incident_id,
                agent=agent,
                min_score=min_score,
                limit=limit,
                tenant_id=tenant_id,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"evaluations": rows, "count": len(rows)}
