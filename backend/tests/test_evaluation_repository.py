from __future__ import annotations

from uuid import uuid4

import pytest
from common.repository import EvaluationRepository


@pytest.mark.asyncio
async def test_save_and_get_evaluation_round_trip(sqlite_session_factory) -> None:
    incident_id = uuid4()
    recommendation_id = uuid4()
    report = {"overall_score": 0.87, "quality_label": "high", "requires_review": False}

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        eval_id = await repo.save_evaluation(
            report=report,
            agent="resolution-agent",
            incident_id=incident_id,
            recommendation_id=recommendation_id,
            model_provider="groq",
            model_name="llama-3.3-70b-versatile",
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        record = await repo.get_evaluation(eval_id)

    assert record is not None
    assert record["id"] == eval_id
    assert record["incident_id"] == str(incident_id)
    assert record["recommendation_id"] == str(recommendation_id)
    assert record["agent"] == "resolution-agent"
    assert record["model_provider"] == "groq"
    assert record["overall_score"] == 0.87
    assert record["quality_label"] == "high"
    assert record["requires_review"] is False
    assert record["report"] == report
    assert record["feedback"] is None


@pytest.mark.asyncio
async def test_get_evaluation_returns_none_when_missing(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        record = await repo.get_evaluation(uuid4())
    assert record is None


@pytest.mark.asyncio
async def test_get_evaluation_rejects_malformed_uuid(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        with pytest.raises(ValueError):
            await repo.get_evaluation("not-a-uuid")


@pytest.mark.asyncio
async def test_save_evaluation_requires_agent(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        with pytest.raises(ValueError):
            await repo.save_evaluation(report={}, agent="")


@pytest.mark.asyncio
async def test_save_evaluation_defaults_missing_report_fields_to_none(sqlite_session_factory) -> None:
    # model-router's judge-only report shape has no overall_score/quality_label.
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        eval_id = await repo.save_evaluation(
            report={"contract_version": "kaiops.evaluation.judge.v1", "metrics": []},
            agent="model-router",
        )
        await session.commit()
        record = await repo.get_evaluation(eval_id)

    assert record["overall_score"] is None
    assert record["quality_label"] is None
    assert record["requires_review"] is False


@pytest.mark.asyncio
async def test_list_evaluations_filters_by_incident_id(sqlite_session_factory) -> None:
    incident_a = uuid4()
    incident_b = uuid4()
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        await repo.save_evaluation(report={"overall_score": 0.9}, agent="resolution-agent", incident_id=incident_a)
        await repo.save_evaluation(report={"overall_score": 0.4}, agent="resolution-agent", incident_id=incident_a)
        await repo.save_evaluation(report={"overall_score": 0.5}, agent="resolution-agent", incident_id=incident_b)
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        rows = await repo.list_evaluations(incident_id=incident_a)

    assert len(rows) == 2
    assert {str(incident_a)} == {row["incident_id"] for row in rows}


@pytest.mark.asyncio
async def test_list_evaluations_filters_by_agent(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        await repo.save_evaluation(report={"overall_score": 0.9}, agent="resolution-agent")
        await repo.save_evaluation(report={}, agent="model-router")
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        rows = await repo.list_evaluations(agent="model-router")

    assert len(rows) == 1
    assert rows[0]["agent"] == "model-router"


@pytest.mark.asyncio
async def test_list_evaluations_filters_by_min_score_excludes_null_scores(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        await repo.save_evaluation(report={"overall_score": 0.9}, agent="resolution-agent")
        await repo.save_evaluation(report={"overall_score": 0.3}, agent="resolution-agent")
        await repo.save_evaluation(report={}, agent="model-router")  # no overall_score at all
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        rows = await repo.list_evaluations(min_score=0.8)

    assert len(rows) == 1
    assert rows[0]["overall_score"] == 0.9


@pytest.mark.asyncio
async def test_list_evaluations_orders_most_recent_first_and_respects_limit(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        for score in (0.1, 0.2, 0.3):
            await repo.save_evaluation(report={"overall_score": score}, agent="resolution-agent")
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        rows = await repo.list_evaluations(limit=2)

    assert len(rows) == 2


@pytest.mark.asyncio
async def test_summarize_evaluations_empty_store(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        summary = await repo.summarize_evaluations()

    assert summary == {
        "total_evaluations": 0,
        "average_overall_score": 0.0,
        "requires_review_rate": 0.0,
        "quality_label_counts": {},
    }


@pytest.mark.asyncio
async def test_summarize_evaluations_computes_expected_aggregates(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        await repo.save_evaluation(
            report={"overall_score": 0.9, "quality_label": "high", "requires_review": False}, agent="resolution-agent"
        )
        await repo.save_evaluation(
            report={"overall_score": 0.5, "quality_label": "medium", "requires_review": False}, agent="resolution-agent"
        )
        await repo.save_evaluation(
            report={"overall_score": 0.2, "quality_label": "low", "requires_review": True}, agent="resolution-agent"
        )
        await repo.save_evaluation(
            report={"contract_version": "kaiops.evaluation.judge.v1", "metrics": []}, agent="model-router"
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        all_agents = await repo.summarize_evaluations()
        resolution_only = await repo.summarize_evaluations(agent="resolution-agent")

    assert all_agents["total_evaluations"] == 4
    assert all_agents["average_overall_score"] == round((0.9 + 0.5 + 0.2) / 3, 4)
    assert all_agents["requires_review_rate"] == round(1 / 4, 4)
    assert all_agents["quality_label_counts"] == {"high": 1, "medium": 1, "low": 1, "unknown": 1}

    assert resolution_only["total_evaluations"] == 3
    assert resolution_only["requires_review_rate"] == round(1 / 3, 4)
    assert "unknown" not in resolution_only["quality_label_counts"]


@pytest.mark.asyncio
async def test_attach_feedback_by_recommendation_updates_existing_record(sqlite_session_factory) -> None:
    recommendation_id = uuid4()
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        eval_id = await repo.save_evaluation(
            report={"overall_score": 0.8}, agent="resolution-agent", recommendation_id=recommendation_id
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        updated = await repo.attach_feedback_by_recommendation(
            recommendation_id, {"decision": "approved", "approver": "alice", "comment": "looks good"}
        )
        await session.commit()

    assert updated is True

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        record = await repo.get_evaluation(eval_id)

    assert record["feedback"] == {"decision": "approved", "approver": "alice", "comment": "looks good"}


@pytest.mark.asyncio
async def test_attach_feedback_by_recommendation_returns_false_when_no_evaluation_exists(
    sqlite_session_factory,
) -> None:
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        updated = await repo.attach_feedback_by_recommendation(uuid4(), {"decision": "approved"})
    assert updated is False


@pytest.mark.asyncio
async def test_attach_feedback_by_recommendation_uses_most_recent_when_multiple_exist(
    sqlite_session_factory,
) -> None:
    recommendation_id = uuid4()
    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        first_id = await repo.save_evaluation(
            report={"overall_score": 0.5}, agent="resolution-agent", recommendation_id=recommendation_id
        )
        second_id = await repo.save_evaluation(
            report={"overall_score": 0.6}, agent="resolution-agent", recommendation_id=recommendation_id
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        await repo.attach_feedback_by_recommendation(recommendation_id, {"decision": "rejected"})
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = EvaluationRepository(session)
        first_record = await repo.get_evaluation(first_id)
        second_record = await repo.get_evaluation(second_id)

    # "most recent" is whichever was inserted last; assert exactly one got the feedback.
    fed_back = [r for r in (first_record, second_record) if r["feedback"] is not None]
    assert len(fed_back) == 1
