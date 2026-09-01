from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from common.config import get_settings
from common.continuous_learning import FailurePattern, FailurePatternAnalyzer, IncidentEvidence, issue_signature
from common.database import ActionRecord, FailurePatternRecord, IncidentEvidenceRecord, IncidentRecord, KnowledgeBaseRecord, LearningAuditRecord, RcaReportRecord, RunbookOutcomeRecord, RunbookVersionRecord
from common.learning_workflows import Mode02Worker
from common.models import EvidenceReference
from common.service import create_app
from fastapi import FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select, text

settings = get_settings()
settings.service_name = "knowledge-development-worker"
interval_seconds = max(300, int(os.getenv("KNOWLEDGE_DEVELOPMENT_INTERVAL_SECONDS", "21600")))
batch_size = max(25, min(int(os.getenv("KNOWLEDGE_DEVELOPMENT_BATCH_SIZE", "500")), 2000))
task: asyncio.Task | None = None
run_lock = asyncio.Lock()
schedule_wakeup = asyncio.Event()
last_result: dict[str, Any] = {"status": "not_run"}
schedule_config: dict[str, Any] = {
    "enabled": True, "interval_seconds": interval_seconds, "lookback_days": 30,
    "application_scope": "all", "collect_logs": True, "collect_metrics": True,
    "collect_traces": True, "collect_tickets": True, "collect_changes": True,
    "minimum_occurrences": 3, "minimum_confidence": 0.70,
    "minimum_success_rate": 0.80, "minimum_reviewed_incidents": 2,
}
configuration_id = uuid5(NAMESPACE_URL, "kaims:knowledge-development:configuration:default")
state_id = uuid5(NAMESPACE_URL, "kaims:knowledge-development:state:default")
lock_name = "kaims_knowledge_development_default"


class ScheduleConfig(BaseModel):
    enabled: bool = True
    interval_hours: int = Field(default=6, ge=1, le=168)
    lookback_days: int = Field(default=30, ge=1, le=365)
    application_scope: str = Field(default="all", max_length=255)
    collect_logs: bool = True
    collect_metrics: bool = True
    collect_traces: bool = True
    collect_tickets: bool = True
    collect_changes: bool = True
    minimum_occurrences: int = Field(default=3, ge=2, le=100)
    minimum_confidence: float = Field(default=0.70, ge=0.5, le=0.99)
    minimum_success_rate: float = Field(default=0.80, ge=0.5, le=1.0)
    minimum_reviewed_incidents: int = Field(default=2, ge=1, le=100)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    value = _utc(value)
    return value.isoformat() if value else None


def _hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _quality_gate(pattern: FailurePattern, evidence_by_id: dict[str, IncidentEvidence]) -> dict[str, Any]:
    rows = [evidence_by_id[item] for item in pattern.incident_ids if item in evidence_by_id]
    reviewed = sum(row.reviewed for row in rows)
    successful = sum(row.resolution_successful is True for row in rows)
    resolved = sum(row.resolution_successful is not None for row in rows)
    success_rate = successful / resolved if resolved else 0.0
    sources = len({ref.source for ref in pattern.evidence_references})
    checks = {
        "occurrences": pattern.occurrence_frequency >= int(schedule_config["minimum_occurrences"]),
        "confidence": pattern.confidence >= float(schedule_config["minimum_confidence"]),
        "reviewed_incidents": reviewed >= int(schedule_config["minimum_reviewed_incidents"]),
        "success_rate": success_rate >= float(schedule_config["minimum_success_rate"]),
        "independent_sources": sources >= 2,
        "successful_resolution": bool(pattern.successful_resolutions),
        "no_conflicts": not pattern.conflicts,
    }
    return {
        "passed": all(checks.values()), "checks": checks,
        "metrics": {"occurrences": pattern.occurrence_frequency, "confidence": round(pattern.confidence, 4), "reviewed_incidents": reviewed, "resolved_incidents": resolved, "success_rate": round(success_rate, 4), "independent_sources": sources},
        "policy_version": "kaims.knowledge-quality.v2",
    }


async def _load_state(app: FastAPI) -> dict[str, Any]:
    if not settings.database_enabled:
        return {}
    async with app.state.session_factory() as session:
        row = await session.get(KnowledgeBaseRecord, state_id)
        return dict(row.payload) if row and isinstance(row.payload, dict) else {}


