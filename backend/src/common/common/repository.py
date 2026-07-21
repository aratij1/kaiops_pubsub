from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.database import (
    ActionRecord,
    AlertRuleRecord,
    AgentWorkItemRecord,
    AlertRecord,
    ApplicationEnvironmentRecord,
    ApplicationLabelRecord,
    ApplicationRecord,
    ApprovalRecord,
    AuditLogRecord,
    EvaluationRecord,
    GrafanaDashboardRecord,
    IncidentEventRecord,
    IncidentRecord,
    IncidentProjectionRecord,
    KnowledgeBaseRecord,
    MonitoringProfileRecord,
    MonitoringIntegrationRecord,
    MonitoringCredentialRecord,
    MonitoringWebhookEndpointRecord,
    MonitoringAlertMappingRecord,
    MonitoringConnectionHealthRecord,
    MonitoringReceivedAlertRecord,
    MonitoringNormalizedAlertRecord,
    MonitoringConnectionAuditRecord,
    OnboardingHistoryRecord,
    RcaReportRecord,
    PrometheusConfigRecord,
    RecordingRuleRecord,
    OnboardingStateRecord,
    PendingWorkflowRecord,
    ValidationHistoryRecord,
)
from common.models import (
    Alert,
    Approval,
    ApplicationRegistration,
    GrafanaDashboardResult,
    Incident,
    MetricsValidationResult,
    MonitoringAuditEvent,
    MonitoringValidationResult,
    PrometheusUpdateResult,
    Recommendation,
    RemediationAction,
    RulesGeneratedResult,
    ResolutionReport,
    utc_now,
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


def _extract_document_available(payload: dict[str, Any] | None) -> bool | None:
    if not isinstance(payload, dict):
        return None
    if "document_available" not in payload:
        return None
    value = payload.get("document_available")
    return bool(value) if value is not None else None


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
        projection_document_available_by_incident: dict[str, bool | None] = {}
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
                incident_key = str(projection.incident_id)
                projection_status_by_incident[incident_key] = str(projection.status or "").strip()
                projection_document_available_by_incident[incident_key] = projection.document_available

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
                if incident_id in projection_document_available_by_incident:
                    payload["document_available"] = projection_document_available_by_incident[incident_id]
            enriched_rows.append(payload)

        return enriched_rows

    async def update_projection_document_flag(self, alert_id: str, available: bool) -> bool:
        """Set incident_projections.document_available for the incident linked to alert_id.

        Used after a user uploads a document for an alert so the landing page
        reflects availability immediately, without waiting for context re-collection.
        """
        parsed_alert_id = self._parse_uuid(alert_id)
        if parsed_alert_id is None:
            return False
        result = await self.session.execute(
            select(IncidentProjectionRecord)
            .where(IncidentProjectionRecord.alert_id == parsed_alert_id)
            .order_by(IncidentProjectionRecord.latest_event_at.desc())
        )
        projection = result.scalars().first()
        if projection is None:
            return False
        projection.document_available = available
        await self.session.merge(projection)
        return True

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
            input_value = payload.get("input") if isinstance(payload.get("input"), (dict, list, str, int, float, bool)) else None
            if input_value is None and isinstance(payload.get("request"), (dict, list, str, int, float, bool)):
                input_value = payload.get("request")
            if input_value is None and isinstance(payload.get("input_payload"), (dict, list, str, int, float, bool)):
                input_value = payload.get("input_payload")
            if input_value is None and isinstance(payload.get("context"), (dict, list, str, int, float, bool)):
                input_value = payload.get("context")

            output_value = payload.get("output") if isinstance(payload.get("output"), (dict, list, str, int, float, bool)) else None
            if output_value is None and isinstance(payload.get("result"), (dict, list, str, int, float, bool)):
                output_value = payload.get("result")
            if output_value is None and payload:
                # Fall back to the full payload so timeline output renders real event data.
                output_value = payload

            error_value = payload.get("error") if isinstance(payload.get("error"), (dict, list, str, int, float, bool)) else None
            if error_value is None and isinstance(payload.get("exception"), (dict, list, str, int, float, bool)):
                error_value = payload.get("exception")

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
                    "payload": payload,
                    "input_value": input_value,
                    "output_value": output_value,
                    "error": error_value,
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

        context_payload: dict[str, Any] = {}
        context_event_payload = next(
            (
                item.get("payload")
                for item in reversed(event_trace)
                if isinstance(item, dict)
                and "context" in str(item.get("event_type") or "").lower()
                and isinstance(item.get("payload"), dict)
            ),
            {},
        )
        if isinstance(context_event_payload, dict):
            nested_context = context_event_payload.get("context")
            if isinstance(nested_context, dict):
                context_payload = dict(nested_context)
            else:
                context_payload = {
                    "deployment": context_event_payload.get("deployment"),
                    "related_incidents": context_event_payload.get("related_incidents"),
                    "dependency_services": context_event_payload.get("dependency_services"),
                    "document_available": context_event_payload.get("document_available"),
                }

        context_metadata = context_payload.get("metadata") if isinstance(context_payload.get("metadata"), dict) else {}
        if recommendation_metadata.get("rag_documents") is not None:
            context_metadata.setdefault("rag_documents", recommendation_metadata.get("rag_documents"))
        if isinstance(recommendation_metadata.get("rag_matches"), list):
            context_metadata.setdefault("rag_matches", recommendation_metadata.get("rag_matches"))
        if recommendation_metadata.get("rag_top_similarity") is not None:
            context_metadata.setdefault("rag_top_similarity", recommendation_metadata.get("rag_top_similarity"))
        if recommendation_metadata.get("rag_service_tagged_match") is not None:
            context_metadata.setdefault("rag_service_tagged_match", recommendation_metadata.get("rag_service_tagged_match"))
        if context_event_payload.get("document_available") is not None:
            context_metadata.setdefault("document_available", context_event_payload.get("document_available"))
        if context_metadata:
            context_payload["metadata"] = context_metadata
        if recommendation_metadata.get("runbook_found") is not None and not context_payload.get("runbook"):
            context_payload["runbook"] = "available" if bool(recommendation_metadata.get("runbook_found")) else ""

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
            "context": context_payload,
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

    async def get_latest_recommendation_for_incident(self, incident_id: Any) -> dict[str, Any] | None:
        incident_uuid = self._parse_uuid(incident_id)
        if incident_uuid is None:
            return None
        audit_stmt = (
            select(AuditLogRecord)
            .where(AuditLogRecord.resource_type == "incident")
            .where(AuditLogRecord.resource_id == str(incident_uuid))
            .where(AuditLogRecord.action == "recommendation.generated")
            .order_by(AuditLogRecord.updated_at.desc(), AuditLogRecord.created_at.desc())
            .limit(1)
        )
        audit_result = await self.session.execute(audit_stmt)
        audit_record = audit_result.scalar_one_or_none()
        if audit_record is not None and isinstance(audit_record.payload, dict):
            return audit_record.payload

        projection_result = await self.session.execute(
            select(IncidentProjectionRecord).where(IncidentProjectionRecord.incident_id == incident_uuid)
        )
        projection = projection_result.scalar_one_or_none()
        if projection is not None and projection.recommendation_id is not None:
            return {"id": str(projection.recommendation_id), "incident_id": str(incident_uuid)}
        return None

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

    async def update_incident_approval_status(
        self,
        incident_id: Any,
        *,
        status: str,
        approval: Approval | None = None,
    ) -> bool:
        incident_uuid = self._parse_uuid(incident_id)
        normalized_status = str(status or "").strip().lower()
        if incident_uuid is None or not normalized_status:
            return False

        updated = False
        now = utc_now()

        incident = await self.session.get(IncidentRecord, incident_uuid)
        if incident is not None:
            incident.status = normalized_status
            payload = dict(incident.payload or {})
            payload["status"] = normalized_status
            payload["state"] = normalized_status
            if approval is not None:
                payload["approval"] = approval.model_dump(mode="json")
                payload["approval_status"] = normalized_status
            incident.payload = payload
            incident.updated_at = now
            await self.session.merge(incident)
            updated = True

        projection = await self.session.get(IncidentProjectionRecord, incident_uuid)
        if projection is not None:
            projection.status = normalized_status
            if approval is not None:
                projection.owner = str(approval.approver or "") or projection.owner
                projection.recommendation_id = self._parse_uuid(approval.recommendation_id) or projection.recommendation_id
            projection.latest_event_type = "incident.approval.recorded"
            projection.latest_event_at = now
            projection.updated_at = now
            projection_payload = dict(projection.projection_payload or {})
            projection_payload["status"] = normalized_status
            projection_payload["state"] = normalized_status
            projection_payload["approval_status"] = normalized_status
            if approval is not None:
                projection_payload["approval"] = approval.model_dump(mode="json")
            projection.projection_payload = projection_payload
            await self.session.merge(projection)
            updated = True

        pending = await self.session.get(PendingWorkflowRecord, incident_uuid)
        if pending is not None:
            pending.status = normalized_status
            pending.updated_at = now
            pending_payload = dict(pending.payload or {})
            pending_payload["status"] = normalized_status
            pending_payload["approval_status"] = normalized_status
            if approval is not None:
                pending_payload["approval"] = approval.model_dump(mode="json")
            pending.payload = pending_payload
            await self.session.merge(pending)
            updated = True

        return updated

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

    async def save_application(self, application: ApplicationRegistration) -> None:
        await self.session.merge(
            ApplicationRecord(
                id=self._require("application.id", application.id),
                tenant_id=self._require("application.tenant_id", application.tenant_id),
                name=self._require("application.name", application.name),
                owner_team=self._require("application.owner_team", application.owner_team),
                owner_email=application.owner_email,
                environment=self._require("application.environment", application.environment),
                namespace=self._require("application.namespace", application.namespace),
                region=self._require("application.region", application.region),
                technology=self._require("application.technology", application.technology),
                monitoring_platform=str(application.monitoring_platform),
                metrics_endpoint=self._require("application.metrics_endpoint", application.metrics_endpoint),
                status=str(application.status),
                payload=application.model_dump(mode="json"),
            )
        )
        await self.session.execute(delete(ApplicationEnvironmentRecord).where(ApplicationEnvironmentRecord.application_id == application.id))
        await self.session.execute(delete(ApplicationLabelRecord).where(ApplicationLabelRecord.application_id == application.id))
        self.session.add(
            ApplicationEnvironmentRecord(
                application_id=application.id,
                tenant_id=application.tenant_id,
                environment=application.environment,
                namespace=application.namespace,
                region=application.region,
                cluster=application.labels.get("cluster") if isinstance(application.labels, dict) else None,
                payload={"metrics_endpoint": application.metrics_endpoint},
            )
        )
        for key, value in (application.labels or {}).items():
            self.session.add(
                ApplicationLabelRecord(
                    application_id=application.id,
                    tenant_id=application.tenant_id,
                    label_key=str(key),
                    label_value=str(value),
                )
            )

    async def update_application_status(
        self,
        application_id: Any,
        *,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        record = await self.session.get(ApplicationRecord, application_id)
        if record is None:
            return
        record.status = str(status)
        if isinstance(payload, dict) and payload:
            merged_payload = dict(record.payload or {})
            merged_payload.update(payload)
            record.payload = merged_payload
        await self.session.merge(record)
    
    async def save_monitoring_integration(
        self,
        *,
        integration_id: Any,
        tenant_id: str,
        project_name: str,
        provider: str,
        status: str,
        active: bool,
        auth_type: str,
        endpoint_url: str | None,
        webhook_path: str,
        deployment_mode: str,
        config_payload: dict[str, Any],
        validation_payload: dict[str, Any],
    ) -> None:
        parsed_id = self._parse_uuid(integration_id)
        if parsed_id is None:
            raise ValueError("monitoring_integration.id is required")
        await self.session.merge(
            MonitoringIntegrationRecord(
                id=parsed_id,
                tenant_id=self._require("monitoring_integration.tenant_id", tenant_id),
                project_name=self._require("monitoring_integration.project_name", project_name),
                provider=self._require("monitoring_integration.provider", provider),
                status=self._require("monitoring_integration.status", status),
                active=bool(active),
                auth_type=self._require("monitoring_integration.auth_type", auth_type),
                endpoint_url=endpoint_url,
                webhook_path=self._require("monitoring_integration.webhook_path", webhook_path),
                deployment_mode=self._require("monitoring_integration.deployment_mode", deployment_mode),
                config_payload=config_payload or {},
                validation_payload=validation_payload or {},
            )
        )
    
    async def list_monitoring_integrations(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(MonitoringIntegrationRecord)
            .where(MonitoringIntegrationRecord.tenant_id == str(tenant_id or "default"))
            .order_by(MonitoringIntegrationRecord.updated_at.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "tenant_id": row.tenant_id,
                "project_name": row.project_name,
                "provider": row.provider,
                "status": row.status,
                "active": row.active,
                "auth_type": row.auth_type,
                "endpoint_url": row.endpoint_url,
                "webhook_path": row.webhook_path,
                "deployment_mode": row.deployment_mode,
                "config_payload": row.config_payload,
                "validation_payload": row.validation_payload,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]
    
    async def get_monitoring_integration(self, integration_id: Any) -> dict[str, Any] | None:
        parsed_id = self._parse_uuid(integration_id)
        if parsed_id is None:
            return None
        result = await self.session.execute(
            select(MonitoringIntegrationRecord).where(MonitoringIntegrationRecord.id == parsed_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": str(row.id),
            "tenant_id": row.tenant_id,
            "project_name": row.project_name,
            "provider": row.provider,
            "status": row.status,
            "active": row.active,
            "auth_type": row.auth_type,
            "endpoint_url": row.endpoint_url,
            "webhook_path": row.webhook_path,
            "deployment_mode": row.deployment_mode,
            "config_payload": row.config_payload,
            "validation_payload": row.validation_payload,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    
    async def delete_monitoring_integration(self, integration_id: Any) -> int:
        parsed_id = self._parse_uuid(integration_id)
        if parsed_id is None:
            return 0
        result = await self.session.execute(
            delete(MonitoringIntegrationRecord).where(MonitoringIntegrationRecord.id == parsed_id)
        )
        return int(result.rowcount or 0)
    
    async def save_monitoring_credential(
        self,
        *,
        credential_id: Any,
        integration_id: Any,
        credential_type: str,
        secret_ref: str,
        encrypted_payload: dict[str, Any],
        redacted_payload: dict[str, Any],
    ) -> None:
        cred_id = self._parse_uuid(credential_id)
        int_id = self._parse_uuid(integration_id)
        if cred_id is None or int_id is None:
            raise ValueError("monitoring_credential ids are required")
        await self.session.merge(
            MonitoringCredentialRecord(
                id=cred_id,
                integration_id=int_id,
                credential_type=self._require("monitoring_credential.credential_type", credential_type),
                secret_ref=self._require("monitoring_credential.secret_ref", secret_ref),
                encrypted_payload=encrypted_payload or {},
                redacted_payload=redacted_payload or {},
            )
        )
    
    async def save_monitoring_webhook_endpoint(
        self,
        *,
        endpoint_id: Any,
        integration_id: Any,
        provider: str,
        webhook_path: str,
        token_hash: str | None,
        hmac_enabled: bool,
        m_tls_enabled: bool,
        active: bool,
        metadata_payload: dict[str, Any],
    ) -> None:
        endpoint_uuid = self._parse_uuid(endpoint_id)
        integration_uuid = self._parse_uuid(integration_id)
        if endpoint_uuid is None or integration_uuid is None:
            raise ValueError("monitoring_webhook_endpoint ids are required")
        await self.session.merge(
            MonitoringWebhookEndpointRecord(
                id=endpoint_uuid,
                integration_id=integration_uuid,
                provider=self._require("monitoring_webhook_endpoint.provider", provider),
                webhook_path=self._require("monitoring_webhook_endpoint.webhook_path", webhook_path),
                token_hash=token_hash,
                hmac_enabled=bool(hmac_enabled),
                m_tls_enabled=bool(m_tls_enabled),
                active=bool(active),
                metadata_payload=metadata_payload or {},
            )
        )
    
    async def replace_monitoring_alert_mappings(
        self,
        *,
        integration_id: Any,
        provider: str,
        mappings: list[dict[str, Any]],
    ) -> int:
        integration_uuid = self._parse_uuid(integration_id)
        if integration_uuid is None:
            return 0
        await self.session.execute(
            delete(MonitoringAlertMappingRecord).where(MonitoringAlertMappingRecord.integration_id == integration_uuid)
        )
        inserted = 0
        for item in mappings:
            provider_field = str(item.get("provider_field") or "").strip()
            kaiops_field = str(item.get("kaiops_field") or "").strip()
            if not provider_field or not kaiops_field:
                continue
            self.session.add(
                MonitoringAlertMappingRecord(
                    id=uuid4(),
                    integration_id=integration_uuid,
                    provider=str(provider or "").strip(),
                    provider_field=provider_field,
                    kaiops_field=kaiops_field,
                    transform=str(item.get("transform") or "").strip() or None,
                    required=bool(item.get("required", False)),
                    mapping_payload=item if isinstance(item, dict) else {},
                )
            )
            inserted += 1
        return inserted
    
    async def list_monitoring_alert_mappings(self, integration_id: Any) -> list[dict[str, Any]]:
        integration_uuid = self._parse_uuid(integration_id)
        if integration_uuid is None:
            return []
        result = await self.session.execute(
            select(MonitoringAlertMappingRecord)
            .where(MonitoringAlertMappingRecord.integration_id == integration_uuid)
            .order_by(MonitoringAlertMappingRecord.provider_field)
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "integration_id": str(row.integration_id),
                "provider": row.provider,
                "provider_field": row.provider_field,
                "kaiops_field": row.kaiops_field,
                "transform": row.transform,
                "required": row.required,
                "mapping_payload": row.mapping_payload,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]
    
    async def save_monitoring_connection_health(
        self,
        *,
        health_id: Any,
        integration_id: Any,
        provider: str,
        status: str,
        connectivity_ok: bool,
        authentication_ok: bool,
        webhook_ok: bool,
        last_received_alert_at: datetime | None,
        last_successful_test_at: datetime | None,
        rate_limit_remaining: int | None,
        payload: dict[str, Any],
    ) -> None:
        health_uuid = self._parse_uuid(health_id)
        integration_uuid = self._parse_uuid(integration_id)
        if health_uuid is None or integration_uuid is None:
            raise ValueError("monitoring_connection_health ids are required")
        await self.session.merge(
            MonitoringConnectionHealthRecord(
                id=health_uuid,
                integration_id=integration_uuid,
                provider=self._require("monitoring_connection_health.provider", provider),
                status=self._require("monitoring_connection_health.status", status),
                connectivity_ok=bool(connectivity_ok),
                authentication_ok=bool(authentication_ok),
                webhook_ok=bool(webhook_ok),
                last_received_alert_at=last_received_alert_at,
                last_successful_test_at=last_successful_test_at,
                rate_limit_remaining=rate_limit_remaining,
                payload=payload or {},
            )
        )
    
    async def list_monitoring_connection_health(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        integration_rows = await self.list_monitoring_integrations(tenant_id=tenant_id)
        integration_ids = [self._parse_uuid(row.get("id")) for row in integration_rows]
        integration_ids = [item for item in integration_ids if item is not None]
        if not integration_ids:
            return []
        result = await self.session.execute(
            select(MonitoringConnectionHealthRecord)
            .where(MonitoringConnectionHealthRecord.integration_id.in_(integration_ids))
            .order_by(MonitoringConnectionHealthRecord.updated_at.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "integration_id": str(row.integration_id),
                "provider": row.provider,
                "status": row.status,
                "connectivity_ok": row.connectivity_ok,
                "authentication_ok": row.authentication_ok,
                "webhook_ok": row.webhook_ok,
                "last_received_alert_at": row.last_received_alert_at,
                "last_successful_test_at": row.last_successful_test_at,
                "rate_limit_remaining": row.rate_limit_remaining,
                "payload": row.payload,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]
    
    async def save_monitoring_received_alert(
        self,
        *,
        received_alert_id: Any,
        integration_id: Any | None,
        tenant_id: str,
        provider: str,
        provider_alert_id: str | None,
        dedupe_key: str | None,
        signature_valid: bool,
        auth_valid: bool,
        status: str,
        raw_payload: dict[str, Any],
    ) -> None:
        record_id = self._parse_uuid(received_alert_id)
        integration_uuid = self._parse_uuid(integration_id)
        if record_id is None:
            raise ValueError("monitoring_received_alert.id is required")
        await self.session.merge(
            MonitoringReceivedAlertRecord(
                id=record_id,
                integration_id=integration_uuid,
                tenant_id=str(tenant_id or "default"),
                provider=self._require("monitoring_received_alert.provider", provider),
                provider_alert_id=provider_alert_id,
                dedupe_key=dedupe_key,
                signature_valid=bool(signature_valid),
                auth_valid=bool(auth_valid),
                status=self._require("monitoring_received_alert.status", status),
                raw_payload=raw_payload or {},
            )
        )
    
    async def save_monitoring_normalized_alert(
        self,
        *,
        normalized_alert_id: Any,
        received_alert_id: Any,
        integration_id: Any | None,
        tenant_id: str,
        provider: str,
        application: str | None,
        environment: str | None,
        severity: str | None,
        alert_name: str,
        resource: str | None,
        labels: dict[str, Any],
        annotations: dict[str, Any],
        normalized_payload: dict[str, Any],
    ) -> None:
        normalized_id = self._parse_uuid(normalized_alert_id)
        received_id = self._parse_uuid(received_alert_id)
        integration_uuid = self._parse_uuid(integration_id)
        if normalized_id is None or received_id is None:
            raise ValueError("monitoring_normalized_alert ids are required")
        await self.session.merge(
            MonitoringNormalizedAlertRecord(
                id=normalized_id,
                received_alert_id=received_id,
                integration_id=integration_uuid,
                tenant_id=str(tenant_id or "default"),
                provider=self._require("monitoring_normalized_alert.provider", provider),
                application=application,
                environment=environment,
                severity=severity,
                alert_name=self._require("monitoring_normalized_alert.alert_name", alert_name),
                resource=resource,
                labels=labels or {},
                annotations=annotations or {},
                normalized_payload=normalized_payload or {},
            )
        )
    
    async def list_monitoring_received_alerts(self, tenant_id: str = "default", limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        result = await self.session.execute(
            select(MonitoringReceivedAlertRecord)
            .where(MonitoringReceivedAlertRecord.tenant_id == str(tenant_id or "default"))
            .order_by(MonitoringReceivedAlertRecord.created_at.desc())
            .limit(safe_limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "integration_id": str(row.integration_id) if row.integration_id else None,
                "tenant_id": row.tenant_id,
                "provider": row.provider,
                "provider_alert_id": row.provider_alert_id,
                "dedupe_key": row.dedupe_key,
                "signature_valid": row.signature_valid,
                "auth_valid": row.auth_valid,
                "status": row.status,
                "raw_payload": row.raw_payload,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    
    async def save_monitoring_connection_audit(
        self,
        *,
        audit_id: Any,
        integration_id: Any | None,
        tenant_id: str,
        actor: str,
        action: str,
        provider: str | None,
        outcome: str,
        message: str | None,
        payload: dict[str, Any],
    ) -> None:
        record_id = self._parse_uuid(audit_id)
        integration_uuid = self._parse_uuid(integration_id)
        if record_id is None:
            raise ValueError("monitoring_connection_audit.id is required")
        await self.session.merge(
            MonitoringConnectionAuditRecord(
                id=record_id,
                integration_id=integration_uuid,
                tenant_id=str(tenant_id or "default"),
                actor=self._require("monitoring_connection_audit.actor", actor),
                action=self._require("monitoring_connection_audit.action", action),
                provider=provider,
                outcome=self._require("monitoring_connection_audit.outcome", outcome),
                message=message,
                payload=payload or {},
            )
        )
    
    async def list_monitoring_connection_audit(self, tenant_id: str = "default", limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 2000))
        result = await self.session.execute(
            select(MonitoringConnectionAuditRecord)
            .where(MonitoringConnectionAuditRecord.tenant_id == str(tenant_id or "default"))
            .order_by(MonitoringConnectionAuditRecord.created_at.desc())
            .limit(safe_limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "integration_id": str(row.integration_id) if row.integration_id else None,
                "tenant_id": row.tenant_id,
                "actor": row.actor,
                "action": row.action,
                "provider": row.provider,
                "outcome": row.outcome,
                "message": row.message,
                "payload": row.payload,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def list_applications(self) -> list[dict[str, Any]]:
        result = await self.session.execute(select(ApplicationRecord).order_by(ApplicationRecord.updated_at.desc()))
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "tenant_id": row.tenant_id,
                "name": row.name,
                "owner_team": row.owner_team,
                "owner_email": row.owner_email,
                "environment": row.environment,
                "namespace": row.namespace,
                "region": row.region,
                "technology": row.technology,
                "monitoring_platform": row.monitoring_platform,
                "metrics_endpoint": row.metrics_endpoint,
                "status": row.status,
                "payload": row.payload,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]

    async def get_application(self, application_id: Any) -> dict[str, Any] | None:
        record = await self.session.get(ApplicationRecord, application_id)
        if record is None:
            return None
        return {
            "id": str(record.id),
            "tenant_id": record.tenant_id,
            "name": record.name,
            "owner_team": record.owner_team,
            "owner_email": record.owner_email,
            "environment": record.environment,
            "namespace": record.namespace,
            "region": record.region,
            "technology": record.technology,
            "monitoring_platform": record.monitoring_platform,
            "metrics_endpoint": record.metrics_endpoint,
            "status": record.status,
            "payload": record.payload,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def delete_application(self, application_id: Any) -> int:
        await self.session.execute(delete(ApplicationEnvironmentRecord).where(ApplicationEnvironmentRecord.application_id == application_id))
        await self.session.execute(delete(ApplicationLabelRecord).where(ApplicationLabelRecord.application_id == application_id))
        result = await self.session.execute(delete(ApplicationRecord).where(ApplicationRecord.id == application_id))
        return int(result.rowcount or 0)

    async def save_monitoring_profile(self, result: MetricsValidationResult, governance_status: str | None = None) -> None:
        await self.session.merge(
            MonitoringProfileRecord(
                application_id=result.application_id,
                tenant_id=result.tenant_id,
                platform="prometheus",
                exporter=result.exporter,
                technology=result.technology,
                metrics_available=result.metrics_available,
                governance_status=governance_status,
                payload=result.model_dump(mode="json"),
            )
        )

    async def replace_rules(self, result: RulesGeneratedResult) -> None:
        await self.session.execute(delete(AlertRuleRecord).where(AlertRuleRecord.application_id == result.application_id))
        await self.session.execute(delete(RecordingRuleRecord).where(RecordingRuleRecord.application_id == result.application_id))
        for rule in result.alert_rules:
            self.session.add(
                AlertRuleRecord(
                    application_id=result.application_id,
                    tenant_id=result.tenant_id,
                    name=rule.name,
                    expression=rule.expr,
                    duration=rule.duration,
                    severity=rule.severity,
                    labels=rule.labels,
                    annotations=rule.annotations,
                    payload=rule.model_dump(mode="json"),
                )
            )
        for rule in result.recording_rules:
            self.session.add(
                RecordingRuleRecord(
                    application_id=result.application_id,
                    tenant_id=result.tenant_id,
                    name=rule.name,
                    expression=rule.expr,
                    labels=rule.labels,
                    payload=rule.model_dump(mode="json"),
                )
            )

    async def save_prometheus_update(self, result: PrometheusUpdateResult) -> None:
        for config_type, file_path in result.files.items():
            content = ""
            provider_response = result.provider_response if isinstance(result.provider_response, dict) else {}
            if config_type in provider_response and isinstance(provider_response.get(config_type), str):
                content = str(provider_response.get(config_type) or "")
            self.session.add(
                PrometheusConfigRecord(
                    application_id=result.application_id,
                    tenant_id=result.tenant_id,
                    config_type=config_type,
                    version=1,
                    file_path=file_path,
                    content=content,
                    payload=result.model_dump(mode="json"),
                )
            )

    async def save_validation_result(self, result: MonitoringValidationResult) -> None:
        self.session.add(
            ValidationHistoryRecord(
                application_id=result.application_id,
                tenant_id=result.tenant_id,
                target_up=result.target_up,
                metrics_available=result.metrics_available,
                alerts_loaded=result.alerts_loaded,
                recording_rules_loaded=result.recording_rules_loaded,
                service_discovery_ok=result.service_discovery_ok,
                dashboard_ready=result.dashboard_ready,
                payload=result.model_dump(mode="json"),
            )
        )

    async def save_dashboard_result(self, result: GrafanaDashboardResult) -> None:
        await self.session.merge(
            GrafanaDashboardRecord(
                application_id=result.application_id,
                tenant_id=result.tenant_id,
                dashboard_uid=result.dashboard_uid,
                title=result.title,
                url=result.url,
                payload=result.model_dump(mode="json"),
            )
        )

    async def save_monitoring_audit(self, audit_event: MonitoringAuditEvent) -> None:
        self.session.add(
            OnboardingHistoryRecord(
                application_id=audit_event.application_id,
                tenant_id=audit_event.tenant_id,
                event_type=audit_event.event_type,
                status=audit_event.decision,
                actor=audit_event.actor,
                agent=audit_event.agent,
                decision=audit_event.decision,
                execution_time_ms=audit_event.execution_time_ms,
                payload=audit_event.model_dump(mode="json"),
            )
        )
        self.session.add(
            AuditLogRecord(
                actor=audit_event.actor,
                action=audit_event.event_type,
                resource_type="application",
                resource_id=str(audit_event.application_id),
                payload=audit_event.model_dump(mode="json"),
            )
        )

    async def list_application_history(self, application_id: Any) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(OnboardingHistoryRecord)
            .where(OnboardingHistoryRecord.application_id == application_id)
            .order_by(OnboardingHistoryRecord.created_at.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "application_id": str(row.application_id),
                "tenant_id": row.tenant_id,
                "event_type": row.event_type,
                "status": row.status,
                "actor": row.actor,
                "agent": row.agent,
                "decision": row.decision,
                "execution_time_ms": row.execution_time_ms,
                "payload": row.payload,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def list_application_dashboards(self, application_id: Any) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(GrafanaDashboardRecord)
            .where(GrafanaDashboardRecord.application_id == application_id)
            .order_by(GrafanaDashboardRecord.updated_at.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "application_id": str(row.application_id),
                "dashboard_uid": row.dashboard_uid,
                "title": row.title,
                "url": row.url,
                "payload": row.payload,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]

    async def list_application_validations(self, application_id: Any) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(ValidationHistoryRecord)
            .where(ValidationHistoryRecord.application_id == application_id)
            .order_by(ValidationHistoryRecord.created_at.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "application_id": str(row.application_id),
                "tenant_id": row.tenant_id,
                "target_up": row.target_up,
                "metrics_available": row.metrics_available,
                "alerts_loaded": row.alerts_loaded,
                "recording_rules_loaded": row.recording_rules_loaded,
                "service_discovery_ok": row.service_discovery_ok,
                "dashboard_ready": row.dashboard_ready,
                "payload": row.payload,
                "created_at": row.created_at,
            }
            for row in rows
        ]

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

        # document_available is not part of the status lifecycle, so it must not be
        # dropped by the regression guard below when events share a timestamp.
        document_available = _extract_document_available(event_record.payload)
        if document_available is not None:
            projection.document_available = document_available

        # Do not regress projection lifecycle when two events share the same timestamp.
        # In local/demo runs, recommendation and closed can be written within the same second.
        existing_latest = _utc_dt(projection.latest_event_at)
        incoming_latest = _utc_dt(event_record.created_at)
        if existing_latest is not None and incoming_latest is not None:
            if incoming_latest < existing_latest:
                await self.session.merge(projection)
                return
            if incoming_latest == existing_latest:
                existing_rank = _status_rank(projection.status)
                incoming_rank = _status_rank(event_record.status)
                if incoming_rank < existing_rank:
                    await self.session.merge(projection)
                    return

        if event_record.alert_id is not None:
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
        risk_tier: str | None = None,
        execution_mode: str | None = None,
        transport_provider: str | None = None,
        status: str | None = None,
        service: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        stmt = select(IncidentProjectionRecord)
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


class EvaluationRepository:
    """Persistence for AI Workbench evaluation reports.

    Kept separate from IncidentRepository so this new, additive capability
    can never change existing incident/alert/approval persistence behavior.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _require(name: str, value: Any) -> Any:
        if value is None:
            raise ValueError(f"{name} is required")
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"{name} is required")
        return value

    @staticmethod
    def _to_uuid(value: UUID | str | None) -> UUID | None:
        if value is None:
            return None
        return value if isinstance(value, UUID) else UUID(str(value))

    @staticmethod
    def _row_to_dict(row: EvaluationRecord) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "incident_id": str(row.incident_id) if row.incident_id else None,
            "recommendation_id": str(row.recommendation_id) if row.recommendation_id else None,
            "agent": row.agent,
            "model_provider": row.model_provider,
            "model_name": row.model_name,
            "overall_score": row.overall_score,
            "quality_label": row.quality_label,
            "requires_review": row.requires_review,
            "report": row.report_payload,
            "feedback": row.feedback_payload,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    async def save_evaluation(
        self,
        *,
        report: dict[str, Any],
        agent: str,
        incident_id: UUID | str | None = None,
        recommendation_id: UUID | str | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        evaluation_id: UUID | str | None = None,
    ) -> str:
        record_id = self._to_uuid(evaluation_id) or uuid4()
        await self.session.merge(
            EvaluationRecord(
                id=record_id,
                incident_id=self._to_uuid(incident_id),
                recommendation_id=self._to_uuid(recommendation_id),
                agent=self._require("agent", agent),
                model_provider=model_provider,
                model_name=model_name,
                overall_score=report.get("overall_score"),
                quality_label=report.get("quality_label"),
                requires_review=bool(report.get("requires_review", False)),
                report_payload=report,
            )
        )
        return str(record_id)

    async def get_evaluation(self, evaluation_id: UUID | str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(EvaluationRecord).where(EvaluationRecord.id == self._to_uuid(evaluation_id))
        )
        row = result.scalar_one_or_none()
        return self._row_to_dict(row) if row is not None else None

    async def list_evaluations(
        self,
        *,
        incident_id: UUID | str | None = None,
        agent: str | None = None,
        min_score: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        stmt = select(EvaluationRecord)
        if incident_id:
            stmt = stmt.where(EvaluationRecord.incident_id == self._to_uuid(incident_id))
        if agent:
            stmt = stmt.where(EvaluationRecord.agent == str(agent))
        if min_score is not None:
            stmt = stmt.where(EvaluationRecord.overall_score >= float(min_score))
        stmt = stmt.order_by(EvaluationRecord.created_at.desc()).limit(safe_limit)
        result = await self.session.execute(stmt)
        return [self._row_to_dict(row) for row in result.scalars().all()]

    async def summarize_evaluations(self, *, agent: str | None = None, limit: int = 1000) -> dict[str, Any]:
        safe_limit = max(1, min(int(limit), 5000))
        stmt = select(EvaluationRecord).order_by(EvaluationRecord.created_at.desc()).limit(safe_limit)
        if agent:
            stmt = stmt.where(EvaluationRecord.agent == str(agent))
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        total = len(rows)
        if total == 0:
            return {
                "total_evaluations": 0,
                "average_overall_score": 0.0,
                "requires_review_rate": 0.0,
                "quality_label_counts": {},
            }

        scores = [row.overall_score for row in rows if row.overall_score is not None]
        review_count = sum(1 for row in rows if row.requires_review)
        label_counts: dict[str, int] = {}
        for row in rows:
            label = row.quality_label or "unknown"
            label_counts[label] = label_counts.get(label, 0) + 1

        return {
            "total_evaluations": total,
            "average_overall_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "requires_review_rate": round(review_count / total, 4),
            "quality_label_counts": label_counts,
        }

    async def attach_feedback_by_recommendation(
        self, recommendation_id: UUID | str, feedback: dict[str, Any]
    ) -> bool:
        """Attaches human feedback to the most recent evaluation for a recommendation.

        Returns False (not an error) when no evaluation exists for that
        recommendation yet -- e.g. evaluation-service was unreachable when
        the recommendation was generated.
        """
        result = await self.session.execute(
            select(EvaluationRecord)
            .where(EvaluationRecord.recommendation_id == self._to_uuid(recommendation_id))
            .order_by(EvaluationRecord.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False
        row.feedback_payload = feedback
        return True
