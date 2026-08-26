from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.database import (
    ActionRecord,
    AgentWorkItemRecord,
    AlertRecord,
    ApprovalRecord,
    AuditLogRecord,
    IncidentEventRecord,
    IncidentRecord,
    IncidentProjectionRecord,
    KnowledgeBaseRecord,
    RcaReportRecord,
    OnboardingStateRecord,
    PendingWorkflowRecord,
)
from common.models import (
    Alert,
    Approval,
    Incident,
    Recommendation,
    RemediationAction,
    ResolutionReport,
)


_PLACEHOLDER_TOKENS = {"", "-", "n/a", "na", "none", "null", "unknown"}
_PENDING_DECISIONS = {"PENDING", "QUEUED", "AWAITING_APPROVAL", "AWAITING USER APPROVAL", "STANDBY"}
_STATUS_PRECEDENCE = {
    "unknown": 0,
    "open": 1,
    "investigating": 2,
    "awaiting_approval": 3,
    "remediating": 4,
    "validating": 5,
    "failed": 6,
    "closed": 7,
}

_EVENT_TABLE_HINTS: dict[str, list[str]] = {
    "incident.alert.enriched": ["alerts", "incidents", "agent_work_items"],
    "incident.workflow.selected": ["incident_events", "incident_projections", "agent_work_items"],
    "incident.context.collected": ["incident_events", "incident_projections", "agent_work_items"],
    "incident.recommendation.generated": ["incident_events", "audit_logs", "incident_projections", "agent_work_items"],
    "incident.approval.requested": ["incident_events", "approvals", "incident_projections", "agent_work_items"],
    "incident.approval.recorded": ["incident_events", "approvals", "incident_projections", "agent_work_items"],
    "incident.remediation.executed": ["incident_events", "actions", "incident_projections", "agent_work_items"],
    "incident.closure.completed": ["incident_events", "rca_reports", "incident_projections", "agent_work_items"],
}



def _is_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in _PLACEHOLDER_TOKENS
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _event_quality_score(event: dict[str, Any]) -> int:
    score = 0
    decision = str(event.get("decision") or "").strip()
    decision_token = decision.upper()
    if _is_meaningful_value(decision):
        score += 2
    if decision_token and decision_token not in _PENDING_DECISIONS:
        score += 8
    if _is_meaningful_value(event.get("output")):
        score += 3
    if _is_meaningful_value(event.get("action")):
        score += 2
    if isinstance(event.get("input"), dict) and event.get("input"):
        score += 1
    if isinstance(event.get("metrics"), dict) and event.get("metrics"):
        score += 1
    return score


def _merge_events(group: list[dict[str, Any]]) -> dict[str, Any]:
    if len(group) == 1:
        return dict(group[0])

    merged = dict(max(group, key=_event_quality_score))

    for item in group:
        for field in ("action", "decision", "output", "communicates_to"):
            if not _is_meaningful_value(merged.get(field)) and _is_meaningful_value(item.get(field)):
                merged[field] = item.get(field)

        for object_field in ("input", "metrics"):
            existing = merged.get(object_field)
            incoming = item.get(object_field)
            if isinstance(existing, dict) and isinstance(incoming, dict):
                for key, value in incoming.items():
                    if key not in existing and _is_meaningful_value(value):
                        existing[key] = value
            elif (not isinstance(existing, dict) or not existing) and isinstance(incoming, dict) and incoming:
                merged[object_field] = dict(incoming)

    llm_calls: list[Any] = []
    llm_errors: list[Any] = []
    for item in group:
        if isinstance(item.get("llm_calls"), list):
            llm_calls.extend(item.get("llm_calls") or [])
        if isinstance(item.get("llm_errors"), list):
            llm_errors.extend(item.get("llm_errors") or [])
    if llm_calls:
        merged["llm_calls"] = llm_calls
    if llm_errors:
        merged["llm_errors"] = llm_errors

    return merged


def _deduplicate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    first_index: dict[tuple[int, str], int] = {}

    for index, event in enumerate(events):
        sequence = int(event.get("sequence", 0) or 0)
        agent = str(event.get("agent") or "").strip()
        key = (sequence, agent)
        grouped.setdefault(key, []).append(event)
        first_index.setdefault(key, index)

    ordered_keys = sorted(grouped.keys(), key=lambda key: (key[0], first_index.get(key, 0)))
    return [_merge_events(grouped[key]) for key in ordered_keys]


def _status_rank(status: str | None) -> int:
    token = str(status or "").strip().lower()
    return _STATUS_PRECEDENCE.get(token, 0)


def _utc_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _extract_recommendation_uuid(payload: dict[str, Any] | None) -> UUID | None:
    if not isinstance(payload, dict):
        return None
    recommendation = payload.get("recommendation") if isinstance(payload.get("recommendation"), dict) else {}
    approval = payload.get("approval") if isinstance(payload.get("approval"), dict) else {}
    source_payload = payload.get("source_payload") if isinstance(payload.get("source_payload"), dict) else {}
    source_recommendation = source_payload.get("recommendation") if isinstance(source_payload.get("recommendation"), dict) else {}
    source_approval = source_payload.get("approval") if isinstance(source_payload.get("approval"), dict) else {}

    candidates = [
        payload.get("recommendation_id"),
        payload.get("recommended_action_id"),
        recommendation.get("id"),
        approval.get("recommendation_id"),
        source_payload.get("recommendation_id"),
        source_recommendation.get("id"),
        source_approval.get("recommendation_id"),
    ]
    for candidate in candidates:
        token = str(candidate or "").strip()
        if not token:
            continue
        try:
            return UUID(token)
        except ValueError:
            continue
    return None