async def _save_state(session: Any, payload: dict[str, Any]) -> None:
    await session.merge(KnowledgeBaseRecord(id=state_id, tenant_id="default", service="KaiMS", title="Periodic knowledge development durable state", content=json.dumps(payload, sort_keys=True), embedding_ref=None, payload=payload))


async def _draft_candidate(session: Any, pattern: FailurePattern, quality: dict[str, Any]) -> bool:
    if not quality["passed"]:
        return False
    runbook_id = uuid5(NAMESPACE_URL, f"kaims:runbook:default:{pattern.issue_signature}")
    latest = (await session.execute(select(RunbookVersionRecord).where(RunbookVersionRecord.runbook_id == runbook_id).order_by(RunbookVersionRecord.version.desc()).limit(1))).scalar_one_or_none()
    draft = Mode02Worker._draft_runbook(pattern)
    payload = draft.model_dump(mode="json", exclude={"runbook_id", "created_at", "version"})
    payload.update({
        "runbook_id": str(runbook_id), "name": f"Resolve {pattern.alert_type} for {pattern.service}",
        "application": pattern.service, "environment": pattern.environment,
        "matching_conditions": {"issue_signature": pattern.issue_signature},
        "supporting_evidence": [item.model_dump(mode="json") for item in pattern.evidence_references[:50]],
        "review_state": "awaiting_hitl_review", "knowledge_quality": quality,
        "generation_policy": "immutable-challenger-v2",
    })
    candidate_hash = _hash(payload)
    latest_payload = latest.content if latest and isinstance(latest.content, dict) else {}
    if latest and latest_payload.get("content_sha256") == candidate_hash:
        return False
    version = latest.version + 1 if latest else 1
    payload.update({"version": version, "content_sha256": candidate_hash})
    session.add(RunbookVersionRecord(runbook_id=runbook_id, version=version, tenant_id="default", issue_signature=pattern.issue_signature, approval_status="draft", owner=draft.owner, risk_level=draft.risk_level, required_approval="mandatory", content=payload))
    audit = {"status": "draft", "version": version, "issue_signature": pattern.issue_signature, "content_sha256": candidate_hash, "quality_gate": quality, "requires_human_approval": True}
    session.add(LearningAuditRecord(event_id=uuid5(NAMESPACE_URL, f"kaims:audit:runbook-drafted:{runbook_id}:{version}"), tenant_id="default", actor="knowledge-development-worker", action="runbook.challenger_drafted", resource_type="runbook", resource_id=str(runbook_id), payload=audit, payload_sha256=_hash(audit), occurred_at=datetime.now(timezone.utc)))
    return True


def _build_evidence(report: RcaReportRecord, incident: IncidentRecord, latest_action: ActionRecord | None) -> IncidentEvidence:
    report_payload = report.payload if isinstance(report.payload, dict) else {}
    action_payload = latest_action.payload if latest_action and isinstance(latest_action.payload, dict) else {}
    validation = action_payload.get("validation") if isinstance(action_payload.get("validation"), dict) else {}
    action_status = str(getattr(latest_action, "status", "") or "").lower()
    validated = bool(action_status.endswith("succeeded") and report_payload.get("health_restored") and report_payload.get("alerts_cleared") and validation.get("passed", True))
    failed = action_status.endswith("failed") or action_status.endswith("rolled_back")
    return IncidentEvidence(
        incident_id=str(incident.id), service=incident.service, environment=incident.environment,
        alert_type=str((incident.payload or {}).get("alert_type") or incident.title),
        symptoms=[str((incident.payload or {}).get("summary") or incident.title)],
        timestamps=[value for value in [_utc(incident.created_at)] if value],
        logs=[EvidenceReference(evidence_id=f"report-{report.id}", source="incident-history", uri=f"report://{report.id}", summary=report.root_cause)] if schedule_config["collect_logs"] else [],
        related_tickets=[EvidenceReference(evidence_id=f"ticket-{incident.ticket_id}", source="itsm", uri=f"ticket://{incident.ticket_id}", summary=incident.title)] if incident.ticket_id and schedule_config["collect_tickets"] else [],
        resolution=str(report_payload.get("action_taken") or action_payload.get("action_type") or "") or None,
        root_causes=[report.root_cause] if report.root_cause else [],
        resolution_successful=True if validated else (False if failed else None), reviewed=validated,
    )


