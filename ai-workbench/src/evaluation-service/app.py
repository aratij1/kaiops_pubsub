from __future__ import annotations

from typing import Any

from common.config import get_settings
from common.repository import EvaluationRepository
from common.service import create_app
from fastapi import Body, HTTPException
from pydantic import BaseModel

settings = get_settings()
settings.service_name = "evaluation-service"

app = create_app(title="KaiMS Evaluation Service", settings=settings)


class EvaluationCreateRequest(BaseModel):
    report: dict[str, Any]
    agent: str
    incident_id: str | None = None
    recommendation_id: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    evaluation_id: str | None = None


class EvaluationFeedbackRequest(BaseModel):
    decision: str
    approver: str | None = None
    comment: str | None = None


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
            evaluation_id = await repo.save_evaluation(
                report=payload.report,
                agent=payload.agent,
                incident_id=payload.incident_id,
                recommendation_id=payload.recommendation_id,
                model_provider=payload.model_provider,
                model_name=payload.model_name,
                evaluation_id=payload.evaluation_id,
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


@app.get("/evaluations/{evaluation_id}")
async def get_evaluation(evaluation_id: str) -> dict[str, Any]:
    _require_storage()
    try:
        async with app.state.session_factory() as session:
            repo = EvaluationRepository(session)
            record = await repo.get_evaluation(evaluation_id)
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
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"evaluations": rows, "count": len(rows)}
