from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from common.config import get_settings
from common.continuous_learning import FailurePatternAnalyzer, IncidentEvidence, issue_signature
from common.database import (
    ActionRecord,
    FailurePatternRecord,
    IncidentEvidenceRecord,
    IncidentRecord,
    KnowledgeBaseRecord,
    LearningAuditRecord,
    RcaReportRecord,
    RunbookVersionRecord,
)
from common.learning_workflows import Mode02Worker
from common.models import EvidenceReference
from common.service import create_app
from fastapi import FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import select

settings = get_settings()
settings.service_name = "knowledge-development-worker"
interval_seconds = max(300, int(os.getenv("KNOWLEDGE_DEVELOPMENT_INTERVAL_SECONDS", "21600")))
task: asyncio.Task | None = None
last_result: dict = {"status": "not_run"}
schedule_config: dict = {
    "enabled": True,
    "interval_seconds": interval_seconds,
    "lookback_days": 30,
    "application_scope": "all",
    "collect_logs": True,
    "collect_metrics": True,
    "collect_traces": True,
    "collect_tickets": True,
    "collect_changes": True,
}
configuration_id = uuid5(NAMESPACE_URL, "kaims:knowledge-development:configuration:default")


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


async def analyze_history(app: FastAPI) -> dict:
    started_at = datetime.now(timezone.utc)
    if not settings.database_enabled:
        return {"status": "disabled", "reason": "database is disabled"}
    async with app.state.session_factory() as session:
        reports = (await session.execute(select(RcaReportRecord).order_by(RcaReportRecord.created_at.desc()).limit(2000))).scalars().all()
        incidents = {str(row.id): row for row in (await session.execute(select(IncidentRecord))).scalars().all()}
        actions_by_incident: dict[str, list[ActionRecord]] = {}
        for row in (await session.execute(select(ActionRecord))).scalars().all():
            actions_by_incident.setdefault(str(row.incident_id), []).append(row)
        evidence_rows: list[IncidentEvidence] = []
        for report in reports:
            incident = incidents.get(str(report.incident_id))
            if incident is None:
                continue
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(schedule_config["lookback_days"]))
            incident_created_at = incident.created_at
            if incident_created_at and incident_created_at.tzinfo is None:
                incident_created_at = incident_created_at.replace(tzinfo=timezone.utc)
            if incident_created_at and incident_created_at < cutoff:
                continue
            configured_scope = str(schedule_config.get("application_scope") or "all").strip().lower()
            if configured_scope != "all" and configured_scope not in {str(incident.service or "").strip().lower(), str((incident.payload or {}).get("application") or "").strip().lower()}:
                continue
            actions = actions_by_incident.get(str(report.incident_id), [])
            latest_action = max(actions, key=lambda item: item.created_at) if actions else None
            report_payload = report.payload if isinstance(report.payload, dict) else {}
            action_payload = latest_action.payload if latest_action and isinstance(latest_action.payload, dict) else {}
            successful = bool(report_payload.get("health_restored") and report_payload.get("alerts_cleared"))
            evidence_rows.append(IncidentEvidence(
                incident_id=str(incident.id), service=incident.service, environment=incident.environment,
                alert_type=str((incident.payload or {}).get("alert_type") or incident.title),
                symptoms=[str((incident.payload or {}).get("summary") or incident.title)],
                timestamps=[value.astimezone(timezone.utc) for value in [incident.created_at] if value],
                logs=[EvidenceReference(evidence_id=f"report-{report.id}", source="incident-history", uri=f"report://{report.id}", summary=report.root_cause)] if schedule_config["collect_logs"] else [],
                related_tickets=[EvidenceReference(evidence_id=f"ticket-{incident.ticket_id}", source="itsm", uri=f"ticket://{incident.ticket_id}", summary=incident.title)] if incident.ticket_id and schedule_config["collect_tickets"] else [],
                resolution=str(report_payload.get("action_taken") or action_payload.get("action_type") or "") or None,
                root_causes=[report.root_cause] if report.root_cause else [],
                resolution_successful=successful, reviewed=successful,
            ))
        analyzer = FailurePatternAnalyzer()
        patterns = analyzer.analyze(evidence_rows)
        drafts = 0
        for evidence in evidence_rows:
            signature = issue_signature(evidence)
            evidence_id = uuid5(NAMESPACE_URL, f"kaims:incident-evidence:default:{evidence.incident_id}")
            await session.merge(IncidentEvidenceRecord(
                id=evidence_id,
                tenant_id="default",
                incident_id=evidence.incident_id,
                issue_signature=signature,
                service=evidence.service,
                environment=evidence.environment,
                alert_type=evidence.alert_type,
                evidence=evidence.model_dump(mode="json"),
                reviewed=evidence.reviewed,
                collected_at=max(evidence.timestamps) if evidence.timestamps else datetime.now(timezone.utc),
            ))
        for pattern in patterns:
            record_id = uuid5(NAMESPACE_URL, f"kaims:failure-pattern:default:{pattern.issue_signature}")
            payload = pattern.model_dump(mode="json")
            payload.update({"knowledge_status": "draft", "requires_human_approval": True, "source": "periodic-knowledge-development"})
            content = json.dumps(payload, indent=2)
            await session.merge(KnowledgeBaseRecord(id=record_id, tenant_id="default", service=pattern.service, title=f"Recurring failure pattern: {pattern.alert_type}", content=content, embedding_ref=None, payload=payload))
            await session.merge(FailurePatternRecord(
                pattern_id=record_id,
                tenant_id="default",
                issue_signature=pattern.issue_signature,
                service=pattern.service,
                environment=pattern.environment,
                analysis=payload,
                confidence=pattern.confidence,
                analyzed_at=pattern.analyzed_at,
            ))
            if analyzer.can_draft(pattern):
                draft = Mode02Worker._draft_runbook(pattern)
                runbook_id = uuid5(NAMESPACE_URL, f"kaims:runbook:default:{pattern.issue_signature}")
                runbook_payload = draft.model_dump(mode="json")
                runbook_payload.update({
                    "name": f"Resolve {pattern.alert_type} for {pattern.service}",
                    "application": pattern.service,
                    "environment": pattern.environment,
                    "matching_conditions": {"issue_signature": pattern.issue_signature},
                    "supporting_evidence": [item.model_dump(mode="json") for item in pattern.evidence_references],
                    "review_state": "awaiting_hitl_review",
                })
                await session.merge(RunbookVersionRecord(
                    runbook_id=runbook_id,
                    version=1,
                    tenant_id="default",
                    issue_signature=pattern.issue_signature,
                    approval_status="draft",
                    owner=draft.owner,
                    risk_level=draft.risk_level,
                    required_approval="mandatory",
                    content=runbook_payload,
                ))
                audit_payload = {"status": "draft", "issue_signature": pattern.issue_signature, "requires_human_approval": True}
                audit_id = uuid5(NAMESPACE_URL, f"kaims:audit:runbook-drafted:{runbook_id}:1")
                canonical = json.dumps(audit_payload, sort_keys=True, separators=(",", ":"))
                audit_exists = await session.scalar(select(LearningAuditRecord.sequence_id).where(LearningAuditRecord.event_id == audit_id).limit(1))
                if audit_exists is None:
                    session.add(LearningAuditRecord(
                        event_id=audit_id,
                        tenant_id="default",
                        actor="knowledge-development-worker",
                        action="runbook.drafted",
                        resource_type="runbook",
                        resource_id=str(runbook_id),
                        payload=audit_payload,
                        payload_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
                        occurred_at=pattern.analyzed_at,
                    ))
                drafts += 1
        await session.commit()
    return {"status": "completed", "started_at": started_at.isoformat(), "completed_at": datetime.now(timezone.utc).isoformat(), "incidents_analyzed": len(evidence_rows), "patterns": len(patterns), "reviewable_runbook_candidates": drafts, "application_scope": schedule_config["application_scope"], "lookback_days": schedule_config["lookback_days"]}