async def _analyze_locked(app: FastAPI, trigger: str) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    cutoff = started - timedelta(days=int(schedule_config["lookback_days"]))
    previous = await _load_state(app)
    checkpoint = _utc(datetime.fromisoformat(str(previous["checkpoint_at"]))) if previous.get("checkpoint_at") else None
    checkpoint_id = str(previous.get("checkpoint_id") or "").strip()
    scope = str(schedule_config["application_scope"]).strip().lower()
    async with app.state.session_factory() as session:
        report_query = select(RcaReportRecord)
        if checkpoint and checkpoint_id:
            report_query = report_query.where(
                or_(
                    RcaReportRecord.created_at > checkpoint,
                    and_(RcaReportRecord.created_at == checkpoint, RcaReportRecord.id > UUID(checkpoint_id)),
                )
            )
        elif checkpoint:
            report_query = report_query.where(RcaReportRecord.created_at > checkpoint)
        else:
            report_query = report_query.where(RcaReportRecord.created_at >= cutoff)
        reports = (await session.execute(report_query.order_by(RcaReportRecord.created_at.asc(), RcaReportRecord.id.asc()).limit(batch_size))).scalars().all()
        incident_ids = {row.incident_id for row in reports}
        incidents = {str(row.id): row for row in (await session.execute(select(IncidentRecord).where(IncidentRecord.id.in_(incident_ids)))).scalars().all()} if incident_ids else {}
        actions: dict[str, list[ActionRecord]] = {}
        if incident_ids:
            for row in (await session.execute(select(ActionRecord).where(ActionRecord.incident_id.in_(incident_ids)))).scalars().all():
                actions.setdefault(str(row.incident_id), []).append(row)
        collected = 0
        max_checkpoint = checkpoint
        max_checkpoint_id = checkpoint_id or None
        for report in reports:
            incident = incidents.get(str(report.incident_id))
            if not incident:
                continue
            service = str(incident.service or "").lower()
            application = str((incident.payload or {}).get("application") or "").lower()
            if scope != "all" and scope not in {service, application}:
                continue
            action_rows = actions.get(str(report.incident_id), [])
            evidence = _build_evidence(report, incident, max(action_rows, key=lambda row: row.created_at) if action_rows else None)
            evidence_id = uuid5(NAMESPACE_URL, f"kaims:incident-evidence:default:{evidence.incident_id}")
            await session.merge(IncidentEvidenceRecord(id=evidence_id, tenant_id="default", incident_id=evidence.incident_id, issue_signature=issue_signature(evidence), service=evidence.service, environment=evidence.environment, alert_type=evidence.alert_type, evidence=evidence.model_dump(mode="json"), reviewed=evidence.reviewed, collected_at=max(evidence.timestamps) if evidence.timestamps else started))
            collected += 1
            report_time = _utc(report.created_at)
            if report_time and (
                max_checkpoint is None
                or report_time > max_checkpoint
                or (report_time == max_checkpoint and str(report.id) > str(max_checkpoint_id or ""))
            ):
                max_checkpoint = report_time
                max_checkpoint_id = str(report.id)
        await session.flush()
        stored = (await session.execute(select(IncidentEvidenceRecord).where(IncidentEvidenceRecord.collected_at >= cutoff).order_by(IncidentEvidenceRecord.collected_at.desc()).limit(5000))).scalars().all()
        evidence_rows = []
        for row in stored:
            try:
                evidence = IncidentEvidence.model_validate(row.evidence)
            except Exception:
                continue
            if scope == "all" or evidence.service == scope:
                evidence_rows.append(evidence)
        patterns = FailurePatternAnalyzer().analyze(evidence_rows)
        evidence_by_id = {row.incident_id: row for row in evidence_rows}
        drafts = gated = 0
        for pattern in patterns:
            quality = _quality_gate(pattern, evidence_by_id)
            gated += int(not quality["passed"])
            record_id = uuid5(NAMESPACE_URL, f"kaims:failure-pattern:default:{pattern.issue_signature}")
            payload = pattern.model_dump(mode="json")
            payload["evidence_references"] = payload.get("evidence_references", [])[:100]
            payload.update({"knowledge_status": "challenger" if quality["passed"] else "observed", "requires_human_approval": True, "source": "periodic-knowledge-development", "quality_gate": quality})
            summary = {"issue_signature": pattern.issue_signature, "service": pattern.service, "environment": pattern.environment, "alert_type": pattern.alert_type, "probable_causes": pattern.probable_causes, "successful_resolutions": pattern.successful_resolutions, "quality_gate": quality}
            await session.merge(KnowledgeBaseRecord(id=record_id, tenant_id="default", service=pattern.service, title=f"Recurring failure pattern: {pattern.alert_type}"[:255], content=json.dumps(summary, indent=2), embedding_ref=None, payload=payload))
            await session.merge(FailurePatternRecord(pattern_id=record_id, tenant_id="default", issue_signature=pattern.issue_signature, service=pattern.service, environment=pattern.environment, analysis=payload, confidence=pattern.confidence, analyzed_at=pattern.analyzed_at))
            drafts += int(await _draft_candidate(session, pattern, quality))
        completed = datetime.now(timezone.utc)
        backlog_remaining = len(reports) >= batch_size
        next_delay = 30 if backlog_remaining else int(schedule_config["interval_seconds"])
        result = {"status": "completed", "trigger": trigger, "started_at": started.isoformat(), "completed_at": completed.isoformat(), "duration_seconds": round((completed - started).total_seconds(), 3), "reports_scanned": len(reports), "evidence_collected": collected, "evidence_in_window": len(evidence_rows), "patterns": len(patterns), "quality_gated_patterns": gated, "reviewable_runbook_candidates": drafts, "checkpoint_at": _iso(max_checkpoint), "checkpoint_id": max_checkpoint_id, "backlog_remaining": backlog_remaining, "next_run_at": (completed + timedelta(seconds=next_delay)).isoformat(), "application_scope": schedule_config["application_scope"], "lookback_days": schedule_config["lookback_days"], "batch_size": batch_size, "quality_policy": "kaims.knowledge-quality.v2"}
        await _save_state(session, result)
        await session.commit()
        return result