def _extract_flow_id(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    event_contract = payload.get("event_contract") if isinstance(payload.get("event_contract"), dict) else {}
    source_payload = payload.get("source_payload") if isinstance(payload.get("source_payload"), dict) else {}
    source_decision = source_payload.get("decision") if isinstance(source_payload.get("decision"), dict) else {}
    source_contract = source_payload.get("event_contract") if isinstance(source_payload.get("event_contract"), dict) else {}

    candidates = [
        payload.get("flow_id"),
        decision.get("flow_id"),
        event_contract.get("flow_id"),
        source_payload.get("flow_id"),
        source_decision.get("flow_id"),
        source_contract.get("flow_id"),
    ]
    for candidate in candidates:
        token = str(candidate or "").strip()
        if token:
            return token
    return None


def _extract_source_channel(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    source_event_contract = (
        payload.get("source_event_contract") if isinstance(payload.get("source_event_contract"), dict) else {}
    )
    source_payload = payload.get("source_payload") if isinstance(payload.get("source_payload"), dict) else {}
    source_payload_contract = (
        source_payload.get("event_contract") if isinstance(source_payload.get("event_contract"), dict) else {}
    )
    candidates = [
        source_event_contract.get("transport", {}).get("channel")
        if isinstance(source_event_contract.get("transport"), dict)
        else None,
        source_payload.get("transport", {}).get("channel")
        if isinstance(source_payload.get("transport"), dict)
        else None,
        source_payload_contract.get("transport", {}).get("channel")
        if isinstance(source_payload_contract.get("transport"), dict)
        else None,
    ]
    for candidate in candidates:
        token = str(candidate or "").strip()
        if token:
            return token
    return None


def _extract_query_hint(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None

    candidate_keys = (
        "sql",
        "query",
        "statement",
        "db_query",
        "query_text",
        "lookup_query",
    )

    queue: list[Any] = [payload]
    seen: set[int] = set()
    while queue:
        item = queue.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, dict):
            for key in candidate_keys:
                value = item.get(key)
                token = str(value or "").strip()
                if token:
                    return token
            for value in item.values():
                if isinstance(value, (dict, list, tuple)):
                    queue.append(value)
        elif isinstance(item, (list, tuple)):
            queue.extend(item)
    return None


def _infer_table_hints(event_type: str, payload: dict[str, Any] | None) -> list[str]:
    hints = list(_EVENT_TABLE_HINTS.get(str(event_type or "").strip().lower(), []))
    if not isinstance(payload, dict):
        return hints

    query_hint = _extract_query_hint(payload)
    if query_hint:
        upper_query = query_hint.upper()
        for table in ("INCIDENT_EVENTS", "INCIDENT_PROJECTIONS", "AGENT_WORK_ITEMS", "AUDIT_LOGS", "APPROVALS", "ACTIONS", "RCA_REPORTS"):
            if table in upper_query and table.lower() not in hints:
                hints.append(table.lower())
    return hints


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _require(name: str, value: Any) -> Any:
        if value is None:
            raise ValueError(f"{name} is required")
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"{name} is required")
        return value

    async def save_alert(self, alert: Alert) -> None:
        await self.session.merge(
            AlertRecord(
                id=self._require("alert.id", alert.id),
                source=self._require("alert.source", alert.source),
                name=self._require("alert.name", alert.name),
                service=self._require("alert.service", alert.service),
                environment=self._require("alert.environment", alert.environment),
                severity=self._require("alert.severity", alert.severity.value),
                fingerprint=alert.fingerprint,
                correlation_id=alert.correlation_id,
                payload=alert.model_dump(mode="json"),
            )
        )

    async def list_alerts(self, limit: int = 500) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 5000))
        result = await self.session.execute(
            select(AlertRecord)
            .order_by(AlertRecord.created_at.desc(), AlertRecord.updated_at.desc())
            .limit(safe_limit)
        )
        rows = result.scalars().all()
        if not rows:
            return []

        alert_id_set = {str(row.id) for row in rows}
        alert_to_incident: dict[str, str] = {}

        # Incident payload carries linked alert IDs. Build a reverse map to incident IDs,
        # preferring most recent incidents by updated timestamp.
        incident_result = await self.session.execute(
            select(IncidentRecord)
            .order_by(IncidentRecord.updated_at.desc(), IncidentRecord.created_at.desc())
            .limit(max(500, safe_limit * 10))
        )
        for incident in incident_result.scalars().all():
            payload = incident.payload if isinstance(incident.payload, dict) else {}
            linked_alert_ids = payload.get("alert_ids", []) if isinstance(payload.get("alert_ids"), list) else []
            for item in linked_alert_ids:
                alert_id = str(item)
                if alert_id in alert_id_set and alert_id not in alert_to_incident:
                    alert_to_incident[alert_id] = str(incident.id)

        projection_status_by_incident: dict[str, str] = {}
        projection_incident_ids = {
            self._parse_uuid(incident_id)
            for incident_id in alert_to_incident.values()
            if self._parse_uuid(incident_id) is not None
        }
        if projection_incident_ids:
            projection_result = await self.session.execute(
                select(IncidentProjectionRecord).where(IncidentProjectionRecord.incident_id.in_(projection_incident_ids))
            )
            for projection in projection_result.scalars().all():
                projection_status_by_incident[str(projection.incident_id)] = str(projection.status or "").strip()

        enriched_rows: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(row.payload) if isinstance(row.payload, dict) else {}
            alert_id = str(row.id)
            incident_id = str(payload.get("incident_id") or "").strip() or alert_to_incident.get(alert_id)
            if incident_id:
                payload["incident_id"] = incident_id
                projection_status = projection_status_by_incident.get(incident_id)
                if projection_status:
                    payload["status"] = projection_status
                    payload["state"] = projection_status
            enriched_rows.append(payload)

        return enriched_rows

    async def get_processed_result_by_alert_id(self, alert_id: str) -> dict[str, Any] | None:
        normalized_alert_id = str(alert_id or "").strip()
        if not normalized_alert_id:
            return None

        try:
            alert_uuid = UUID(normalized_alert_id)
        except ValueError:
            return None

        alert_result = await self.session.execute(select(AlertRecord).where(AlertRecord.id == alert_uuid))
        alert_record = alert_result.scalar_one_or_none()
        if alert_record is None:
            return None

        alert_payload = alert_record.payload if isinstance(alert_record.payload, dict) else {}

        incident_rows = await self.session.execute(
            select(IncidentRecord).order_by(IncidentRecord.updated_at.desc(), IncidentRecord.created_at.desc()).limit(300)
        )
        incident_record = None
        for record in incident_rows.scalars().all():
            payload = record.payload if isinstance(record.payload, dict) else {}
            linked_alert_ids = payload.get("alert_ids", []) if isinstance(payload.get("alert_ids"), list) else []
            linked_as_strings = {str(item) for item in linked_alert_ids}
            if normalized_alert_id in linked_as_strings:
                incident_record = record
                break

        if incident_record is None:
            # Fallback: match by service and severity for latest likely incident.
            service = str(alert_payload.get("service") or "").strip()
            severity = str(alert_payload.get("severity") or "").strip()
            if service:
                fallback_stmt = select(IncidentRecord).where(IncidentRecord.service == service)
                if severity:
                    fallback_stmt = fallback_stmt.where(IncidentRecord.severity == severity)
                fallback_result = await self.session.execute(
                    fallback_stmt.order_by(IncidentRecord.updated_at.desc(), IncidentRecord.created_at.desc()).limit(1)
                )
                incident_record = fallback_result.scalar_one_or_none()

        if incident_record is None:
            return None

        incident_payload = incident_record.payload if isinstance(incident_record.payload, dict) else {}
        incident_id_str = str(incident_record.id)

        recommendation = {}
        audit_stmt = (
            select(AuditLogRecord)
            .where(AuditLogRecord.resource_type == "incident")
            .where(AuditLogRecord.resource_id == incident_id_str)
            .where(AuditLogRecord.action == "recommendation.generated")
            .order_by(AuditLogRecord.updated_at.desc(), AuditLogRecord.created_at.desc())
            .limit(1)
        )
        audit_result = await self.session.execute(audit_stmt)
        audit_record = audit_result.scalar_one_or_none()
        if audit_record is not None and isinstance(audit_record.payload, dict):
            recommendation = audit_record.payload

        approval = {}
        approval_result = await self.session.execute(
            select(ApprovalRecord)
            .where(ApprovalRecord.incident_id == UUID(incident_id_str))
            .order_by(ApprovalRecord.updated_at.desc(), ApprovalRecord.created_at.desc())
            .limit(1)
        )
        approval_record = approval_result.scalar_one_or_none()
        if approval_record is not None and isinstance(approval_record.payload, dict):
            approval = approval_record.payload

        remediation_action = {}
        action_result = await self.session.execute(
            select(ActionRecord)
            .where(ActionRecord.incident_id == UUID(incident_id_str))
            .order_by(ActionRecord.updated_at.desc(), ActionRecord.created_at.desc())
            .limit(1)
        )
        action_record = action_result.scalar_one_or_none()
        if action_record is not None and isinstance(action_record.payload, dict):
            remediation_action = action_record.payload

        closure_report = {}
        report_result = await self.session.execute(
            select(RcaReportRecord)
            .where(RcaReportRecord.incident_id == UUID(incident_id_str))
            .order_by(RcaReportRecord.updated_at.desc(), RcaReportRecord.created_at.desc())
            .limit(1)
        )
        report_record = report_result.scalar_one_or_none()
        if report_record is not None and isinstance(report_record.payload, dict):
            closure_report = report_record.payload

        work_rows_result = await self.session.execute(
            select(AgentWorkItemRecord)
            .where(AgentWorkItemRecord.incident_id == UUID(incident_id_str))
            .order_by(AgentWorkItemRecord.sequence.asc(), AgentWorkItemRecord.updated_at.asc())
        )
        work_rows = work_rows_result.scalars().all()
        events = [
            {
                "sequence": row.sequence,
                "agent": row.agent_name,
                "status": row.status,
                "timestamp": row.updated_at,
                "action": (row.details or {}).get("action") or row.work_item,
                "input": (row.details or {}).get("input", {}),
                "decision": (row.details or {}).get("decision"),
                "metrics": (row.details or {}).get("metrics", {}),
                "output": (row.details or {}).get("output") or row.status,
                "communicates_to": (row.details or {}).get("communicates_to", ""),
                "llm_calls": (row.details or {}).get("llm_calls", []),
                "llm_errors": (row.details or {}).get("llm_errors", []),
            }
            for row in work_rows
        ]
        events = _deduplicate_events(events)

        incident_event_result = await self.session.execute(
            select(IncidentEventRecord)
            .where(IncidentEventRecord.incident_id == UUID(incident_id_str))
            .order_by(IncidentEventRecord.created_at.asc())
        )
        incident_event_rows = incident_event_result.scalars().all()
        event_trace: list[dict[str, Any]] = []
        for row in incident_event_rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            source_channel = _extract_source_channel(payload)
            query_hint = _extract_query_hint(payload)
            event_trace.append(
                {
                    "timestamp": row.created_at,
                    "service": row.service,
                    "event_type": row.event_type,
                    "event_stage": row.event_stage,
                    "status": row.status,
                    "source_channel": source_channel,
                    "transport_channel": row.transport_channel,
                    "transport_provider": row.transport_provider,
                    "risk_tier": row.risk_tier,
                    "execution_mode": row.execution_mode,
                    "policy_reason": row.policy_reason,
                    "trace_id": row.trace_id,
                    "table_hints": _infer_table_hints(row.event_type, payload),
                    "query_hint": query_hint,
                }
            )

        if not events and event_trace:
            events = [
                {
                    "sequence": index + 1,
                    "agent": str(item.get("service") or "-") or "-",
                    "status": str(item.get("status") or item.get("event_stage") or "-") or "-",
                    "timestamp": item.get("timestamp"),
                    "action": str(item.get("event_type") or "incident.event"),
                    "input": {
                        "source_channel": item.get("source_channel"),
                        "transport_channel": item.get("transport_channel"),
                        "transport_provider": item.get("transport_provider"),
                    },
                    "decision": str(item.get("policy_reason") or item.get("status") or item.get("event_stage") or "").strip() or None,
                    "metrics": {
                        "risk_tier": item.get("risk_tier"),
                        "execution_mode": item.get("execution_mode"),
                    },
                    "output": str(item.get("event_type") or "incident.event"),
                    "communicates_to": str(item.get("transport_channel") or "").strip(),
                    "llm_calls": [],
                    "llm_errors": [],
                }
                for index, item in enumerate(event_trace)
            ]

        recommendation_metadata = recommendation.get("metadata", {}) if isinstance(recommendation.get("metadata"), dict) else {}
        orchestration_decision = (
            recommendation_metadata.get("orchestration_decision", {})
            if isinstance(recommendation_metadata.get("orchestration_decision"), dict)
            else {}
        )
        model_usage = recommendation_metadata.get("model_usage", []) if isinstance(recommendation_metadata.get("model_usage"), list) else []
        finops_totals = {
            "input_tokens": sum(int(item.get("input_tokens", 0) or 0) for item in model_usage if isinstance(item, dict)),
            "output_tokens": sum(int(item.get("output_tokens", 0) or 0) for item in model_usage if isinstance(item, dict)),
            "total_tokens": sum(int(item.get("total_tokens", 0) or 0) for item in model_usage if isinstance(item, dict)),
            "total_cost_usd": round(sum(float(item.get("total_cost_usd", 0.0) or 0.0) for item in model_usage if isinstance(item, dict)), 8),
            "calls": len([item for item in model_usage if isinstance(item, dict)]),
            "failed_calls": 0,
        }
        by_provider: dict[str, dict[str, Any]] = {}
        for item in model_usage:
            if not isinstance(item, dict):
                continue
            provider = str(item.get("provider") or "unknown")
            row = by_provider.setdefault(
                provider,
                {"provider": provider, "calls": 0, "total_tokens": 0, "total_cost_usd": 0.0},
            )
            row["calls"] += 1
            row["total_tokens"] += int(item.get("total_tokens", 0) or 0)
            row["total_cost_usd"] = round(float(row["total_cost_usd"]) + float(item.get("total_cost_usd", 0.0) or 0.0), 8)

        metrics = {
            "severity": str(incident_payload.get("severity") or alert_payload.get("severity") or "unknown").upper(),
            "remediation_status": str(remediation_action.get("status") or "unknown"),
            "health_restored": bool(closure_report.get("health_restored", False)),
            "alerts_cleared": bool(closure_report.get("alerts_cleared", False)),
            "recommendation_confidence": float(recommendation.get("confidence", 0.0) or 0.0),
            "agent_handoffs": len(events),
        }

        scenario = {
            "id": "db-processed",
            "title": str(incident_payload.get("title") or alert_payload.get("name") or "Incident"),
            "recommended_action": str(recommendation.get("recommended_action") or ""),
        }

        return {
            "mode": "db-processed",
            "scenario": scenario,
            "alert": alert_payload,
            "incident": incident_payload,
            "decision": {
                "workflow": str(orchestration_decision.get("workflow") or "db-processed"),
                "requires_approval": bool(orchestration_decision.get("requires_approval", False)),
                "risk_tier": str(orchestration_decision.get("risk_tier") or "unknown"),
                "execution_mode": str(orchestration_decision.get("execution_mode") or "unknown"),
                "policy_version": str(orchestration_decision.get("policy_version") or "policy-v1"),
                "policy_reason": str(orchestration_decision.get("policy_reason") or ""),
                "message_bus_provider": str(orchestration_decision.get("message_bus_provider") or "unknown"),
                "stream_count": int(orchestration_decision.get("stream_count", 0) or 0),
                "stream_threshold": int(orchestration_decision.get("stream_threshold", 0) or 0),
                "planner_used": False,
                "planner_model": None,
                "planner_reason": "db-processed historical result",
            },
            "recommendation": recommendation,
            "approval": approval,
            "remediation_action": remediation_action,
            "closure_report": closure_report,
            "metrics": metrics,
            "finops": {
                "totals": finops_totals,
                "by_provider": list(by_provider.values()),
                "calls": model_usage,
                "errors": [],
                "currency": "USD",
            },
            "events": events,
            "event_trace": event_trace,
            "trace_summary": {
                "services_called": sorted({str(item.get("service") or "").strip() for item in event_trace if str(item.get("service") or "").strip()}),
                "channels": sorted(
                    {
                        str(channel).strip()
                        for item in event_trace
                        for channel in (item.get("source_channel"), item.get("transport_channel"))
                        if str(channel or "").strip()
                    }
                ),
                "tables_touched": sorted(
                    {
                        str(table).strip()
                        for item in event_trace
                        for table in (item.get("table_hints") or [])
                        if str(table or "").strip()
                    }
                ),
                "event_count": len(event_trace),
            },
            "next_step": "Loaded processed incident summary from database.",
        }

    async def get_incident_stage_completeness(self, incident_id: str) -> dict[str, Any] | None:
        incident_uuid = self._parse_uuid(incident_id)
        if incident_uuid is None:
            return None

        incident_result = await self.session.execute(
            select(IncidentRecord).where(IncidentRecord.id == incident_uuid)
        )
        incident_record = incident_result.scalar_one_or_none()
        if incident_record is None:
            return None

        events_result = await self.session.execute(
            select(IncidentEventRecord)
            .where(IncidentEventRecord.incident_id == incident_uuid)
            .order_by(IncidentEventRecord.created_at.asc())
        )
        event_rows = events_result.scalars().all()
        event_types = {
            str(row.event_type or "").strip().lower()
            for row in event_rows
            if str(row.event_type or "").strip()
        }
        event_statuses = {
            str(row.status or "").strip().lower()
            for row in event_rows
            if str(row.status or "").strip()
        }

        work_result = await self.session.execute(
            select(AgentWorkItemRecord).where(AgentWorkItemRecord.incident_id == incident_uuid)
        )
        work_rows = work_result.scalars().all()

        approval_result = await self.session.execute(
            select(ApprovalRecord).where(ApprovalRecord.incident_id == incident_uuid)
        )
        approval_rows = approval_result.scalars().all()

        action_result = await self.session.execute(
            select(ActionRecord).where(ActionRecord.incident_id == incident_uuid)
        )
        action_rows = action_result.scalars().all()

        report_result = await self.session.execute(
            select(RcaReportRecord).where(RcaReportRecord.incident_id == incident_uuid)
        )
        report_rows = report_result.scalars().all()
        incident_status = str(incident_record.status or "").strip().lower()

        stage_matrix = [
            {
                "stage": "alert_enriched",
                "label": "Alert Intelligence Agent",
                "event_types": ["incident.alert.enriched"],
            },
            {
                "stage": "workflow_selected",
                "label": "Orchestrator Agent",
                "event_types": ["incident.workflow.selected"],
            },
            {
                "stage": "context_collected",
                "label": "Context Intelligence Agent",
                "event_types": ["incident.context.collected"],
            },
            {
                "stage": "recommendation_generated",
                "label": "Resolution Intelligence Agent",
                "event_types": ["incident.recommendation.generated"],
            },
            {
                "stage": "approval_recorded",
                "label": "Human Approval Layer",
                "event_types": ["incident.approval.recorded", "incident.approval.requested"],
            },
            {
                "stage": "remediation_executed",
                "label": "Remediation Automation Engine",
                "event_types": ["incident.remediation.executed"],
            },
            {
                "stage": "closure_completed",
                "label": "Closure & Validation",
                "event_types": ["incident.closure.completed", "incident.closed"],
            },
        ]

        stages = []
        for row in stage_matrix:
            matched = [event_type for event_type in row["event_types"] if event_type in event_types]
            persisted = bool(matched)

            # Use persisted relational evidence to avoid under-reporting when some
            # services emit equivalent terminal states under different event names.
            if row["stage"] == "alert_enriched" and not persisted:
                persisted = len(work_rows) > 0 or len(event_rows) > 0
            elif row["stage"] == "context_collected" and not persisted:
                persisted = any(
                    str(work.agent_name or "").strip().lower() in {"context intelligence agent", "context-agent"}
                    for work in work_rows
                )
            elif row["stage"] == "approval_recorded" and not persisted:
                persisted = len(approval_rows) > 0
            elif row["stage"] == "remediation_executed" and not persisted:
                persisted = len(action_rows) > 0 or "remediating" in event_statuses
            elif row["stage"] == "closure_completed" and not persisted:
                persisted = len(report_rows) > 0 or incident_status in {"closed", "resolved"}

            stages.append(
                {
                    "stage": row["stage"],
                    "label": row["label"],
                    "persisted": persisted,
                    "matched_event_types": matched,
                }
            )

        completed = len([row for row in stages if row["persisted"]])
        total = len(stages)
        missing = [row["stage"] for row in stages if not row["persisted"]]
        latest_event_at = event_rows[-1].created_at if event_rows else None

        return {
            "incident_id": str(incident_record.id),
            "status": str(incident_record.status or "unknown"),
            "service": str(incident_record.service or "unknown"),
            "counts": {
                "incident_events": len(event_rows),
                "agent_work_items": len(work_rows),
                "approvals": len(approval_rows),
                "actions": len(action_rows),
                "rca_reports": len(report_rows),
            },
            "event_types": sorted(event_types),
            "stages": stages,
            "stage_completion": {
                "completed": completed,
                "total": total,
                "percentage": round((completed / total) * 100, 2) if total else 0.0,
                "missing": missing,
            },
            "latest_event_at": latest_event_at,
        }

    async def save_incident(self, incident: Incident) -> None:
        await self.session.merge(
            IncidentRecord(
                id=self._require("incident.id", incident.id),
                service=self._require("incident.service", incident.service),
                environment=self._require("incident.environment", incident.environment),
                severity=self._require("incident.severity", incident.severity.value),
                status=self._require("incident.status", incident.status.value),
                title=self._require("incident.title", incident.title),
                ticket_id=incident.ticket_id,
                payload=incident.model_dump(mode="json"),
            )
        )

    async def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        incident_uuid = self._parse_uuid(incident_id)
        if incident_uuid is None:
            return None
        result = await self.session.execute(select(IncidentRecord).where(IncidentRecord.id == incident_uuid))
        record = result.scalar_one_or_none()
        return record.payload if record else None

    async def save_approval(self, approval: Approval) -> None:
        await self.session.merge(
            ApprovalRecord(
                id=self._require("approval.id", approval.id),
                incident_id=self._require("approval.incident_id", approval.incident_id),
                recommendation_id=self._require("approval.recommendation_id", approval.recommendation_id),
                decision=self._require("approval.decision", approval.decision.value),
                approver=approval.approver,
                payload=approval.model_dump(mode="json"),
            )
        )

    async def save_action(self, action: RemediationAction) -> None:
        await self.session.merge(
            ActionRecord(
                id=self._require("action.id", action.id),
                incident_id=self._require("action.incident_id", action.incident_id),
                action_type=self._require("action.action_type", action.action_type),
                target=self._require("action.target", action.target),
                status=self._require("action.status", action.status.value),
                payload=action.model_dump(mode="json"),
            )
        )

    async def save_action_audit(self, action: RemediationAction, actor: str = "remediation-engine") -> None:
        payload = action.model_dump(mode="json")
        policy_version = str(action.parameters.get("policy_version", "")).strip()
        policy_reason = str(action.parameters.get("policy_reason", "")).strip()
        if policy_version:
            payload["policy_version"] = policy_version
        if policy_reason:
            payload["policy_reason"] = policy_reason

        await self.session.merge(
            AuditLogRecord(
                id=uuid4(),
                actor=self._require("audit.actor", actor),
                action=self._require("audit.action", "remediation.executed"),
                resource_type="incident",
                resource_id=self._require("audit.resource_id", str(action.incident_id)),
                payload=payload,
            )
        )

    async def save_report(self, report: ResolutionReport) -> None:
        await self.session.merge(
            RcaReportRecord(
                id=self._require("report.id", report.id),
                incident_id=self._require("report.incident_id", report.incident_id),
                root_cause=self._require("report.root_cause", report.root_cause),
                impact=self._require("report.impact", report.impact),
                payload=report.model_dump(mode="json"),
            )
        )

    async def save_recommendation_as_audit(self, recommendation: Recommendation) -> None:
        await self.session.merge(
            AuditLogRecord(
                id=self._require("recommendation.id", recommendation.id),
                actor=self._require("audit.actor", "resolution-agent"),
                action=self._require("audit.action", "recommendation.generated"),
                resource_type="incident",
                resource_id=self._require("audit.resource_id", str(recommendation.incident_id)),
                payload=recommendation.model_dump(mode="json"),
            )
        )

    async def save_knowledge_base(self, report: ResolutionReport, service: str = "unknown") -> None:
        await self.session.merge(
            KnowledgeBaseRecord(
                id=self._require("knowledge_base.id", report.id),
                service=self._require("knowledge_base.service", service),
                title=self._require("knowledge_base.title", f"RCA for incident {report.incident_id}"),
                content=self._require("knowledge_base.content", report.knowledge_base_entry),
                embedding_ref=self._require("knowledge_base.embedding_ref", str(report.id)),
                payload=report.model_dump(mode="json"),
            )
        )

    async def save_onboarding_state(
        self,
        *,
        project_name: str,
        provider_name: str,
        project_payload: dict[str, Any],
        connectivity_payload: dict[str, Any],
        owner_team: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
        test_status: str | None = None,
        test_message: str | None = None,
        last_tested_at: datetime | None = None,
    ) -> None:
        await self.session.merge(
            OnboardingStateRecord(
                project_name=self._require("onboarding.project_name", project_name),
                provider_name=self._require("onboarding.provider_name", provider_name),
                owner_team=owner_team,
                environment=environment,
                region=region,
                endpoint_url=endpoint_url,
                test_status=test_status,
                test_message=test_message,
                project_payload=self._require("onboarding.project_payload", project_payload),
                connectivity_payload=self._require("onboarding.connectivity_payload", connectivity_payload),
                last_tested_at=last_tested_at,
            )
        )

    async def list_onboarding_state(self) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(OnboardingStateRecord).order_by(OnboardingStateRecord.project_name, OnboardingStateRecord.provider_name)
        )
        rows = result.scalars().all()
        return [
            {
                "project_name": row.project_name,
                "provider_name": row.provider_name,
                "owner_team": row.owner_team,
                "environment": row.environment,
                "region": row.region,
                "endpoint_url": row.endpoint_url,
                "test_status": row.test_status,
                "test_message": row.test_message,
                "project_payload": row.project_payload,
                "connectivity_payload": row.connectivity_payload,
                "updated_at": row.updated_at,
                "last_tested_at": row.last_tested_at,
            }
            for row in rows
        ]

    async def get_onboarding_state_row(self, project_name: str, provider_name: str) -> dict[str, Any] | None:
        normalized_project = str(project_name or "").strip()
        normalized_provider = str(provider_name or "").strip().lower()
        if not normalized_project or not normalized_provider:
            return None
        result = await self.session.execute(
            select(OnboardingStateRecord).where(
                func.lower(func.trim(OnboardingStateRecord.project_name)) == normalized_project.lower(),
                func.lower(func.trim(OnboardingStateRecord.provider_name)) == normalized_provider,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "project_name": row.project_name,
            "provider_name": row.provider_name,
            "owner_team": row.owner_team,
            "environment": row.environment,
            "region": row.region,
            "endpoint_url": row.endpoint_url,
            "test_status": row.test_status,
            "test_message": row.test_message,
            "project_payload": row.project_payload,
            "connectivity_payload": row.connectivity_payload,
            "updated_at": row.updated_at,
            "last_tested_at": row.last_tested_at,
        }

    async def delete_onboarding_state(self, project_name: str, provider_name: str | None = None) -> int:
        normalized_project = str(project_name or "").strip()
        if not normalized_project:
            return 0
        statement = delete(OnboardingStateRecord).where(
            func.lower(func.trim(OnboardingStateRecord.project_name)) == normalized_project.lower()
        )
        normalized_provider = str(provider_name or "").strip().lower()
        if normalized_provider:
            statement = statement.where(func.lower(func.trim(OnboardingStateRecord.provider_name)) == normalized_provider)
        result = await self.session.execute(statement)
        return int(result.rowcount or 0)

    async def save_agent_work_item(
        self,
        *,
        incident_id: Any,
        agent_name: str,
        work_item: str,
        status: str,
        sequence: int | None = None,
        trace_id: str | None = None,
        ticket_id: str | None = None,
        details: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        self.session.add(
            AgentWorkItemRecord(
                incident_id=self._require("agent_work.incident_id", incident_id),
                agent_name=self._require("agent_work.agent_name", agent_name),
                trace_id=trace_id,
                ticket_id=ticket_id,
                work_item=self._require("agent_work.work_item", work_item),
                status=self._require("agent_work.status", status),
                sequence=sequence,
                details=details or {},
                started_at=started_at,
                completed_at=completed_at,
            )
        )

    async def save_pending_workflow(
        self,
        *,
        incident_id: Any,
        recommendation_id: Any,
        flow_id: str,
        trace_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        incident_uuid = self._parse_uuid(incident_id)
        if incident_uuid is None:
            raise ValueError("pending_workflow.incident_id is required")
        recommendation_uuid = self._parse_uuid(recommendation_id)
        if recommendation_uuid is None:
            raise ValueError("pending_workflow.recommendation_id is required")

        result = await self.session.execute(
            select(PendingWorkflowRecord).where(PendingWorkflowRecord.incident_id == incident_uuid)
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = PendingWorkflowRecord(
                incident_id=incident_uuid,
                recommendation_id=recommendation_uuid,
                flow_id=self._require("pending_workflow.flow_id", flow_id),
                trace_id=trace_id,
                status="pending",
                payload=payload,
                completed_payload=None,
                completed_at=None,
            )
            self.session.add(record)
            return

        record.recommendation_id = recommendation_uuid
        record.flow_id = self._require("pending_workflow.flow_id", flow_id)
        record.trace_id = trace_id
        record.status = "pending"
        record.payload = payload
        record.completed_payload = None
        record.completed_at = None
        await self.session.merge(record)

    async def get_pending_workflow(self, incident_id: Any) -> dict[str, Any] | None:
        incident_uuid = self._parse_uuid(incident_id)
        if incident_uuid is None:
            return None
        result = await self.session.execute(
            select(PendingWorkflowRecord).where(PendingWorkflowRecord.incident_id == incident_uuid)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return {
            "incident_id": str(record.incident_id),
            "recommendation_id": str(record.recommendation_id),
            "flow_id": record.flow_id,
            "trace_id": record.trace_id,
            "status": record.status,
            "payload": record.payload if isinstance(record.payload, dict) else {},
            "completed_payload": record.completed_payload if isinstance(record.completed_payload, dict) else None,
            "completed_at": record.completed_at,
        }

    async def mark_pending_workflow_completed(self, incident_id: Any, completed_payload: dict[str, Any]) -> None:
        incident_uuid = self._parse_uuid(incident_id)
        if incident_uuid is None:
            return
        result = await self.session.execute(
            select(PendingWorkflowRecord).where(PendingWorkflowRecord.incident_id == incident_uuid)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return
        record.status = "completed"
        record.completed_payload = completed_payload
        record.completed_at = datetime.utcnow()
        await self.session.merge(record)

    async def clear_pending_workflow(self, incident_id: Any) -> None:
        incident_uuid = self._parse_uuid(incident_id)
        if incident_uuid is None:
            return
        result = await self.session.execute(
            select(PendingWorkflowRecord).where(PendingWorkflowRecord.incident_id == incident_uuid)
        )
        record = result.scalar_one_or_none()
        if record is not None:
            await self.session.delete(record)

    async def list_agent_work_items(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        result = await self.session.execute(
            select(AgentWorkItemRecord)
            .order_by(AgentWorkItemRecord.updated_at.desc(), AgentWorkItemRecord.sequence.asc())
            .limit(safe_limit)
        )
        rows = result.scalars().all()
        return [
            {
                "incident_id": str(row.incident_id),
                "agent_name": row.agent_name,
                "trace_id": row.trace_id,
                "ticket_id": row.ticket_id,
                "work_item": row.work_item,
                "status": row.status,
                "sequence": row.sequence,
                "details": row.details,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]

    @staticmethod
    def _parse_uuid(value: Any) -> UUID | None:
        token = str(value or "").strip()
        if not token:
            return None
        try:
            return UUID(token)
        except ValueError:
            return None

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        token = str(value or "").strip()
        if not token:
            return None
        try:
            return datetime.fromisoformat(token.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def _upsert_projection_from_record(self, event_record: IncidentEventRecord) -> None:
        result = await self.session.execute(
            select(IncidentProjectionRecord).where(IncidentProjectionRecord.incident_id == event_record.incident_id)
        )
        projection = result.scalar_one_or_none()
        if projection is None:
            projection = IncidentProjectionRecord(
                incident_id=event_record.incident_id,
                first_seen_at=event_record.created_at,
                projection_payload={},
                service=event_record.service,
                environment=event_record.environment,
                status=event_record.status or "open",
            )

        # Do not regress projection lifecycle when two events share the same timestamp.
        # In local/demo runs, recommendation and closed can be written within the same second.
        existing_latest = _utc_dt(projection.latest_event_at)
        incoming_latest = _utc_dt(event_record.created_at)
        if existing_latest is not None and incoming_latest is not None:
            if incoming_latest < existing_latest:
                return
            if incoming_latest == existing_latest:
                existing_rank = _status_rank(projection.status)
                incoming_rank = _status_rank(event_record.status)
                if incoming_rank < existing_rank:
                    return

        projection.alert_id = event_record.alert_id
        projection.trace_id = event_record.trace_id
        recommendation_uuid = _extract_recommendation_uuid(event_record.payload)
        flow_id = _extract_flow_id(event_record.payload)
        if recommendation_uuid is not None:
            projection.recommendation_id = recommendation_uuid
        if flow_id:
            projection.flow_id = flow_id
        projection.tenant_id = event_record.tenant_id or "default"
        projection.service = event_record.service
        projection.environment = event_record.environment
        projection.severity = event_record.severity
        projection.status = event_record.status or projection.status or "open"
        projection.risk_tier = event_record.risk_tier
        projection.execution_mode = event_record.execution_mode
        projection.requires_approval = event_record.requires_approval
        projection.policy_version = event_record.policy_version
        projection.policy_reason = event_record.policy_reason
        projection.transport_provider = event_record.transport_provider
        projection.latest_event_id = event_record.id
        projection.latest_event_type = event_record.event_type
        projection.latest_event_at = event_record.created_at
        projection.projection_payload = {
            "event_stage": event_record.event_stage,
            "event_type": event_record.event_type,
            "transport_channel": event_record.transport_channel,
            "event_payload": event_record.payload,
        }
        await self.session.merge(projection)

    async def save_incident_event(self, envelope: dict[str, Any]) -> None:
        identity = envelope.get("identity", {}) if isinstance(envelope.get("identity"), dict) else {}
        scope = envelope.get("scope", {}) if isinstance(envelope.get("scope"), dict) else {}
        state = envelope.get("state", {}) if isinstance(envelope.get("state"), dict) else {}
        policy = envelope.get("policy", {}) if isinstance(envelope.get("policy"), dict) else {}
        ai = envelope.get("ai", {}) if isinstance(envelope.get("ai"), dict) else {}
        transport = envelope.get("transport", {}) if isinstance(envelope.get("transport"), dict) else {}
        idempotency = envelope.get("idempotency", {}) if isinstance(envelope.get("idempotency"), dict) else {}

        incident_uuid = self._parse_uuid(identity.get("incident_id"))
        if incident_uuid is None:
            raise ValueError("identity.incident_id is required")

        record = IncidentEventRecord(
            id=self._parse_uuid(envelope.get("event_id")) or uuid4(),
            incident_id=incident_uuid,
            alert_id=self._parse_uuid(identity.get("alert_id")),
            trace_id=str(identity.get("trace_id") or "").strip() or None,
            correlation_id=str(identity.get("correlation_id") or "").strip() or None,
            causation_id=str(identity.get("causation_id") or "").strip() or None,
            parent_event_id=self._parse_uuid(identity.get("parent_event_id")),
            tenant_id=str(scope.get("tenant_id") or "default").strip() or "default",
            service=str(scope.get("service") or "unknown").strip() or "unknown",
            environment=str(scope.get("environment") or "prod").strip() or "prod",
            region=str(scope.get("region") or "").strip() or None,
            team=str(scope.get("team") or "").strip() or None,
            severity=str(state.get("severity") or "").strip() or None,
            status=str(state.get("status") or "").strip() or None,
            event_type=str(envelope.get("event_type") or "incident.event").strip(),
            event_stage=str(state.get("status") or "unknown").strip() or "unknown",
            risk_tier=str(policy.get("risk_tier") or "").strip() or None,
            execution_mode=str(policy.get("execution_mode") or "").strip() or None,
            requires_approval=bool(policy.get("requires_approval")) if "requires_approval" in policy else None,
            policy_version=str(policy.get("policy_version") or "").strip() or None,
            policy_reason=str(policy.get("policy_reason") or "").strip() or None,
            confidence=float(ai.get("confidence")) if ai.get("confidence") is not None else None,
            model_provider=str(ai.get("model_provider") or "").strip() or None,
            model_name=str(ai.get("model_name") or "").strip() or None,
            transport_provider=str(transport.get("provider") or "unknown").strip() or "unknown",
            transport_channel=str(transport.get("channel") or "unknown").strip() or "unknown",
            transport_partition=int(transport.get("partition")) if transport.get("partition") is not None else None,
            transport_offset=int(transport.get("offset")) if transport.get("offset") is not None else None,
            transport_delivery_tag=str(transport.get("delivery_tag") or "").strip() or None,
            idempotency_key=str(idempotency.get("idempotency_key") or "").strip() or None,
            fingerprint=str(idempotency.get("fingerprint") or "").strip() or None,
            payload=envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {},
            created_at=self._parse_datetime(envelope.get("produced_at")) or datetime.utcnow(),
        )
        await self.session.merge(record)
        await self._upsert_projection_from_record(record)

    async def project_recent_incident_events(self, limit: int = 500) -> int:
        safe_limit = max(1, min(int(limit), 5000))
        result = await self.session.execute(
            select(IncidentEventRecord)
            .order_by(IncidentEventRecord.created_at.desc())
            .limit(safe_limit)
        )
        rows = list(result.scalars().all())
        rows.sort(key=lambda row: row.created_at)
        for row in rows:
            await self._upsert_projection_from_record(row)
        return len(rows)

    async def list_incident_projections(
        self,
        *,
        limit: int = 100,
        tenant_id: str | None = None,
        incident_id: str | None = None,
        risk_tier: str | None = None,
        execution_mode: str | None = None,
        transport_provider: str | None = None,
        status: str | None = None,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        stmt = select(IncidentProjectionRecord)
        if tenant_id:
            stmt = stmt.where(IncidentProjectionRecord.tenant_id == str(tenant_id).strip())
        if incident_id:
            incident_uuid = self._parse_uuid(incident_id)
            if incident_uuid is None:
                return []
            stmt = stmt.where(IncidentProjectionRecord.incident_id == incident_uuid)
        if risk_tier:
            stmt = stmt.where(IncidentProjectionRecord.risk_tier == str(risk_tier).strip().lower())
        if execution_mode:
            stmt = stmt.where(IncidentProjectionRecord.execution_mode == str(execution_mode).strip().lower())
        if transport_provider:
            stmt = stmt.where(IncidentProjectionRecord.transport_provider == str(transport_provider).strip().lower())
        if status:
            stmt = stmt.where(IncidentProjectionRecord.status == str(status).strip().lower())
        if service:
            stmt = stmt.where(IncidentProjectionRecord.service == str(service).strip())
        stmt = stmt.order_by(IncidentProjectionRecord.updated_at.desc()).limit(safe_limit)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        pending_by_incident: dict[UUID, PendingWorkflowRecord] = {}
        missing_context_incidents = [
            row.incident_id
            for row in rows
            if row.recommendation_id is None or not str(row.flow_id or "").strip()
        ]
        if missing_context_incidents:
            pending_result = await self.session.execute(
                select(PendingWorkflowRecord).where(PendingWorkflowRecord.incident_id.in_(missing_context_incidents))
            )
            pending_rows = pending_result.scalars().all()
            pending_by_incident = {pending.incident_id: pending for pending in pending_rows}

        response_rows: list[dict[str, Any]] = []
        for row in rows:
            pending = pending_by_incident.get(row.incident_id)
            merged_recommendation_id = row.recommendation_id or (pending.recommendation_id if pending is not None else None)
            merged_flow_id = row.flow_id or (pending.flow_id if pending is not None else None)

            response_rows.append(
                {
                    "incident_id": str(row.incident_id),
                    "alert_id": str(row.alert_id) if row.alert_id else None,
                    "trace_id": row.trace_id,
                    "recommendation_id": str(merged_recommendation_id) if merged_recommendation_id else None,
                    "flow_id": merged_flow_id,
                    "tenant_id": row.tenant_id,
                    "service": row.service,
                    "environment": row.environment,
                    "severity": row.severity,
                    "status": row.status,
                    "owner": row.owner,
                    "risk_tier": row.risk_tier,
                    "execution_mode": row.execution_mode,
                    "requires_approval": row.requires_approval,
                    "policy_version": row.policy_version,
                    "policy_reason": row.policy_reason,
                    "transport_provider": row.transport_provider,
                    "latest_event_id": str(row.latest_event_id) if row.latest_event_id else None,
                    "latest_event_type": row.latest_event_type,
                    "latest_event_at": row.latest_event_at,
                    "updated_at": row.updated_at,
                    "projection_payload": row.projection_payload,
                }
            )
        return response_rows

    async def list_closed_incidents(self, *, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        stmt = (
            select(IncidentProjectionRecord)
            .where(IncidentProjectionRecord.status.in_(["closed", "resolved", "failed"]))
            .order_by(IncidentProjectionRecord.updated_at.desc())
            .limit(safe_limit)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        response_rows: list[dict[str, Any]] = []
        for row in rows:
            projection_payload = row.projection_payload if isinstance(row.projection_payload, dict) else {}
            event_payload = projection_payload.get("event_payload") if isinstance(projection_payload.get("event_payload"), dict) else {}
            response_rows.append(
                {
                    "incident_id": str(row.incident_id),
                    "alert_id": str(row.alert_id) if row.alert_id else None,
                    "trace_id": row.trace_id,
                    "recommendation_id": str(row.recommendation_id) if row.recommendation_id else None,
                    "flow_id": row.flow_id,
                    "service": row.service,
                    "environment": row.environment,
                    "severity": row.severity,
                    "status": row.status,
                    "risk_tier": row.risk_tier,
                    "execution_mode": row.execution_mode,
                    "transport_provider": row.transport_provider,
                    "health_restored": bool(event_payload.get("health_restored")) if "health_restored" in event_payload else None,
                    "alerts_cleared": bool(event_payload.get("alerts_cleared")) if "alerts_cleared" in event_payload else None,
                    "closed_at": row.latest_event_at or row.updated_at,
                    "updated_at": row.updated_at,
                    "projection_payload": projection_payload,
                }
            )
        return response_rows