async def periodic_loop(app: FastAPI) -> None:
    global last_result
    while True:
        try:
            if schedule_config["enabled"]:
                last_result = await analyze_history(app)
        except Exception as exc:
            last_result = {"status": "failed", "error": str(exc)[:500]}
        await asyncio.sleep(int(schedule_config["interval_seconds"]))


async def startup(app: FastAPI) -> None:
    global task
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            persisted = await session.get(KnowledgeBaseRecord, configuration_id)
            if persisted and isinstance(persisted.payload, dict):
                schedule_config.update({key: value for key, value in persisted.payload.items() if key in schedule_config})
    task = asyncio.create_task(periodic_loop(app), name="periodic-knowledge-development")


async def shutdown(_: FastAPI) -> None:
    if task: task.cancel()


app = create_app(title="KaiMS Knowledge Development Worker", settings=settings, startup=startup, shutdown=shutdown)


@app.post("/run")
async def run_now() -> dict:
    global last_result
    last_result = await analyze_history(app)
    return last_result


@app.get("/status")
async def status() -> dict:
    return {**last_result, "schedule": schedule_config}


@app.get("/configuration")
async def get_configuration() -> dict:
    return {**schedule_config, "interval_hours": max(1, int(schedule_config["interval_seconds"]) // 3600)}


@app.put("/configuration")
async def update_configuration(configuration: ScheduleConfig) -> dict:
    schedule_config.update(configuration.model_dump(exclude={"interval_hours"}))
    schedule_config["interval_seconds"] = configuration.interval_hours * 3600
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            await session.merge(KnowledgeBaseRecord(id=configuration_id, tenant_id="default", service="KaiMS", title="Periodic knowledge development configuration", content=json.dumps(schedule_config, indent=2), embedding_ref=None, payload=dict(schedule_config)))
            await session.commit()
    return await get_configuration()


@app.get("/report")
async def report() -> dict:
    if not settings.database_enabled:
        return {"status": "disabled", "summary": last_result, "patterns": [], "drafts": []}
    async with app.state.session_factory() as session:
        patterns = (await session.execute(select(FailurePatternRecord).order_by(FailurePatternRecord.analyzed_at.desc()).limit(50))).scalars().all()
        drafts = (await session.execute(select(RunbookVersionRecord).order_by(RunbookVersionRecord.created_at.desc()).limit(50))).scalars().all()
        evidence = (await session.execute(select(IncidentEvidenceRecord).order_by(IncidentEvidenceRecord.collected_at.desc()).limit(100))).scalars().all()
    return {
        "status": "ok",
        "summary": last_result,
        "evidence_count": len(evidence),
        "patterns": [{"id": str(row.pattern_id), "service": row.service, "environment": row.environment, "issue_signature": row.issue_signature, "confidence": float(row.confidence), "analyzed_at": row.analyzed_at.isoformat() if row.analyzed_at else None, "analysis": row.analysis} for row in patterns],
        "drafts": [{"runbook_id": str(row.runbook_id), "version": row.version, "status": row.approval_status, "owner": row.owner, "risk_level": row.risk_level, "created_at": row.created_at.isoformat() if row.created_at else None, "content": row.content} for row in drafts],
        "recent_evidence": [{"incident_id": row.incident_id, "service": row.service, "environment": row.environment, "alert_type": row.alert_type, "reviewed": row.reviewed, "collected_at": row.collected_at.isoformat() if row.collected_at else None} for row in evidence[:20]],
    }