async def analyze_history(app: FastAPI, trigger: str = "manual") -> dict[str, Any]:
    if not settings.database_enabled:
        return {"status": "disabled", "reason": "database is disabled"}
    if run_lock.locked():
        return {"status": "skipped", "reason": "knowledge development cycle already running"}
    async with run_lock:
        async with app.state.db_engine.connect() as connection:
            acquired = await connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name})
            if int(acquired or 0) != 1:
                return {"status": "skipped", "reason": "another replica owns the knowledge development lease"}
            try:
                return await _analyze_locked(app, trigger)
            finally:
                await connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})


async def periodic_loop(app: FastAPI) -> None:
    global last_result
    while True:
        try:
            state = await _load_state(app)
            next_run = None
            if state.get("next_run_at"):
                try:
                    next_run = _utc(datetime.fromisoformat(str(state["next_run_at"])))
                except ValueError:
                    pass
            now = datetime.now(timezone.utc)
            if schedule_config["enabled"] and (next_run is None or next_run <= now):
                last_result = await analyze_history(app, "schedule")
                continue
            timeout = max(1.0, min(300.0, (next_run - now).total_seconds())) if schedule_config["enabled"] and next_run else 60.0
            schedule_wakeup.clear()
            try:
                await asyncio.wait_for(schedule_wakeup.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_result = {"status": "failed", "error": str(exc)[:1000], "failed_at": datetime.now(timezone.utc).isoformat()}
            await asyncio.sleep(30)


async def startup(app: FastAPI) -> None:
    global task, last_result
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            persisted = await session.get(KnowledgeBaseRecord, configuration_id)
            if persisted and isinstance(persisted.payload, dict):
                schedule_config.update({key: value for key, value in persisted.payload.items() if key in schedule_config})
        last_result = (await _load_state(app)) or last_result
    task = asyncio.create_task(periodic_loop(app), name="periodic-knowledge-development")


async def shutdown(_: FastAPI) -> None:
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = create_app(title="KaiMS Knowledge Development Worker", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/run")
async def run_now() -> dict[str, Any]:
    global last_result
    try:
        last_result = await analyze_history(app, "manual")
    except Exception as exc:
        last_result = {"status": "failed", "error": str(exc)[:1000], "failed_at": datetime.now(timezone.utc).isoformat()}
    finally:
        # A manual cycle can replace a distant periodic deadline with a short
        # backlog catch-up deadline. Wake the scheduler so it reloads the
        # durable state instead of continuing to wait on the old deadline.
        schedule_wakeup.set()
    return last_result


@app.get("/status")
async def status() -> dict[str, Any]:
    summary = (await _load_state(app)) or last_result
    completed = None
    if summary.get("completed_at"):
        try:
            completed = _utc(datetime.fromisoformat(str(summary["completed_at"])))
        except ValueError:
            pass
    stale = bool(schedule_config["enabled"] and completed and (datetime.now(timezone.utc) - completed).total_seconds() > int(schedule_config["interval_seconds"]) * 2)
    return {**summary, "stale": stale, "running": run_lock.locked(), "schedule": schedule_config}


@app.get("/configuration")
async def get_configuration() -> dict[str, Any]:
    return {**schedule_config, "interval_hours": max(1, int(schedule_config["interval_seconds"]) // 3600)}


@app.put("/configuration")
async def update_configuration(configuration: ScheduleConfig) -> dict[str, Any]:
    schedule_config.update(configuration.model_dump(exclude={"interval_hours"}))
    schedule_config["interval_seconds"] = configuration.interval_hours * 3600
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            await session.merge(KnowledgeBaseRecord(id=configuration_id, tenant_id="default", service="KaiMS", title="Periodic knowledge development configuration", content=json.dumps(schedule_config, indent=2), embedding_ref=None, payload=dict(schedule_config)))
            await session.commit()
    schedule_wakeup.set()
    return await get_configuration()


@app.get("/report")
async def report(tenant_id: str = "default") -> dict[str, Any]:
    if not settings.database_enabled:
        return {"status": "disabled", "summary": last_result, "patterns": [], "drafts": []}
    async with app.state.session_factory() as session:
        tenant = str(tenant_id or "default").strip() or "default"
        patterns = (await session.execute(select(FailurePatternRecord).where(FailurePatternRecord.tenant_id == tenant).order_by(FailurePatternRecord.analyzed_at.desc()).limit(50))).scalars().all()
        drafts = (await session.execute(select(RunbookVersionRecord).where(RunbookVersionRecord.tenant_id == tenant).order_by(RunbookVersionRecord.created_at.desc()).limit(50))).scalars().all()
        evidence = (await session.execute(select(IncidentEvidenceRecord).where(IncidentEvidenceRecord.tenant_id == tenant).order_by(IncidentEvidenceRecord.collected_at.desc()).limit(100))).scalars().all()
        outcomes = (await session.execute(select(RunbookOutcomeRecord).where(RunbookOutcomeRecord.tenant_id == tenant).order_by(RunbookOutcomeRecord.created_at.desc()).limit(100))).scalars().all()
        audit_rows = (await session.execute(select(LearningAuditRecord).where(LearningAuditRecord.tenant_id == tenant).order_by(LearningAuditRecord.occurred_at.desc()).limit(100))).scalars().all()
    audits = []
    for row in audit_rows:
        canonical = json.dumps(row.payload or {}, sort_keys=True, separators=(",", ":"), default=str)
        audits.append({"event_id": str(row.event_id), "action": row.action, "actor": row.actor, "resource_type": row.resource_type, "resource_id": row.resource_id, "occurred_at": _iso(row.occurred_at), "payload_sha256": row.payload_sha256, "hash_verified": hashlib.sha256(canonical.encode()).hexdigest() == row.payload_sha256})
    reviewed = sum(bool(row.reviewed) for row in outcomes)
    successful = sum(bool(row.successful) for row in outcomes)
    return {"status": "ok", "summary": (await _load_state(app)) or last_result, "evidence_count": len(evidence), "outcome_summary": {"total": len(outcomes), "reviewed": reviewed, "successful": successful, "failed": len(outcomes) - successful, "success_rate": round(successful / len(outcomes), 4) if outcomes else None}, "patterns": [{"id": str(row.pattern_id), "service": row.service, "environment": row.environment, "issue_signature": row.issue_signature, "confidence": float(row.confidence), "analyzed_at": _iso(row.analyzed_at), "quality_gate": (row.analysis or {}).get("quality_gate", {})} for row in patterns], "drafts": [{"runbook_id": str(row.runbook_id), "version": row.version, "status": row.approval_status, "owner": row.owner, "risk_level": row.risk_level, "created_at": _iso(row.created_at), "content": row.content or {}, "quality_gate": (row.content or {}).get("knowledge_quality", {})} for row in drafts], "outcomes": [{"outcome_id": str(row.outcome_id), "incident_id": row.incident_id, "runbook_id": str(row.runbook_id), "runbook_version": row.runbook_version, "reviewed": row.reviewed, "successful": row.successful, "created_at": _iso(row.created_at)} for row in outcomes[:50]], "learning_audit": audits[:50], "recent_evidence": [{"incident_id": row.incident_id, "service": row.service, "environment": row.environment, "alert_type": row.alert_type, "reviewed": row.reviewed, "collected_at": _iso(row.collected_at)} for row in evidence[:20]]}
