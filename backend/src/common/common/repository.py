from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import and_, case, delete, exists, func, literal, or_, select, text, union_all
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from common.database import (
    ActionRecord,
    AgentWorkItemRecord,
    AlertRecord,
    AlertRuleRecord,
    ApplicationEnvironmentRecord,
    ApplicationLabelRecord,
    ApplicationRecord,
    ApprovalRecord,
    AuditLogRecord,
    ContextKnowledgeRecord,
    ContextSnapshotRecord,
    DraftPullRequestOutboxRecord,
    EvaluationRecord,
    GrafanaDashboardRecord,
    IncidentCorrelationOwnershipRecord,
    IncidentEventRecord,
    IncidentInvestigationBindingRecord,
    IncidentOccurrenceRecord,
    IncidentProjectionRecord,
    IncidentRecord,
    JiraTicketLinkRecord,
    KnowledgeBaseRecord,
    LearningAuditRecord,
    MonitoringAlertMappingRecord,
    MonitoringConnectionAuditRecord,
    MonitoringConnectionHealthRecord,
    MonitoringCredentialRecord,
    MonitoringIntegrationRecord,
    MonitoringNormalizedAlertRecord,
    MonitoringProfileRecord,
    MonitoringReceivedAlertRecord,
    MonitoringWebhookEndpointRecord,
    ObjectStorageRecord,
    OnboardingControlPlaneRecord,
    OnboardingHistoryRecord,
    OnboardingStateRecord,
    PendingWorkflowRecord,
    PrometheusConfigRecord,
    RcaReportRecord,
    RecordingRuleRecord,
    ResolutionOutboxRecord,
    RunbookOutcomeRecord,
    RunbookVersionRecord,
    ValidationHistoryRecord,
    ValidationObservationRecord,
)
from common.incident_status import reduce_incident_status
from common.incident_investigation import IncidentInvestigationContract
from common.resolution_lifecycle import select_current_lifecycle
from common.tenant_identity import require_tenant_id


class ObjectStorageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, values: dict[str, Any]) -> ObjectStorageRecord:
        object_key = str(values["object_key"])
        row = (await self.session.execute(select(ObjectStorageRecord).where(ObjectStorageRecord.object_key == object_key))).scalar_one_or_none()
        if row is None:
            row = ObjectStorageRecord(**values)
            self.session.add(row)
        else:
            for key, value in values.items():
                if key not in {"id", "object_key", "created_at"} and hasattr(row, key):
                    setattr(row, key, value)
        await self.session.flush()
        return row

    async def list(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
        application: str | None = None,
        environment: str | None = None,
        incident_id: UUID | None = None,
        alert_id: UUID | None = None,
    ) -> list[ObjectStorageRecord]:
        stmt = select(ObjectStorageRecord)
        if status:
            stmt = stmt.where(ObjectStorageRecord.processing_status == status)
        if application:
            stmt = stmt.where(ObjectStorageRecord.application == application)
        if environment:
            stmt = stmt.where(ObjectStorageRecord.environment == environment)
        if incident_id:
            stmt = stmt.where(ObjectStorageRecord.incident_id == incident_id)
        if alert_id:
            stmt = stmt.where(ObjectStorageRecord.alert_id == alert_id)
        result = await self.session.execute(stmt.order_by(ObjectStorageRecord.created_at.desc()).limit(max(1, min(int(limit), 500))))
        return list(result.scalars().all())

    async def get(self, object_id: UUID) -> ObjectStorageRecord | None:
        return (await self.session.execute(select(ObjectStorageRecord).where(ObjectStorageRecord.id == object_id))).scalar_one_or_none()

    async def retention_candidates(self, *, before: datetime, limit: int = 500) -> list[ObjectStorageRecord]:
        stmt = (
            select(ObjectStorageRecord)
            .where(
                ObjectStorageRecord.processing_status == "stored",
                ObjectStorageRecord.ingested_at.is_not(None),
                ObjectStorageRecord.ingested_at < before,
            )
            .order_by(ObjectStorageRecord.ingested_at.asc())
            .limit(max(1, min(int(limit), 5000)))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def mark_deleted(self, row: ObjectStorageRecord, *, deleted_at: datetime) -> None:
        row.processing_status = "deleted"
        row.metadata_payload = {**(row.metadata_payload or {}), "deleted_at": deleted_at.isoformat()}
        await self.session.flush()
from common.models import (
    Alert,
    ApplicationRegistration,
    Approval,
    ApprovalDecision,
    GrafanaDashboardResult,
    Incident,
    MetricsValidationResult,
    MonitoringAuditEvent,
    MonitoringValidationResult,
    PrometheusUpdateResult,
    Recommendation,
    RemediationAction,
    ResolutionReport,
    RulesGeneratedResult,
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
_CLOSED_INCIDENT_STATUSES = frozenset({"closed", "resolved", "cancelled", "canceled"})

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


_DISCOVERY_DEFAULT_CODE_ROOT = "/app/fault-lab"
_DISCOVERY_DEFAULT_LOG_ROOT = "/app/fault-lab/runtime"



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


def _normalize_match_token(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _collect_alert_application_tokens(alert_payload: dict[str, Any]) -> list[str]:
    labels = alert_payload.get("labels", {}) if isinstance(alert_payload.get("labels"), dict) else {}
    candidates = [
        alert_payload.get("application"),
        alert_payload.get("project"),
        alert_payload.get("project_name"),
        alert_payload.get("service"),
        labels.get("application"),
        labels.get("project"),
        labels.get("project_name"),
        labels.get("namespace"),
        labels.get("job"),
    ]
    rows = [str(value or "").strip() for value in candidates if str(value or "").strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for value in rows:
        token = _normalize_match_token(value)
        if not token or token in seen:
            continue
        seen.add(token)
        deduped.append(value)
    return deduped


def _short_snippet(value: Any, limit: int = 520) -> str:
    compact = re.sub(r"\s+", " ", str(value or "").strip())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _make_discovery_evidence_row(source: str, uri: str, snippet: str, matched_terms: list[str]) -> dict[str, Any]:
    payload = f"{source}|{uri}|{snippet}"
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return {
        "evidence_id": f"{source.upper()}-{digest}",
        "source": source,
        "uri": uri,
        "path": uri.split("://", 1)[-1].split("#", 1)[0],
        "line": 1,
        "snippet": _short_snippet(snippet),
        "matched_terms": matched_terms,
        "sha256": hashlib.sha256(snippet.encode("utf-8", errors="ignore")).hexdigest(),
    }


def _build_discovery_contract(
    *,
    alert_payload: dict[str, Any],
    recommendation: dict[str, Any],
    recommendation_metadata: dict[str, Any],
    matched_application_payload: dict[str, Any],
    onboarding_rows: list[OnboardingStateRecord],
    existing_rag_documents: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    labels = alert_payload.get("labels", {}) if isinstance(alert_payload.get("labels"), dict) else {}
    service = str(alert_payload.get("service") or labels.get("service") or "unknown-service").strip()
    alert_name = str(alert_payload.get("name") or labels.get("alertname") or "incident-alert").strip()
    environment = str(alert_payload.get("environment") or labels.get("environment") or "prod").strip()
    application_tokens = _collect_alert_application_tokens(alert_payload)
    query_terms = [service, alert_name, environment, *application_tokens]
    query_terms = [item for item in query_terms if item]

    discovery_payload = (
        matched_application_payload.get("discovery")
        if isinstance(matched_application_payload.get("discovery"), dict)
        else {}
    )
    discovery_labels = (
        discovery_payload.get("labels") if isinstance(discovery_payload.get("labels"), dict) else {}
    )
    discovered_resources = (
        discovery_payload.get("discovered_resources")
        if isinstance(discovery_payload.get("discovered_resources"), list)
        else []
    )

    discovered_services = [
        str(item.get("name") or "").strip()
        for item in discovered_resources
        if isinstance(item, dict) and str(item.get("kind") or "").strip().lower() == "discoveredservice"
    ]
    discovered_services = [item for item in discovered_services if item]
    discovered_languages = [
        item.strip()
        for item in str(discovery_labels.get("discovered_languages") or "").split(",")
        if item.strip()
    ]
    codebase_root = str(discovery_labels.get("codebase_root") or _DISCOVERY_DEFAULT_CODE_ROOT).strip()
    files_scanned = str(discovery_labels.get("codebase_files_scanned") or "").strip() or "0"
    log_error_count = str(discovery_labels.get("log_error_count") or "0").strip() or "0"
    alert_names = [
        item.strip()
        for item in str(discovery_labels.get("discovered_alert_names") or "").split(",")
        if item.strip()
    ]

    onboarding_inputs: list[str] = []
    onboarding_roots: list[str] = []
    for row in onboarding_rows:
        if row.endpoint_url:
            onboarding_roots.append(str(row.endpoint_url))
        project_payload = row.project_payload if isinstance(row.project_payload, dict) else {}
        connectivity_payload = row.connectivity_payload if isinstance(row.connectivity_payload, dict) else {}
        source_docs = project_payload.get("source_documents") if isinstance(project_payload.get("source_documents"), list) else []
        if source_docs:
            for item in source_docs[:20]:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("kind") or "other").strip().lower() or "other"
                name = str(item.get("name") or "uploaded-document").strip() or "uploaded-document"
                excerpt = str(item.get("excerpt") or item.get("content") or item.get("text") or "").strip()
                onboarding_inputs.append(f"{kind}: {name} {excerpt}")
        requirements = connectivity_payload.get("result", {}).get("project", {}).get("monitoring_requirements")
        if isinstance(requirements, list) and requirements:
            onboarding_inputs.extend(str(item).strip() for item in requirements[:20] if str(item).strip())
        summary = connectivity_payload.get("summary")
        if isinstance(summary, dict):
            onboarding_inputs.append(json_dumps_safe(summary))

    rag_docs = [item for item in existing_rag_documents if isinstance(item, dict)]
    for doc in rag_docs[:20]:
        doc_title = str(doc.get("title") or doc.get("path") or "document").strip()
        doc_kind = str(doc.get("kind") or doc.get("document_kind") or "other").strip().lower()
        doc_summary = str(doc.get("summary") or doc.get("recommended_action") or "").strip()
        onboarding_inputs.append(f"{doc_kind}: {doc_title} {doc_summary}")

    code_matches: list[dict[str, Any]] = []
    if discovered_services or discovered_languages or int(files_scanned or "0") > 0:
        code_matches.append(
            {
                "service_candidates": discovered_services,
                "languages": discovered_languages,
                "files_scanned": int(files_scanned or "0"),
                "root": codebase_root,
            }
        )

    log_matches: list[dict[str, Any]] = []
    if alert_names or int(log_error_count or "0") > 0:
        log_matches.append(
            {
                "alert_names": alert_names,
                "error_count": int(log_error_count or "0"),
                "root": _DISCOVERY_DEFAULT_LOG_ROOT,
            }
        )

    ticket_matches: list[dict[str, Any]] = []
    for item in onboarding_inputs[:20]:
        ticket_matches.append({"text": _short_snippet(item, 360)})

    evidence: list[dict[str, Any]] = []
    if code_matches:
        evidence.append(
            _make_discovery_evidence_row(
                "code",
                f"code://{codebase_root}",
                f"services={','.join(discovered_services) or service}; languages={','.join(discovered_languages)}; files_scanned={files_scanned}",
                query_terms[:8],
            )
        )
    if log_matches:
        evidence.append(
            _make_discovery_evidence_row(
                "log",
                f"log://{_DISCOVERY_DEFAULT_LOG_ROOT}/application.log",
                f"error_count={log_error_count}; alert_names={','.join(alert_names) or alert_name}",
                query_terms[:8],
            )
        )
    for index, item in enumerate(onboarding_inputs[:8], start=1):
        evidence.append(
            _make_discovery_evidence_row(
                "ticket",
                f"ticket://onboarding/input#{index}",
                item,
                query_terms[:8],
            )
        )

    root_cause = str(recommendation.get("root_cause") or alert_payload.get("description") or "").strip()
    if not root_cause:
        root_cause = f"{service} is degraded according to alert {alert_name}."
    supporting = [row.get("evidence_id") for row in evidence[:4] if isinstance(row, dict) and row.get("evidence_id")]
    report = {
        "summary": f"Discovery correlated {len(evidence)} evidence item(s) across tickets, logs, codebase, and onboarding inputs for {service}.",
        "model": "kaiops-discovery-synth-v1",
        "insufficient_evidence": not bool(evidence),
        "hypotheses": [
            {
                "cause": root_cause,
                "confidence": 0.74 if evidence else 0.42,
                "supporting_evidence": supporting,
            }
        ],
    }

    retrieval_stages = [
        {"stage": "query_planned", "status": "completed", "result_count": len(query_terms)},
        {"stage": "ticket_search", "status": "completed", "result_count": len([row for row in evidence if row.get("source") == "ticket"])},
        {"stage": "log_search", "status": "completed", "result_count": len([row for row in evidence if row.get("source") == "log"])},
        {"stage": "code_search", "status": "completed", "result_count": len([row for row in evidence if row.get("source") == "code"])},
        {"stage": "onboarding_context_merge", "status": "completed", "result_count": len(onboarding_inputs)},
        {"stage": "discovery_completed", "status": "completed", "result_count": len(evidence)},
    ]

    discovery_report = {
        "protocol": "mcp-jsonrpc-2.0",
        "server": "kaiops-discovery-mcp",
        "retrieval_stages": retrieval_stages,
        "evidence": evidence,
        "report": report,
    }
    discovery_evidence = {
        "query_terms": query_terms,
        "code_roots": [codebase_root],
        "log_roots": [_DISCOVERY_DEFAULT_LOG_ROOT],
        "ticket_roots": onboarding_roots,
        "code_matches": code_matches,
        "log_matches": log_matches,
        "ticket_matches": ticket_matches,
    }
    return discovery_report, discovery_evidence


def json_dumps_safe(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


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
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
                tenant_id=alert.tenant_id or "default",
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

    async def get_open_jira_ticket_link(self, fingerprint: str) -> dict[str, Any] | None:
        """Centralized dedup lookup: is there already an open Jira ticket
        for this alert fingerprint? Ingestion paths (Prometheus/log/email)
        call this before deciding whether to create a new Jira issue or
        comment on the existing one."""
        result = await self.session.execute(
            select(JiraTicketLinkRecord).where(
                JiraTicketLinkRecord.fingerprint == self._require("fingerprint", fingerprint),
                JiraTicketLinkRecord.status == "open",
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "fingerprint": row.fingerprint,
            "jira_issue_key": row.jira_issue_key,
            "status": row.status,
            "source": row.source,
            "occurrence_count": row.occurrence_count,
            "first_seen_at": row.first_seen_at,
            "last_seen_at": row.last_seen_at,
        }

    async def save_jira_ticket_link(self, *, fingerprint: str, jira_issue_key: str, source: str) -> None:
        """Records a newly-created Jira issue against its alert fingerprint."""
        now = utc_now()
        await self.session.merge(
            JiraTicketLinkRecord(
                id=uuid4(),
                fingerprint=self._require("fingerprint", fingerprint),
                jira_issue_key=self._require("jira_issue_key", jira_issue_key),
                status="open",
                source=self._require("source", source),
                occurrence_count=1,
                first_seen_at=now,
                last_seen_at=now,
            )
        )

    async def bump_jira_ticket_occurrence(self, fingerprint: str) -> None:
        """Records a repeat occurrence against an already-open Jira ticket
        (a comment was added rather than a new issue created)."""
        result = await self.session.execute(
            select(JiraTicketLinkRecord).where(JiraTicketLinkRecord.fingerprint == self._require("fingerprint", fingerprint))
        )
        row = result.scalar_one_or_none()
        if row is None:
            return
        row.occurrence_count += 1
        row.last_seen_at = utc_now()

    async def close_jira_ticket_link(self, jira_issue_key: str) -> None:
        """Marks the link closed once the Jira ticket itself is resolved/closed,
        so the next occurrence of the same fingerprint opens a fresh ticket
        instead of commenting on a closed one."""
        result = await self.session.execute(
            select(JiraTicketLinkRecord).where(JiraTicketLinkRecord.jira_issue_key == self._require("jira_issue_key", jira_issue_key))
        )
        row = result.scalar_one_or_none()
        if row is None:
            return
        row.status = "closed"

    async def list_alerts(
        self,
        limit: int = 500,
        include_incident_context: bool = True,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 10000))
        alert_ids_query = select(AlertRecord.id)
        if tenant_id is not None:
            alert_ids_query = alert_ids_query.where(AlertRecord.tenant_id == self._require("tenant_id", tenant_id))
        alert_ids_result = await self.session.execute(alert_ids_query.order_by(AlertRecord.created_at.desc()).limit(safe_limit))
        alert_ids = [row[0] for row in alert_ids_result.all()]
        if not alert_ids:
            return []

        result = await self.session.execute(
            select(AlertRecord)
            .options(load_only(AlertRecord.id, AlertRecord.payload, AlertRecord.created_at, AlertRecord.updated_at))
            .where(AlertRecord.id.in_(alert_ids))
        )
        rows_by_id = {row.id: row for row in result.scalars().all()}
        rows = [rows_by_id[alert_id] for alert_id in alert_ids if alert_id in rows_by_id]
        if not rows:
            return []

        if not include_incident_context:
            return [dict(row.payload) if isinstance(row.payload, dict) else {} for row in rows]

        alert_id_set = {str(row.id) for row in rows}
        alert_to_incident: dict[str, str] = {}

        # Incident payload carries linked alert IDs. Build a reverse map to incident IDs,
        # preferring most recent incidents by updated timestamp.
        incident_ids_result = await self.session.execute(
            select(IncidentRecord.id)
            .order_by(IncidentRecord.created_at.desc())
            .limit(max(150, safe_limit * 3))
        )
        incident_ids = [row[0] for row in incident_ids_result.all()]
        incident_result = await self.session.execute(
            select(IncidentRecord)
            .options(load_only(IncidentRecord.id, IncidentRecord.payload))
            .where(IncidentRecord.id.in_(incident_ids))
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

    async def list_alerts_source_balanced(self, limit: int = 500, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """Return recent alerts while reserving the latest row per durable source.

        A global LIMIT alone lets bursty sources crowd low-volume sources out of
        the intake UI. This performs one indexed latest-row lookup per distinct
        source and fills the rest from the normal recent window.

        `tenant_id`: when provided, scopes every query to that tenant only
        (backed by idx_alerts_tenant). None returns across all tenants, which
        callers should only do for internal/trusted contexts, not for a
        caller-facing list endpoint.
        """
        safe_limit = max(1, min(int(limit), 5000))
        sources_query = select(AlertRecord.source).distinct()
        if tenant_id is not None:
            sources_query = sources_query.where(AlertRecord.tenant_id == tenant_id)
        sources_result = await self.session.execute(sources_query)
        sources = [str(row[0] or "").strip() for row in sources_result.all() if str(row[0] or "").strip()]

        reserved: list[AlertRecord] = []
        for source in sources:
            query = (
                select(AlertRecord)
                .options(load_only(AlertRecord.id, AlertRecord.payload, AlertRecord.created_at))
                .where(AlertRecord.source == source)
            )
            if tenant_id is not None:
                query = query.where(AlertRecord.tenant_id == tenant_id)
            result = await self.session.execute(query.order_by(AlertRecord.created_at.desc()).limit(1))
            record = result.scalar_one_or_none()
            if record is not None:
                reserved.append(record)

        recent_query = select(AlertRecord).options(
            load_only(AlertRecord.id, AlertRecord.payload, AlertRecord.created_at)
        )
        if tenant_id is not None:
            recent_query = recent_query.where(AlertRecord.tenant_id == tenant_id)
        recent_result = await self.session.execute(
            recent_query.order_by(AlertRecord.created_at.desc()).limit(safe_limit)
        )
        recent = list(recent_result.scalars().all())
        selected: list[AlertRecord] = []
        seen: set[UUID] = set()
        for record in [*reserved, *recent]:
            if record.id in seen:
                continue
            seen.add(record.id)
            selected.append(record)
        selected = sorted(selected, key=lambda row: row.created_at, reverse=True)

        # Preserve source reservations even when source count approaches limit.
        reserved_ids = {row.id for row in reserved}
        output = [row for row in selected if row.id in reserved_ids]
        output.extend(row for row in selected if row.id not in reserved_ids)
        output = sorted(output[:safe_limit], key=lambda row: row.created_at, reverse=True)
        alert_ids = {str(row.id) for row in output}
        incident_by_alert: dict[str, dict[str, Any]] = {}
        incident_query = (
            select(IncidentRecord)
            .options(load_only(IncidentRecord.id, IncidentRecord.ticket_id, IncidentRecord.payload))
            .order_by(IncidentRecord.created_at.desc())
            .limit(max(150, safe_limit * 3))
        )
        if tenant_id is not None:
            incident_query = incident_query.where(IncidentRecord.tenant_id == tenant_id)
        incident_result = await self.session.execute(incident_query)
        for incident in incident_result.scalars().all():
            incident_payload = incident.payload if isinstance(incident.payload, dict) else {}
            linked_alert_ids = incident_payload.get("alert_ids", [])
            if not isinstance(linked_alert_ids, list):
                continue
            for linked_alert_id in linked_alert_ids:
                alert_id = str(linked_alert_id)
                if alert_id in alert_ids and alert_id not in incident_by_alert:
                    incident_by_alert[alert_id] = {
                        "incident_id": str(incident.id),
                        "ticket_id": str(incident.ticket_id or "").strip() or None,
                    }

        rows: list[dict[str, Any]] = []
        for record in output:
            payload = dict(record.payload) if isinstance(record.payload, dict) else {}
            payload.update({key: value for key, value in incident_by_alert.get(str(record.id), {}).items() if value})
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            deduplication = metadata.get("deduplication") if isinstance(metadata.get("deduplication"), dict) else {}
            payload["incident_disposition"] = str(
                deduplication.get("disposition")
                or ("duplicate" if int(payload.get("deduplicated_count") or 1) > 1 else "new_incident")
            )
            rows.append(payload)
        return rows

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

    async def get_processed_result_by_alert_id(
        self,
        alert_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        normalized_alert_id = str(alert_id or "").strip()
        if not normalized_alert_id:
            return None
        normalized_tenant_id = self._require("tenant_id", tenant_id)

        try:
            alert_uuid = UUID(normalized_alert_id)
        except ValueError:
            return None

        alert_result = await self.session.execute(
            select(AlertRecord).where(
                AlertRecord.id == alert_uuid,
                AlertRecord.tenant_id == normalized_tenant_id,
            )
        )
        alert_record = alert_result.scalar_one_or_none()
        if alert_record is None:
            return None

        alert_payload = alert_record.payload if isinstance(alert_record.payload, dict) else {}
        alert_labels = alert_payload.get("labels") if isinstance(alert_payload.get("labels"), dict) else {}
        explicit_incident_id = str(
            alert_payload.get("incident_id")
            or alert_labels.get("kaiops_incident_id")
            or ""
        ).strip()

        incident_record = None
        explicit_incident_uuid = self._parse_uuid(explicit_incident_id)
        if explicit_incident_uuid is not None:
            explicit_result = await self.session.execute(
                select(IncidentRecord).where(
                    IncidentRecord.id == explicit_incident_uuid,
                    IncidentRecord.tenant_id == normalized_tenant_id,
                )
            )
            incident_record = explicit_result.scalar_one_or_none()

        if incident_record is None:
            # The projection is the authoritative alert-to-incident relation.
            # Repeated alerts for the same service/Jira may have many incident
            # records, so a service/severity fallback can hydrate an alert with
            # a newer, still-investigating incident and hide its persisted RCA.
            projection_result = await self.session.execute(
                select(IncidentProjectionRecord)
                .where(
                    IncidentProjectionRecord.alert_id == alert_uuid,
                    IncidentProjectionRecord.tenant_id == normalized_tenant_id,
                )
                .order_by(
                    IncidentProjectionRecord.latest_event_at.desc(),
                    IncidentProjectionRecord.updated_at.desc(),
                )
                .limit(1)
            )
            projection_record = projection_result.scalar_one_or_none()
            projection_incident_uuid = self._parse_uuid(
                getattr(projection_record, "incident_id", None)
            )
            if projection_incident_uuid is not None:
                projection_incident_result = await self.session.execute(
                    select(IncidentRecord).where(
                        IncidentRecord.id == projection_incident_uuid,
                        IncidentRecord.tenant_id == normalized_tenant_id,
                    )
                )
                incident_record = projection_incident_result.scalar_one_or_none()

        if incident_record is None:
            occurrence_result = await self.session.execute(
                select(IncidentOccurrenceRecord)
                .where(
                    IncidentOccurrenceRecord.occurrence_id == alert_uuid,
                    IncidentOccurrenceRecord.tenant_id == normalized_tenant_id,
                )
                .order_by(IncidentOccurrenceRecord.observed_at.desc())
                .limit(1)
            )
            occurrence_record = occurrence_result.scalar_one_or_none()
            if occurrence_record is not None:
                occurrence_incident_result = await self.session.execute(
                    select(IncidentRecord).where(
                        IncidentRecord.id == occurrence_record.canonical_incident_id,
                        IncidentRecord.tenant_id == normalized_tenant_id,
                    )
                )
                incident_record = occurrence_incident_result.scalar_one_or_none()

        if incident_record is None:
            incident_rows = await self.session.execute(
                select(IncidentRecord)
                .where(IncidentRecord.tenant_id == normalized_tenant_id)
                .order_by(IncidentRecord.updated_at.desc(), IncidentRecord.created_at.desc())
                .limit(300)
            )
            for record in incident_rows.scalars().all():
                payload = record.payload if isinstance(record.payload, dict) else {}
                linked_alert_ids = payload.get("alert_ids", []) if isinstance(payload.get("alert_ids"), list) else []
                linked_as_strings = {str(item) for item in linked_alert_ids}
                if normalized_alert_id in linked_as_strings:
                    incident_record = record
                    break

        if incident_record is None:
            alert_tokens = {_normalize_match_token(item) for item in _collect_alert_application_tokens(alert_payload)}

            app_result = await self.session.execute(
                select(ApplicationRecord)
                .where(ApplicationRecord.tenant_id == normalized_tenant_id)
                .order_by(ApplicationRecord.updated_at.desc())
                .limit(500)
            )
            matched_application_payload: dict[str, Any] = {}
            for app_row in app_result.scalars().all():
                app_name = str(getattr(app_row, "name", "") or "").strip()
                app_namespace = str(getattr(app_row, "namespace", "") or "").strip()
                app_tokens = {_normalize_match_token(app_name), _normalize_match_token(app_namespace)}
                if not (alert_tokens & {token for token in app_tokens if token}):
                    continue
                matched_application_payload = app_row.payload if isinstance(app_row.payload, dict) else {}
                break

            onboarding_result = await self.session.execute(
                select(OnboardingStateRecord)
                .where(OnboardingStateRecord.tenant_id == normalized_tenant_id)
                .order_by(OnboardingStateRecord.updated_at.desc())
                .limit(500)
            )
            matched_onboarding_rows: list[OnboardingStateRecord] = []
            for onboarding_row in onboarding_result.scalars().all():
                project_token = _normalize_match_token(getattr(onboarding_row, "project_name", ""))
                if project_token and project_token in alert_tokens:
                    matched_onboarding_rows.append(onboarding_row)

            discovery_report, discovery_evidence = _build_discovery_contract(
                alert_payload=alert_payload,
                recommendation={},
                recommendation_metadata={},
                matched_application_payload=matched_application_payload,
                onboarding_rows=matched_onboarding_rows,
                existing_rag_documents=[],
            )

            service_name = str(alert_payload.get("service") or "selected service").strip() or "selected service"
            hypotheses = discovery_report.get("hypotheses") if isinstance(discovery_report.get("hypotheses"), list) else []
            first_hypothesis = hypotheses[0] if hypotheses and isinstance(hypotheses[0], dict) else {}
            evidence_ids = [
                str(item.get("evidence_id"))
                for item in discovery_evidence
                if isinstance(item, dict) and str(item.get("evidence_id") or "").strip()
            ]
            fallback_root_cause = str(first_hypothesis.get("cause") or "").strip() or (
                f"RCA pending: evidence for {service_name} has been collected but no validated causal conclusion exists yet."
            )
            fallback_impact = (
                f"No direct customer or service impact is established by the collected evidence for {service_name}; "
                "validate availability, latency, error rate, and dependency health before assigning impact."
            )
            recommendation = {
                "id": str(uuid4()),
                "incident_id": None,
                "root_cause": fallback_root_cause,
                "impact": fallback_impact,
                "recommended_action": "Review discovery evidence, verify logs and linked tickets, then run the approved remediation runbook.",
                "confidence": min(float(first_hypothesis.get("confidence") or 0.0), 0.49),
                "metadata": {
                    "fallback": True,
                    "fallback_reason": "No linked incident projection exists for this alert yet.",
                    "discovery_report": discovery_report,
                    "discovery_evidence": discovery_evidence,
                    "rca_analysis": {
                        "root_cause": fallback_root_cause,
                        "evidence_used": evidence_ids,
                        "confidence_score": min(float(first_hypothesis.get("confidence") or 0.0), 0.49),
                        "missing_evidence": ["A linked incident projection and Resolution Agent result are not available yet."],
                    },
                    "impact_analysis": {
                        "impact_summary": fallback_impact,
                        "evidence_used": [],
                        "confidence_score": 0.0,
                        "missing_evidence": ["No direct service or customer-impact measurement was cited."],
                    },
                    "model_usage": [],
                },
            }
            context_payload = {
                "deployment": "unknown",
                "related_incidents": [],
                "dependency_services": [],
                "document_available": False,
                "metadata": {
                    "discovery_report": discovery_report,
                    "discovery_evidence": discovery_evidence,
                },
            }
            return {
                "mode": "alert-only-fallback",
                "scenario": {
                    "id": "alert-only",
                    "title": str(alert_payload.get("name") or "Alert"),
                    "recommended_action": recommendation["recommended_action"],
                },
                "alert": alert_payload,
                "incident": {
                    "id": None,
                    "status": str(alert_payload.get("status") or alert_payload.get("state") or "investigating"),
                    "service": alert_payload.get("service"),
                    "severity": alert_payload.get("severity"),
                    "created_at": alert_payload.get("created_at"),
                },
                "decision": {
                    "workflow": "guided-remediation",
                    "requires_approval": True,
                    "risk_tier": "high",
                    "execution_mode": "supervised",
                    "policy_version": "policy-v1",
                    "policy_reason": "Incident projection unavailable; requiring supervised path.",
                    "message_bus_provider": "rabbitmq",
                    "stream_count": 0,
                    "stream_threshold": 0,
                    "planner_used": False,
                    "planner_model": None,
                    "planner_reason": "fallback path",
                },
                "context": context_payload,
                "recommendation": recommendation,
                "investigation_integrity": {
                    "status": "missing_recommendation",
                    "verified": False,
                    "blocking_reasons": ["alert is not linked to a persisted incident recommendation"],
                    "recommendation_id": None,
                    "context_snapshot_id": None,
                },
                "approval": {},
                "remediation_action": {},
                "closure_report": {},
                "metrics": {
                    "severity": str(alert_payload.get("severity") or "unknown").upper(),
                    "remediation_status": "unknown",
                    "health_restored": False,
                    "alerts_cleared": False,
                    "recommendation_confidence": float(recommendation.get("confidence", 0.0) or 0.0),
                    "agent_handoffs": 0,
                },
                "finops": {
                    "totals": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                        "total_cost_usd": 0.0,
                        "calls": 0,
                        "failed_calls": 0,
                    },
                    "by_provider": [],
                    "calls": [],
                    "errors": [],
                    "currency": "USD",
                },
                "events": [],
                "event_trace": [],
                "trace_summary": {
                    "services_called": [],
                    "channels": [],
                    "tables_touched": [],
                    "event_count": 0,
                },
                "next_step": "Discovery context loaded from onboarding inputs, ticket/log/code evidence, and alert metadata while incident projection is pending.",
            }

        incident_payload = dict(incident_record.payload) if isinstance(incident_record.payload, dict) else {}
        incident_id_str = str(incident_record.id)
        incident_payload["id"] = incident_id_str
        incident_payload["status"] = incident_record.status
        incident_payload["severity"] = incident_record.severity
        incident_payload["service"] = incident_record.service
        incident_payload["environment"] = incident_record.environment
        incident_payload["title"] = incident_record.title
        ticket_id = incident_record.ticket_id or incident_payload.get("ticket_id") or ""
        incident_payload["ticket_id"] = ticket_id or None

        import os
        jira_base = str(os.environ.get("JIRA_URL") or os.environ.get("JIRA_API_BASE_URL") or "").rstrip("/")
        jira_link = f"{jira_base}/browse/{ticket_id}" if (ticket_id and jira_base) else None
        incident_payload["jira_link"] = jira_link
        # jira_key/jira_url alias the same value under the naming convention
        # alert-intelligence and the incident list UI already use.
        incident_payload["jira_key"] = ticket_id or None
        incident_payload["jira_url"] = jira_link

        status_lower = str(incident_record.status or "").strip().lower()
        jira_status = None
        if ticket_id:
            if status_lower in {"closed", "resolved", "done"}:
                jira_status = "Done"
            elif status_lower in {"pending", "awaiting_approval"}:
                jira_status = "Awaiting Approval"
            else:
                jira_status = "In Progress"
        incident_payload["jira_status"] = jira_status


        bound_projection = (
            await self.session.execute(
                select(IncidentProjectionRecord).where(
                    IncidentProjectionRecord.incident_id == incident_record.id,
                    IncidentProjectionRecord.alert_id == alert_uuid,
                    IncidentProjectionRecord.tenant_id == normalized_tenant_id,
                )
            )
        ).scalar_one_or_none()
        bound_investigation = await self.get_bound_incident_investigation(
            tenant_id=normalized_tenant_id,
            incident_id=incident_record.id,
            alert_id=alert_uuid,
            recommendation_id=(
                bound_projection.recommendation_id if bound_projection is not None else None
            ),
        )
        recommendation = dict(bound_investigation.get("recommendation") or {})
        investigation_integrity = dict(
            bound_investigation.get("investigation_integrity") or {}
        )

        approval = {}
        approval_stmt = select(ApprovalRecord).where(
                ApprovalRecord.incident_id == UUID(incident_id_str),
                ApprovalRecord.tenant_id == normalized_tenant_id,
            )
        if bound_projection is not None and bound_projection.recommendation_id is not None:
            approval_stmt = approval_stmt.where(
                ApprovalRecord.recommendation_id == bound_projection.recommendation_id
            )
        approval_result = await self.session.execute(
            approval_stmt
            .order_by(ApprovalRecord.updated_at.desc(), ApprovalRecord.created_at.desc())
            .limit(1)
        )
        approval_record = approval_result.scalar_one_or_none()
        if approval_record is not None and isinstance(approval_record.payload, dict):
            approval = approval_record.payload

        remediation_action = {}
        action_result = await self.session.execute(
            select(ActionRecord)
            .where(
                ActionRecord.incident_id == UUID(incident_id_str),
                ActionRecord.tenant_id == normalized_tenant_id,
            )
            .order_by(ActionRecord.updated_at.desc(), ActionRecord.created_at.desc())
            .limit(1)
        )
        action_record = action_result.scalar_one_or_none()
        if action_record is not None and isinstance(action_record.payload, dict):
            remediation_action = action_record.payload

        closure_report = {}
        report_result = await self.session.execute(
            select(RcaReportRecord)
            .where(
                RcaReportRecord.incident_id == UUID(incident_id_str),
                RcaReportRecord.tenant_id == normalized_tenant_id,
            )
            .order_by(RcaReportRecord.updated_at.desc(), RcaReportRecord.created_at.desc())
            .limit(1)
        )
        report_record = report_result.scalar_one_or_none()
        if report_record is not None and isinstance(report_record.payload, dict):
            closure_report = report_record.payload

        closure_metadata = (
            closure_report.get("metadata")
            if isinstance(closure_report.get("metadata"), dict)
            else {}
        )
        processed_status = reduce_incident_status(
            projection_status=(bound_projection.status if bound_projection is not None else None),
            projection_updated_at=(bound_projection.updated_at if bound_projection is not None else None),
            canonical_status=incident_record.status,
            canonical_updated_at=incident_record.updated_at,
            approval_status=(approval_record.decision if approval_record is not None else None),
            approval_updated_at=(approval_record.updated_at if approval_record is not None else None),
            action_status=(action_record.status if action_record is not None else None),
            action_updated_at=(action_record.updated_at if action_record is not None else None),
            closure_kind=closure_metadata.get("closure_kind"),
        )
        incident_payload["status"] = processed_status["status"]
        incident_payload["status_source"] = processed_status["source"]
        incident_payload["status_reason"] = processed_status["reason"]

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
            .where(
                IncidentEventRecord.incident_id == UUID(incident_id_str),
                IncidentEventRecord.tenant_id == normalized_tenant_id,
            )
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

        # The recommendation's immutable snapshot binding is authoritative.  A
        # newer independently collected snapshot belongs to a later analysis
        # attempt and must never be substituted here.
        durable_context_snapshot = dict(
            bound_investigation.get("context_snapshot") or {}
        )
        context_payload: dict[str, Any] = (
            dict(durable_context_snapshot.get("context") or {})
            if isinstance(durable_context_snapshot, dict)
            and isinstance(durable_context_snapshot.get("context"), dict)
            else {}
        )
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
                for key, value in nested_context.items():
                    context_payload.setdefault(key, value)
            else:
                for key in ("deployment", "related_incidents", "dependency_services", "document_available"):
                    if context_event_payload.get(key) is not None:
                        context_payload.setdefault(key, context_event_payload.get(key))

        context_metadata = context_payload.get("metadata") if isinstance(context_payload.get("metadata"), dict) else {}
        if recommendation_metadata.get("rag_documents") is not None:
            context_metadata.setdefault("rag_documents", recommendation_metadata.get("rag_documents"))
        if isinstance(recommendation_metadata.get("rag_matches"), list):
            context_metadata.setdefault("rag_matches", recommendation_metadata.get("rag_matches"))
        if recommendation_metadata.get("rag_top_similarity") is not None:
            context_metadata.setdefault("rag_top_similarity", recommendation_metadata.get("rag_top_similarity"))
        if recommendation_metadata.get("rag_service_tagged_match") is not None:
            context_metadata.setdefault("rag_service_tagged_match", recommendation_metadata.get("rag_service_tagged_match"))
        if isinstance(recommendation_metadata.get("discovery_report"), dict):
            context_metadata.setdefault("discovery_report", recommendation_metadata.get("discovery_report"))
        if isinstance(recommendation_metadata.get("discovery_evidence"), dict):
            context_metadata.setdefault("discovery_evidence", recommendation_metadata.get("discovery_evidence"))
        if context_event_payload.get("document_available") is not None:
            context_metadata.setdefault("document_available", context_event_payload.get("document_available"))
        if isinstance(context_event_payload.get("discovery_report"), dict):
            context_metadata.setdefault("discovery_report", context_event_payload.get("discovery_report"))
        if isinstance(context_event_payload.get("discovery_evidence"), dict):
            context_metadata.setdefault("discovery_evidence", context_event_payload.get("discovery_evidence"))
        if isinstance(context_event_payload.get("context_sources"), dict):
            context_metadata.setdefault("context_sources", context_event_payload.get("context_sources"))
        if isinstance(context_event_payload.get("context_evidence"), dict):
            context_metadata.setdefault("context_evidence", context_event_payload.get("context_evidence"))
        if durable_context_snapshot:
            snapshot_provenance = {
                key: durable_context_snapshot.get(key)
                for key in (
                    "snapshot_id",
                    "source_incident_id",
                    "context_fingerprint",
                    "contract_version",
                    "quality_score",
                    "reusable",
                    "source_manifest",
                    "collected_at",
                    "expires_at",
                )
            }
            context_metadata.setdefault("snapshot", snapshot_provenance)
            context_payload.setdefault("snapshot", snapshot_provenance)

        has_discovery_report = isinstance(context_metadata.get("discovery_report"), dict) and bool(context_metadata.get("discovery_report"))
        has_discovery_evidence = isinstance(context_metadata.get("discovery_evidence"), dict) and bool(context_metadata.get("discovery_evidence"))
        # Never manufacture completed Context/Discovery data from alert text. If
        # Context did not emit a persisted event, return an empty stage so the UI
        # accurately reports that downstream processing has not occurred.
        if context_event_payload and not (has_discovery_report and has_discovery_evidence):
            alert_tokens = {_normalize_match_token(item) for item in _collect_alert_application_tokens(alert_payload)}

            app_result = await self.session.execute(
                select(ApplicationRecord)
                .where(ApplicationRecord.tenant_id == normalized_tenant_id)
                .order_by(ApplicationRecord.updated_at.desc())
                .limit(500)
            )
            matched_application_payload: dict[str, Any] = {}
            for app_row in app_result.scalars().all():
                app_name = str(getattr(app_row, "name", "") or "").strip()
                app_namespace = str(getattr(app_row, "namespace", "") or "").strip()
                app_tokens = {_normalize_match_token(app_name), _normalize_match_token(app_namespace)}
                if not (alert_tokens & {token for token in app_tokens if token}):
                    continue
                matched_application_payload = app_row.payload if isinstance(app_row.payload, dict) else {}
                break

            onboarding_result = await self.session.execute(
                select(OnboardingStateRecord)
                .where(OnboardingStateRecord.tenant_id == normalized_tenant_id)
                .order_by(OnboardingStateRecord.updated_at.desc())
                .limit(500)
            )
            matched_onboarding_rows: list[OnboardingStateRecord] = []
            for onboarding_row in onboarding_result.scalars().all():
                project_token = _normalize_match_token(getattr(onboarding_row, "project_name", ""))
                if project_token and project_token in alert_tokens:
                    matched_onboarding_rows.append(onboarding_row)

            rag_documents = context_metadata.get("rag_documents") if isinstance(context_metadata.get("rag_documents"), list) else []
            discovery_report, discovery_evidence = _build_discovery_contract(
                alert_payload=alert_payload,
                recommendation=recommendation,
                recommendation_metadata=recommendation_metadata,
                matched_application_payload=matched_application_payload,
                onboarding_rows=matched_onboarding_rows,
                existing_rag_documents=rag_documents,
            )
            context_metadata.setdefault("discovery_report", discovery_report)
            context_metadata.setdefault("discovery_evidence", discovery_evidence)
            recommendation_metadata.setdefault("discovery_report", discovery_report)
            recommendation_metadata.setdefault("discovery_evidence", discovery_evidence)

        if context_metadata:
            context_payload["metadata"] = context_metadata
        if recommendation_metadata:
            recommendation["metadata"] = recommendation_metadata
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

        observed_transport_provider = next(
            (
                str(item.get("transport_provider") or "").strip()
                for item in reversed(event_trace)
                if str(item.get("transport_provider") or "").strip().lower() not in {"", "unknown"}
            ),
            "",
        )
        observed_workflow = next(
            (
                str(item.get("payload", {}).get("decision", {}).get("workflow") or "").strip()
                for item in reversed(event_trace)
                if isinstance(item.get("payload"), dict)
                and isinstance(item.get("payload", {}).get("decision"), dict)
                and str(item.get("payload", {}).get("decision", {}).get("workflow") or "").strip()
            ),
            "",
        )
        decision_workflow = str(orchestration_decision.get("workflow") or observed_workflow or "guided-remediation")
        decision_message_bus_provider = str(
            orchestration_decision.get("message_bus_provider")
            or observed_transport_provider
            or "rabbitmq"
        )

        scenario = {
            "id": "db-processed",
            "title": str(incident_payload.get("title") or alert_payload.get("name") or "Incident"),
            "recommended_action": str(recommendation.get("recommended_action") or ""),
        }

        lifecycle_candidates = (
            closure_report.get("metadata", {}).get("resolution_lifecycle") if isinstance(closure_report.get("metadata"), dict) else None,
            remediation_action.get("parameters", {}).get("resolution_lifecycle") if isinstance(remediation_action.get("parameters"), dict) else None,
            remediation_action.get("metadata", {}).get("resolution_lifecycle") if isinstance(remediation_action.get("metadata"), dict) else None,
            recommendation.get("metadata", {}).get("resolution_lifecycle") if isinstance(recommendation.get("metadata"), dict) else None,
            incident_payload.get("metadata", {}).get("resolution_lifecycle") if isinstance(incident_payload.get("metadata"), dict) else None,
        )
        resolution_lifecycle = select_current_lifecycle(
            *({"resolution_lifecycle": item} for item in lifecycle_candidates if isinstance(item, dict))
        )
        incident_investigation: dict[str, Any] | None = None
        if investigation_integrity.get("verified") is True:
            try:
                incident_investigation = self.build_incident_investigation_contract(
                    tenant_id=normalized_tenant_id,
                    project_id=str(
                        incident_payload.get("project_id")
                        or alert_payload.get("project_id")
                        or alert_labels.get("project_id")
                        or "default"
                    ),
                    incident_id=incident_record.id,
                    alert_id=alert_uuid,
                    recommendation=recommendation,
                    context_snapshot=durable_context_snapshot,
                    approval=approval,
                    remediation_action=remediation_action,
                    validation_status=str(closure_report.get("status") or "pending"),
                )
            except ValueError as exc:
                investigation_integrity = {
                    **investigation_integrity,
                    "status": "contract_invalid",
                    "verified": False,
                    "blocking_reasons": [
                        "bound investigation does not satisfy the canonical runtime contract",
                        str(exc)[:1000],
                    ],
                }

        return {
            "mode": "db-processed",
            "scenario": scenario,
            "alert": alert_payload,
            "incident": incident_payload,
            "decision": {
                "workflow": decision_workflow,
                "requires_approval": bool(orchestration_decision.get("requires_approval", False)),
                "risk_tier": str(orchestration_decision.get("risk_tier") or "unknown"),
                "execution_mode": str(orchestration_decision.get("execution_mode") or "unknown"),
                "policy_version": str(orchestration_decision.get("policy_version") or "policy-v1"),
                "policy_reason": str(orchestration_decision.get("policy_reason") or ""),
                "message_bus_provider": decision_message_bus_provider,
                "stream_count": int(orchestration_decision.get("stream_count", 0) or 0),
                "stream_threshold": int(orchestration_decision.get("stream_threshold", 0) or 0),
                "planner_used": False,
                "planner_model": None,
                "planner_reason": "db-processed historical result",
            },
            "context": context_payload,
            "recommendation": recommendation,
            "incident_investigation": incident_investigation,
            "investigation_integrity": investigation_integrity,
            "approval": approval,
            "remediation_action": remediation_action,
            "closure_report": closure_report,
            "resolution_lifecycle": resolution_lifecycle,
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

    async def get_incident_stage_completeness(
        self,
        incident_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        incident_uuid = self._parse_uuid(incident_id)
        if incident_uuid is None:
            return None
        normalized_tenant_id = self._require("tenant_id", tenant_id)

        incident_result = await self.session.execute(
            select(IncidentRecord).where(
                IncidentRecord.id == incident_uuid,
                IncidentRecord.tenant_id == normalized_tenant_id,
            )
        )
        incident_record = incident_result.scalar_one_or_none()
        if incident_record is None:
            return None

        events_result = await self.session.execute(
            select(
                IncidentEventRecord.event_type,
                IncidentEventRecord.status,
                IncidentEventRecord.created_at,
            )
            .where(
                IncidentEventRecord.incident_id == incident_uuid,
                IncidentEventRecord.tenant_id == normalized_tenant_id,
            )
            .order_by(IncidentEventRecord.created_at.asc())
        )
        event_rows = events_result.all()
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
            select(ApprovalRecord)
            .where(
                ApprovalRecord.incident_id == incident_uuid,
                ApprovalRecord.tenant_id == normalized_tenant_id,
            )
            .order_by(ApprovalRecord.updated_at.desc(), ApprovalRecord.created_at.desc())
        )
        approval_rows = approval_result.scalars().all()

        action_result = await self.session.execute(
            select(ActionRecord)
            .where(
                ActionRecord.incident_id == incident_uuid,
                ActionRecord.tenant_id == normalized_tenant_id,
            )
            .order_by(ActionRecord.updated_at.desc(), ActionRecord.created_at.desc())
        )
        action_rows = action_result.scalars().all()

        report_result = await self.session.execute(
            select(RcaReportRecord).where(
                RcaReportRecord.incident_id == incident_uuid,
                RcaReportRecord.tenant_id == normalized_tenant_id,
            )
        )
        report_rows = report_result.scalars().all()
        report_closure_kinds = {
            str(
                (
                    (report.payload or {}).get("metadata")
                    if isinstance((report.payload or {}).get("metadata"), dict)
                    else {}
                ).get("closure_kind")
                or ""
            ).strip().lower()
            for report in report_rows
        }
        closure_kind = (
            "manual"
            if "manual" in report_closure_kinds
            else "diagnostic"
            if "diagnostic" in report_closure_kinds
            else ""
        )
        projection_result = await self.session.execute(
            select(IncidentProjectionRecord).where(
                IncidentProjectionRecord.incident_id == incident_uuid,
                IncidentProjectionRecord.tenant_id == normalized_tenant_id,
            )
        )
        projection_record = projection_result.scalar_one_or_none()
        current_recommendation_id = (
            projection_record.recommendation_id if projection_record is not None else None
        )
        current_approval_rows = [
            approval for approval in approval_rows
            if current_recommendation_id is None
            or approval.recommendation_id == current_recommendation_id
        ]
        latest_approval = approval_rows[0] if approval_rows else None
        latest_action = action_rows[0] if action_rows else None
        lifecycle_status = reduce_incident_status(
            projection_status=projection_record.status if projection_record is not None else None,
            projection_updated_at=projection_record.updated_at if projection_record is not None else None,
            canonical_status=incident_record.status,
            canonical_updated_at=incident_record.updated_at,
            approval_status=latest_approval.decision if latest_approval is not None else None,
            approval_updated_at=latest_approval.updated_at if latest_approval is not None else None,
            action_status=latest_action.status if latest_action is not None else None,
            action_updated_at=latest_action.updated_at if latest_action is not None else None,
            closure_kind=closure_kind,
        )
        incident_status = lifecycle_status["status"]

        stage_matrix = [
            {
                "stage": "alert_enriched",
                "label": "Alert Intelligence Agent",
                "event_types": ["incident.alert.enriched"],
                "next_action": "Enrich and persist the normalized alert.",
            },
            {
                "stage": "workflow_selected",
                "label": "Orchestrator Agent",
                "event_types": ["incident.workflow.selected"],
                "next_action": "Select and persist the incident workflow.",
            },
            {
                "stage": "context_collected",
                "label": "Context Intelligence Agent",
                "event_types": ["incident.context.collected"],
                "next_action": "Collect logs, metrics, traces, tickets, and dependency context.",
            },
            {
                "stage": "recommendation_generated",
                "label": "Resolution Intelligence Agent",
                "event_types": ["incident.recommendation.generated"],
                "next_action": "Generate and persist an evidence-grounded recommendation.",
            },
            {
                "stage": "approval_recorded",
                "label": "Human Approval Layer",
                "event_types": ["incident.approval.recorded", "incident.approval.requested"],
                "next_action": "Record an authorized operator decision.",
            },
            {
                "stage": "remediation_executed",
                "label": "Remediation Automation Engine",
                "event_types": ["incident.remediation.executed"],
                "next_action": "Execute or explicitly skip the approved remediation plan.",
            },
            {
                "stage": "closure_completed",
                "label": "Closure & Validation",
                "event_types": ["incident.closure.completed", "incident.closed"],
                "next_action": "Validate recovery and close or escalate the incident.",
            },
        ]
        diagnostic_completion = any(
            str(action.action_type or "").strip().lower() == "diagnostic_completion"
            and str(action.status or "").strip().lower() == "skipped"
            and bool(((action.payload or {}).get("parameters") or {}).get("diagnostic_closure"))
            for action in action_rows
        )
        manual_closure = closure_kind == "manual"
        if diagnostic_completion:
            # Approval is not part of a non-mutating diagnostic branch. Count
            # the lifecycle that actually ran instead of reporting a permanent
            # missing approval after the incident was correctly auto-closed.
            stage_matrix = [row for row in stage_matrix if row["stage"] != "approval_recorded"]
        elif manual_closure:
            # Administrative closure is a separate governed terminal branch.
            # Approval and remediation were never required or executed, so do
            # not report those inapplicable phases as missing work.
            stage_matrix = [
                row
                for row in stage_matrix
                if row["stage"] not in {"approval_recorded", "remediation_executed"}
            ]

        stages = []
        for row in stage_matrix:
            matched = [event_type for event_type in row["event_types"] if event_type in event_types]
            persisted = bool(matched)
            evidence_sources = [f"event:{event_type}" for event_type in matched]
            state = "complete" if persisted else "waiting"

            if row["stage"] == "approval_recorded":
                # Approval is immutable authorization for one recommendation
                # version. Historical approval events must not make a newly
                # regenerated plan appear approved.
                persisted = bool(current_approval_rows)
                matched = matched if persisted else []
                evidence_sources = (
                    ["relational:approvals/current-recommendation"] if persisted else []
                )
                state = "complete" if persisted else "waiting"

            # Use persisted relational evidence to avoid under-reporting when some
            # services emit equivalent terminal states under different event names.
            if row["stage"] == "alert_enriched" and not persisted:
                persisted = len(work_rows) > 0 or len(event_rows) > 0
                if persisted:
                    evidence_sources.append("relational:incident_events")
            elif row["stage"] == "context_collected" and not persisted:
                context_work = [work for work in work_rows if
                    str(work.agent_name or "").strip().lower() in {"context intelligence agent", "context-agent"}
                ]
                persisted = any(
                    str(work.status or "").strip().lower() in {"completed", "complete", "succeeded", "success"}
                    for work in context_work
                )
                if persisted:
                    evidence_sources.append("relational:agent_work_items/context-completed")
                elif context_work:
                    state = "in_progress"
                    evidence_sources.append("relational:agent_work_items/context-started")
            elif row["stage"] == "approval_recorded" and not persisted:
                persisted = False
            elif row["stage"] == "remediation_executed" and not persisted:
                policy_blocked_actions = [
                    action
                    for action in action_rows
                    if str(action.action_type or "").strip().lower() == "policy-blocked"
                    or bool(((action.payload or {}).get("metadata") or {}).get("policy_blocked"))
                ]
                terminal_actions = [
                    action
                    for action in action_rows
                    if action not in policy_blocked_actions
                    and str(action.status or "").strip().lower() in {"succeeded", "failed", "skipped"}
                ]
                persisted = bool(terminal_actions)
                if persisted:
                    evidence_sources.extend(f"relational:actions/{str(action.status or '').strip().lower()}" for action in terminal_actions)
                elif policy_blocked_actions:
                    state = "blocked"
                    evidence_sources.append("relational:actions/policy-blocked")
                    row = {
                        **row,
                        "next_action": "Review the policy reason, select a matching runbook, and record operator approval before execution.",
                    }
                elif action_rows or "remediating" in event_statuses:
                    state = "in_progress"
                    evidence_sources.append("relational:actions/in-progress")
            elif row["stage"] == "closure_completed" and not persisted:
                persisted = incident_status in {"closed", "resolved"}
                if persisted:
                    evidence_sources.append(f"relational:incidents/status={incident_status}")

            if persisted:
                state = "complete"

            stages.append(
                {
                    "stage": row["stage"],
                    "label": row["label"],
                    "persisted": persisted,
                    "matched_event_types": matched,
                    "evidence_sources": sorted(set(evidence_sources)),
                    "state": state,
                    "next_action": "Completed." if persisted else row["next_action"],
                }
            )

        completed = len([row for row in stages if row["persisted"]])
        total = len(stages)
        missing = [row["stage"] for row in stages if not row["persisted"]]
        latest_event_at = event_rows[-1].created_at if event_rows else None

        return {
            "incident_id": str(incident_record.id),
            "status": incident_status,
            "status_source": lifecycle_status["source"],
            "status_reason": lifecycle_status["reason"],
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

    async def acquire_canonical_incident(
        self,
        *,
        incident: Incident,
        occurrence_id: UUID,
        correlation_key: str,
        project_id: str,
        idempotency_key: str,
        causation_id: str | None = None,
        correlation_window_minutes: int = 60,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically acquire bounded correlation ownership and attach an occurrence."""
        tenant_id = self._require("tenant_id", incident.tenant_id)
        project_id = self._require("project_id", project_id)
        environment = self._require("environment", incident.environment)
        service = self._require("service", incident.service)
        correlation_key = self._require("correlation_key", correlation_key)
        idempotency_key = self._require("idempotency_key", idempotency_key)
        now = observed_at or datetime.now(UTC)
        window = timedelta(minutes=max(1, min(int(correlation_window_minutes), 1440)))

        existing_occurrence = (
            await self.session.execute(
                select(IncidentOccurrenceRecord).where(
                    IncidentOccurrenceRecord.tenant_id == tenant_id,
                    IncidentOccurrenceRecord.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing_occurrence is not None:
            return {
                "canonical_incident_id": existing_occurrence.canonical_incident_id,
                "correlation_family_id": existing_occurrence.correlation_family_id,
                "correlation_generation": existing_occurrence.correlation_generation,
                "created": False,
                "retried": True,
            }

        scope = (
            IncidentCorrelationOwnershipRecord.tenant_id == tenant_id,
            IncidentCorrelationOwnershipRecord.project_id == project_id,
            IncidentCorrelationOwnershipRecord.environment == environment,
            IncidentCorrelationOwnershipRecord.service == service,
            IncidentCorrelationOwnershipRecord.correlation_key == correlation_key,
        )
        ownership = (
            await self.session.execute(
                select(IncidentCorrelationOwnershipRecord)
                .where(*scope)
                .order_by(IncidentCorrelationOwnershipRecord.correlation_generation.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        terminal = {"closed", "resolved", "cancelled", "canceled"}
        ownership_expiry = ownership.correlation_window_expires_at if ownership is not None else None
        if ownership_expiry is not None and ownership_expiry.tzinfo is None:
            ownership_expiry = ownership_expiry.replace(tzinfo=UTC)
        ownership_last_seen = ownership.last_seen_at if ownership is not None else None
        if ownership_last_seen is not None and ownership_last_seen.tzinfo is None:
            ownership_last_seen = ownership_last_seen.replace(tzinfo=UTC)
        historical_event = ownership_last_seen is not None and now <= ownership_last_seen
        create_generation = (
            ownership is None
            or (
                not historical_event
                and (
                    str(ownership.lifecycle_state or "").lower() in terminal
                    or ownership_expiry < now
                )
            )
        )
        created = False
        if create_generation:
            generation = 1 if ownership is None else int(ownership.correlation_generation) + 1
            family_id = ownership.correlation_family_id if ownership is not None else uuid5(
                NAMESPACE_URL, f"kaims-correlation:{tenant_id}:{project_id}:{environment}:{service}:{correlation_key}"
            )
            candidate_values = dict(
                id=uuid4(),
                tenant_id=tenant_id,
                project_id=project_id,
                environment=environment,
                service=service,
                correlation_key=correlation_key,
                correlation_family_id=family_id,
                correlation_generation=generation,
                canonical_incident_id=incident.id,
                first_seen_at=now,
                last_seen_at=now,
                correlation_window_expires_at=now + window,
                lifecycle_state=incident.status.value,
                version=1,
                created_at=now,
                updated_at=now,
            )
            dialect_name = self.session.get_bind().dialect.name
            if dialect_name == "mysql":
                statement = mysql_insert(IncidentCorrelationOwnershipRecord).values(**candidate_values)
                statement = statement.on_duplicate_key_update(
                    id=IncidentCorrelationOwnershipRecord.id
                )
                await self.session.execute(statement)
            elif dialect_name == "sqlite":
                statement = sqlite_insert(IncidentCorrelationOwnershipRecord).values(**candidate_values)
                statement = statement.on_conflict_do_nothing(
                    index_elements=[
                        "tenant_id", "project_id", "environment", "service",
                        "correlation_key", "correlation_generation",
                    ]
                )
                await self.session.execute(statement)
            else:
                async with self.session.begin_nested():
                    self.session.add(IncidentCorrelationOwnershipRecord(**candidate_values))
                    await self.session.flush()
            ownership = (
                await self.session.execute(
                    select(IncidentCorrelationOwnershipRecord)
                    .where(*scope)
                    .order_by(IncidentCorrelationOwnershipRecord.correlation_generation.desc())
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one()
            created = ownership.canonical_incident_id == incident.id
        else:
            last_seen = ownership.last_seen_at
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
            ownership.last_seen_at = max(last_seen, now)
            ownership.version = int(ownership.version or 1) + 1

        occurrence = IncidentOccurrenceRecord(
            tenant_id=tenant_id,
            project_id=project_id,
            environment=environment,
            service=service,
            correlation_family_id=ownership.correlation_family_id,
            correlation_generation=ownership.correlation_generation,
            canonical_incident_id=ownership.canonical_incident_id,
            occurrence_id=occurrence_id,
            idempotency_key=idempotency_key,
            causation_id=causation_id,
            observed_at=now,
            payload={"incoming_incident_id": str(incident.id), "correlation_key": correlation_key},
        )
        try:
            async with self.session.begin_nested():
                self.session.add(occurrence)
                await self.session.flush()
        except IntegrityError:
            existing_occurrence = (
                await self.session.execute(
                    select(IncidentOccurrenceRecord).where(
                        IncidentOccurrenceRecord.tenant_id == tenant_id,
                        IncidentOccurrenceRecord.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one()
            ownership = (
                await self.session.execute(
                    select(IncidentCorrelationOwnershipRecord).where(
                        IncidentCorrelationOwnershipRecord.correlation_family_id
                        == existing_occurrence.correlation_family_id,
                        IncidentCorrelationOwnershipRecord.correlation_generation
                        == existing_occurrence.correlation_generation,
                    )
                )
            ).scalar_one()
            created = False
        return {
            "canonical_incident_id": ownership.canonical_incident_id,
            "correlation_family_id": ownership.correlation_family_id,
            "correlation_generation": ownership.correlation_generation,
            "created": created,
            "retried": False,
        }

    async def save_incident(self, incident: Incident) -> None:
        incident_id = self._require("incident.id", incident.id)
        incoming_status = self._require("incident.status", incident.status.value)
        existing = await self.session.get(IncidentRecord, incident_id)
        if (
            existing is not None
            and str(existing.status or "").strip().lower() in _CLOSED_INCIDENT_STATUSES
            and str(incoming_status).strip().lower() not in _CLOSED_INCIDENT_STATUSES
        ):
            # Delayed alert/Jira messages can arrive after closure and still
            # carry the pre-closure Incident object. They may enrich identity,
            # but they must never reopen a terminal incident implicitly.
            stored_payload = dict(existing.payload or {})
            incoming_payload = incident.model_dump(mode="json")
            if not existing.ticket_id and incident.ticket_id:
                existing.ticket_id = incident.ticket_id
                stored_payload["ticket_id"] = incident.ticket_id
            stored_alert_ids = [str(item) for item in stored_payload.get("alert_ids", []) if str(item).strip()]
            incoming_alert_ids = [str(item) for item in incoming_payload.get("alert_ids", []) if str(item).strip()]
            if incoming_alert_ids:
                stored_payload["alert_ids"] = list(dict.fromkeys([*stored_alert_ids, *incoming_alert_ids]))
            stored_payload["status"] = existing.status
            stored_payload["state"] = existing.status
            existing.payload = stored_payload
            await self.session.merge(existing)
            return
        await self.session.merge(
            IncidentRecord(
                id=incident_id,
                tenant_id=incident.tenant_id or "default",
                service=self._require("incident.service", incident.service),
                environment=self._require("incident.environment", incident.environment),
                severity=self._require("incident.severity", incident.severity.value),
                status=incoming_status,
                title=self._require("incident.title", incident.title),
                ticket_id=incident.ticket_id,
                payload=incident.model_dump(mode="json"),
            )
        )
        ownership_rows = (
            await self.session.execute(
                select(IncidentCorrelationOwnershipRecord).where(
                    IncidentCorrelationOwnershipRecord.canonical_incident_id == incident_id,
                    IncidentCorrelationOwnershipRecord.tenant_id == (incident.tenant_id or "default"),
                )
            )
        ).scalars().all()
        for ownership in ownership_rows:
            ownership.lifecycle_state = incoming_status
            ownership.version = int(ownership.version or 1) + 1

    async def get_incident(self, incident_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        incident_uuid = self._parse_uuid(incident_id)
        if incident_uuid is None:
            return None
        query = select(IncidentRecord).where(IncidentRecord.id == incident_uuid)
        if tenant_id is not None:
            query = query.where(IncidentRecord.tenant_id == self._require("tenant_id", tenant_id))
        result = await self.session.execute(query)
        record = result.scalar_one_or_none()
        return record.payload if record else None

    async def find_open_jira_by_correlation_key(
        self,
        correlation_key: str,
        *,
        tenant_id: str,
        project_id: str,
        environment: str,
        service: str,
    ) -> str | None:
        """Resolve a previously qualified Jira incident for a correlated signal."""
        required_scope = (tenant_id, project_id, environment, service, correlation_key)
        if any(not str(value or "").strip() for value in required_scope):
            return None
        incident = await self.find_open_incident_by_correlation_key(
            correlation_key,
            tenant_id=tenant_id,
            project_id=project_id,
            environment=environment,
            service=service,
        )
        if not incident:
            return None
        metadata = incident.get("metadata") if isinstance(incident.get("metadata"), dict) else {}
        candidate = metadata.get("incident_candidate") if isinstance(metadata.get("incident_candidate"), dict) else {}
        return str(incident.get("ticket_id") or candidate.get("jira_key") or "").strip() or None

    async def find_open_incident_by_correlation_key(
        self,
        correlation_key: str,
        *,
        tenant_id: str = "default",
        project_id: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> dict[str, Any] | None:
        """Resolve indexed canonical ownership without inspecting JSON payloads."""
        normalized = str(correlation_key or "").strip()
        if not normalized:
            return None
        ownership_query = select(IncidentCorrelationOwnershipRecord).where(
            IncidentCorrelationOwnershipRecord.tenant_id == tenant_id,
            IncidentCorrelationOwnershipRecord.correlation_key == normalized,
            IncidentCorrelationOwnershipRecord.lifecycle_state.not_in(
                ("closed", "resolved", "cancelled", "canceled")
            ),
        )
        if project_id:
            ownership_query = ownership_query.where(IncidentCorrelationOwnershipRecord.project_id == project_id)
        if environment:
            ownership_query = ownership_query.where(IncidentCorrelationOwnershipRecord.environment == environment)
        if service:
            ownership_query = ownership_query.where(IncidentCorrelationOwnershipRecord.service == service)
        ownership = (
            await self.session.execute(
                ownership_query.order_by(
                    IncidentCorrelationOwnershipRecord.last_seen_at.desc(),
                    IncidentCorrelationOwnershipRecord.correlation_generation.desc(),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if ownership is None:
            return None
        record = await self.session.get(IncidentRecord, ownership.canonical_incident_id)
        return record.payload if record is not None else None

    async def list_unresolved_incident_family(
        self,
        *,
        incident_id: str,
        service: str,
        environment: str,
        category: str,
        tenant_id: str = "default",
        limit: int = 100,
        window_minutes: int = 60,
    ) -> list[dict[str, Any]]:
        """Find unresolved members of the same operational symptom family."""
        from common.incident_identity import same_environment_family

        current_id = self._parse_uuid(incident_id)
        current_record = await self.session.get(IncidentRecord, current_id) if current_id is not None else None
        if current_record is None:
            return []
        family_cutoff = current_record.created_at - timedelta(minutes=max(1, min(int(window_minutes), 1440)))
        query = (
            select(IncidentRecord)
            .where(IncidentRecord.tenant_id == tenant_id)
            .where(IncidentRecord.service == self._require("service", service))
            .where(IncidentRecord.status.not_in(("closed", "resolved", "cancelled", "canceled")))
            .where(IncidentRecord.created_at >= family_cutoff)
            .where(IncidentRecord.created_at <= current_record.created_at)
            .order_by(IncidentRecord.created_at.desc())
            .limit(max(1, min(int(limit), 500)))
        )
        result = await self.session.execute(query)
        related: list[dict[str, Any]] = []
        normalized_category = str(category or "unknown").strip().lower()
        for record in result.scalars().all():
            if current_id is not None and record.id == current_id:
                continue
            payload = record.payload if isinstance(record.payload, dict) else {}
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            candidate = metadata.get("incident_candidate") if isinstance(metadata.get("incident_candidate"), dict) else {}
            candidate_category = str(candidate.get("category") or "unknown").strip().lower()
            if candidate_category != normalized_category:
                continue
            if not same_environment_family(environment, payload.get("environment") or record.environment):
                continue
            related.append(payload)
        return related

    async def get_latest_recommendation_for_incident(
        self,
        incident_id: Any,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
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
        if tenant_id is not None:
            audit_stmt = audit_stmt.where(AuditLogRecord.tenant_id == self._require("tenant_id", tenant_id))
        audit_result = await self.session.execute(audit_stmt)
        audit_record = audit_result.scalar_one_or_none()
        if audit_record is not None and isinstance(audit_record.payload, dict):
            return audit_record.payload

        projection_stmt = select(IncidentProjectionRecord).where(
            IncidentProjectionRecord.incident_id == incident_uuid
        )
        if tenant_id is not None:
            projection_stmt = projection_stmt.where(
                IncidentProjectionRecord.tenant_id == self._require("tenant_id", tenant_id)
            )
        projection_result = await self.session.execute(projection_stmt)
        projection = projection_result.scalar_one_or_none()
        if projection is not None and projection.recommendation_id is not None:
            return {"id": str(projection.recommendation_id), "incident_id": str(incident_uuid)}
        return None

    async def save_approval(self, approval: Approval) -> None:
        await self.session.merge(
            ApprovalRecord(
                id=self._require("approval.id", approval.id),
                tenant_id=self._require("approval.tenant_id", approval.tenant_id),
                incident_id=self._require("approval.incident_id", approval.incident_id),
                recommendation_id=self._require("approval.recommendation_id", approval.recommendation_id),
                plan_id=approval.plan_id,
                plan_fingerprint=approval.plan_fingerprint,
                approval_expires_at=approval.approval_expires_at,
                approver_role=approval.approver_role,
                decision=self._require("approval.decision", approval.decision.value),
                approver=approval.approver,
                payload=approval.model_dump(mode="json"),
            )
        )

    async def has_accepted_approval(
        self,
        incident_id: Any,
        recommendation_id: Any,
        *,
        tenant_id: str = "default",
    ) -> bool:
        incident_uuid = self._parse_uuid(incident_id)
        recommendation_uuid = self._parse_uuid(recommendation_id)
        if incident_uuid is None or recommendation_uuid is None:
            return False
        result = await self.session.execute(
            select(ApprovalRecord.id)
            .where(ApprovalRecord.tenant_id == (str(tenant_id or "default").strip() or "default"))
            .where(ApprovalRecord.incident_id == incident_uuid)
            .where(ApprovalRecord.recommendation_id == recommendation_uuid)
            .where(ApprovalRecord.decision == ApprovalDecision.APPROVED.value)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def has_accepted_approval_id(
        self,
        approval_id: Any,
        incident_id: Any,
        recommendation_id: Any,
        *,
        tenant_id: str,
        plan_id: Any,
        plan_fingerprint: str,
    ) -> bool:
        approval_uuid = self._parse_uuid(approval_id)
        incident_uuid = self._parse_uuid(incident_id)
        recommendation_uuid = self._parse_uuid(recommendation_id)
        if approval_uuid is None or incident_uuid is None or recommendation_uuid is None:
            return False
        normalized_tenant = str(tenant_id or "").strip()
        if not normalized_tenant or normalized_tenant.lower() == "default" or not plan_fingerprint:
            return False
        result = await self.session.execute(
            select(ApprovalRecord)
            .where(ApprovalRecord.id == approval_uuid)
            .where(ApprovalRecord.tenant_id == normalized_tenant)
            .where(ApprovalRecord.incident_id == incident_uuid)
            .where(ApprovalRecord.recommendation_id == recommendation_uuid)
            .where(ApprovalRecord.decision == ApprovalDecision.APPROVED.value)
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None or not isinstance(record.payload, dict):
            return False
        expires_at = record.approval_expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return (
            str(record.plan_id or record.payload.get("plan_id") or "") == str(plan_id or "")
            and str(record.plan_fingerprint or record.payload.get("plan_fingerprint") or "") == plan_fingerprint
            and str(record.payload.get("tenant_id") or "") == normalized_tenant
            and str(record.payload.get("authorization_scope") or "execution") == "execution"
            and expires_at is not None
            and expires_at > datetime.now(UTC)
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
        action_status = self._require("action.status", action.status.value)
        await self.session.merge(
            ActionRecord(
                id=self._require("action.id", action.id),
                tenant_id=action.tenant_id or "default",
                incident_id=self._require("action.incident_id", action.incident_id),
                action_type=self._require("action.action_type", action.action_type),
                target=self._require("action.target", action.target),
                idempotency_key=action.idempotency_key,
                status=action_status,
                payload=action.model_dump(mode="json"),
            )
        )
        # Keep the incident read model synchronized with the durable action.
        # Action persistence is the lifecycle source of truth; relying only on
        # asynchronous events leaves incidents permanently "remediating" when
        # a consumer is restarted or an older producer omits a terminal event.
        incident_status = {
            "pending": "remediating",
            "policy_checked": "remediating",
            "approved": "remediating",
            "dispatching": "remediating",
            "running": "remediating",
            "succeeded": "validating",
            "failed": "failed",
            "skipped": "failed",
            "execution_failed": "failed",
            "validation_failed": "failed",
            "dispatch_failed": "failed",
            "policy_blocked": "awaiting_approval",
            "awaiting_approval": "awaiting_approval",
            "rollback_failed": "failed",
            "timed_out": "failed",
            "cancelled": "failed",
            "manual_intervention_required": "failed",
            "rolled_back": "validating",
        }.get(str(action_status).lower())
        if action_status == "skipped" and action.action_type == "diagnostic_completion":
            incident_status = "validating"
        if (
            action_status == "skipped"
            and str(action.action_type or "").strip().lower().replace("_", "-") == "policy-blocked"
        ):
            # Policy enforcement succeeded: execution did not fail. Keep the
            # incident in investigation so the operator can collect evidence
            # or regenerate a safe plan instead of presenting false recovery
            # failure semantics.
            incident_status = "investigating"
        if incident_status:
            projection = await self.session.get(IncidentProjectionRecord, action.incident_id)
            if (
                projection is not None
                and str(projection.status or "").strip().lower() not in _CLOSED_INCIDENT_STATUSES
            ):
                now = utc_now()
                projection.status = incident_status
                projection.latest_event_type = "incident.remediation.status"
                projection.latest_event_at = now
                projection.updated_at = now
                payload = dict(projection.projection_payload or {})
                payload["status"] = incident_status
                payload["state"] = incident_status
                payload["remediation_status"] = action_status
                payload["remediation_action"] = action.model_dump(mode="json")
                projection.projection_payload = payload
                await self.session.merge(projection)

    async def enqueue_resolution_event(
        self,
        *,
        event_id: str,
        aggregate_id: str,
        topic: str,
        partition_key: str,
        payload: dict[str, Any],
        tenant_id: str = "default",
        available_after_seconds: float = 60.0,
    ) -> bool:
        normalized_event_id = self._require("outbox.event_id", event_id)
        if await self.session.get(ResolutionOutboxRecord, normalized_event_id) is not None:
            return False
        self.session.add(
            ResolutionOutboxRecord(
                event_id=normalized_event_id,
                tenant_id=tenant_id or "default",
                aggregate_id=self._require("outbox.aggregate_id", aggregate_id),
                topic=self._require("outbox.topic", topic),
                partition_key=self._require("outbox.partition_key", partition_key),
                payload=payload,
                status="pending",
                attempts=0,
                next_attempt_at=utc_now() + timedelta(seconds=max(0.0, float(available_after_seconds))),
            )
        )
        return True

    async def list_pending_resolution_events(self, *, limit: int = 100) -> list[ResolutionOutboxRecord]:
        rows = await self.session.execute(
            select(ResolutionOutboxRecord)
            .where(
                ResolutionOutboxRecord.published_at.is_(None),
                ResolutionOutboxRecord.status.in_(("pending", "retry")),
                ResolutionOutboxRecord.next_attempt_at <= utc_now(),
            )
            .order_by(ResolutionOutboxRecord.created_at.asc())
            .limit(max(1, min(int(limit), 1000)))
        )
        return list(rows.scalars().all())

    async def mark_resolution_event_published(self, event_id: str) -> None:
        row = await self.session.get(ResolutionOutboxRecord, event_id)
        if row is None:
            return
        row.status = "published"
        row.published_at = utc_now()
        row.last_error = None
        row.attempts = int(row.attempts or 0) + 1
        await self.session.merge(row)

    async def mark_resolution_event_retry(self, event_id: str, error: str) -> None:
        row = await self.session.get(ResolutionOutboxRecord, event_id)
        if row is None:
            return
        attempts = int(row.attempts or 0) + 1
        row.status = "retry"
        row.attempts = attempts
        row.last_error = str(error)[:4000]
        row.next_attempt_at = utc_now() + timedelta(seconds=min(300, 2 ** min(attempts, 8)))
        await self.session.merge(row)

    async def find_action_by_idempotency_key(self, idempotency_key: str) -> RemediationAction | None:
        """Look up a previously-persisted action by its deterministic idempotency key.

        Used by remediation-engine to detect a redelivered approval/resolution
        message and skip re-running a remediation plugin that already executed.
        """
        if not idempotency_key:
            return None
        result = await self.session.execute(
            select(ActionRecord).where(ActionRecord.idempotency_key == idempotency_key).limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return RemediationAction.model_validate(record.payload)

    async def find_latest_action_by_incident(self, incident_id: UUID) -> RemediationAction | None:
        """Return authoritative execution state for UI/status polling."""
        result = await self.session.execute(
            select(ActionRecord)
            .where(ActionRecord.incident_id == incident_id)
            .order_by(ActionRecord.updated_at.desc(), ActionRecord.created_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        return RemediationAction.model_validate(record.payload) if record is not None else None

    async def find_action_by_id(self, action_id: UUID, *, tenant_id: str) -> RemediationAction | None:
        """Return an action only inside the authenticated tenant boundary."""
        result = await self.session.execute(
            select(ActionRecord).where(
                ActionRecord.id == action_id,
                ActionRecord.tenant_id == self._require("tenant_id", tenant_id),
            ).limit(1)
        )
        record = result.scalar_one_or_none()
        return RemediationAction.model_validate(record.payload) if record is not None else None

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
                tenant_id=action.tenant_id or "default",
                actor=self._require("audit.actor", actor),
                action=self._require("audit.action", "remediation.executed"),
                resource_type="incident",
                resource_id=self._require("audit.resource_id", str(action.incident_id)),
                payload=payload,
            )
        )

    async def get_runbook_governance(
        self, runbook_id: str, version: int = 1, *, tenant_id: str
    ) -> dict[str, Any] | None:
        normalized_tenant = self._require("tenant_id", tenant_id)
        result = await self.session.execute(
            select(RunbookVersionRecord).where(
                or_(
                    RunbookVersionRecord.tenant_id == normalized_tenant,
                    RunbookVersionRecord.tenant_id == "global",
                ),
                RunbookVersionRecord.runbook_id == self._parse_uuid(runbook_id),
                RunbookVersionRecord.version == int(version),
            )
            .order_by((RunbookVersionRecord.tenant_id == normalized_tenant).desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "runbook_id": str(row.runbook_id), "version": row.version, "status": row.approval_status,
            "approved_by": row.approved_by, "approved_at": row.approved_at,
            "success_count": row.success_count, "failure_count": row.failure_count,
            "suspended_reason": (row.content or {}).get("suspended_reason"), "payload": row.content or {},
        }

    async def approve_runbook_version(
        self, *, runbook_id: str, version: int, approved_by: str,
        tenant_id: str, payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tenant_id = self._require("tenant_id", tenant_id)
        result = await self.session.execute(
            select(RunbookVersionRecord).where(
                RunbookVersionRecord.tenant_id == tenant_id,
                RunbookVersionRecord.runbook_id == self._parse_uuid(runbook_id),
                RunbookVersionRecord.version == int(version),
            ).limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = RunbookVersionRecord(
                tenant_id=tenant_id, runbook_id=self._parse_uuid(runbook_id), version=int(version),
                issue_signature=str((payload or {}).get("issue_signature") or "manual-approval")[:64],
                owner=str(approved_by), risk_level=str((payload or {}).get("risk_level") or "medium"),
                required_approval="mandatory", content=payload or {},
            )
            self.session.add(row)
        row.approval_status = "approved"
        row.approved_by = str(approved_by)
        row.approved_at = datetime.now(UTC)
        row.content = payload or row.content or {}
        await self.session.flush()
        return {"runbook_id": str(row.runbook_id), "version": row.version, "status": row.approval_status}

    async def record_runbook_execution_outcome(
        self, *, runbook_id: str, version: int, successful: bool, modified: bool,
        actor: str, tenant_id: str, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tenant_id = self._require("tenant_id", tenant_id)
        result = await self.session.execute(
            select(RunbookVersionRecord).where(
                RunbookVersionRecord.tenant_id == tenant_id,
                RunbookVersionRecord.runbook_id == self._parse_uuid(runbook_id),
                RunbookVersionRecord.version == int(version),
            ).limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = RunbookVersionRecord(
                tenant_id=tenant_id, runbook_id=self._parse_uuid(runbook_id), version=int(version),
                issue_signature=str((metadata or {}).get("issue_signature") or "execution")[:64],
                approval_status=str((metadata or {}).get("runbook_status") or "draft"),
                owner=str(actor), risk_level=str((metadata or {}).get("risk_level") or "medium"),
                required_approval="mandatory", content=metadata or {},
            )
            self.session.add(row)
        row.success_count = int(row.success_count or 0) + int(successful)
        row.failure_count = int(row.failure_count or 0) + int(not successful)
        if modified or not successful:
            row.approval_status = "suspended"
            content = dict(row.content or {})
            content["suspended_reason"] = f"modified during execution by {actor}" if modified else f"execution failed; recorded by {actor}"
            row.content = content
        row.last_validated_at = datetime.now(UTC)
        outcome_payload = dict(metadata or {})
        incident_id = str(outcome_payload.get("incident_id") or outcome_payload.get("alert_id") or "unknown")[:128]
        outcome_key = f"{tenant_id}:{incident_id}:{row.runbook_id}:{row.version}"
        outcome_id = UUID(hashlib.md5(outcome_key.encode(), usedforsecurity=False).hexdigest())
        await self.session.merge(RunbookOutcomeRecord(
            outcome_id=outcome_id,
            tenant_id=tenant_id,
            incident_id=incident_id,
            runbook_id=row.runbook_id,
            runbook_version=row.version,
            reviewed=bool(outcome_payload.get("outcome_reviewed") and outcome_payload.get("outcome_reviewed_by")),
            successful=successful,
            validation=outcome_payload,
        ))
        audit_payload = {
            "successful": successful,
            "modified": modified,
            "runbook_version": row.version,
            "resulting_status": row.approval_status,
            "incident_id": incident_id,
        }
        canonical = json.dumps(audit_payload, sort_keys=True, separators=(",", ":"))
        self.session.add(LearningAuditRecord(
            tenant_id=tenant_id,
            actor=str(actor),
            action="runbook.execution.recorded",
            resource_type="runbook",
            resource_id=str(row.runbook_id),
            payload=audit_payload,
            payload_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
        ))
        await self.session.flush()
        return {"runbook_id": str(row.runbook_id), "version": row.version, "status": row.approval_status}

    async def save_report(self, report: ResolutionReport, *, tenant_id: str | None = None) -> None:
        verified_tenant = require_tenant_id(report.tenant_id, source="resolution report persistence")
        if tenant_id is not None and require_tenant_id(tenant_id, source="resolution report persistence") != verified_tenant:
            raise ValueError("report tenant does not match persistence tenant")
        await self.session.merge(
            RcaReportRecord(
                id=self._require("report.id", report.id),
                tenant_id=verified_tenant,
                incident_id=self._require("report.incident_id", report.incident_id),
                root_cause=self._require("report.root_cause", report.root_cause),
                impact=self._require("report.impact", report.impact),
                payload=report.model_dump(mode="json"),
            )
        )
        await self._save_validation_observations(report, tenant_id=verified_tenant)

    async def _save_validation_observations(self, report: ResolutionReport, *, tenant_id: str) -> None:
        observations = report.metadata.get("independent_validation_observations")
        observations = observations if isinstance(observations, list) else []
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            observed_at = datetime.fromisoformat(str(observation.get("observed_at") or "").replace("Z", "+00:00"))
            material = ":".join((
                str(report.id), str(observation.get("validator_id") or ""),
                observed_at.isoformat(), str(observation.get("result_checksum") or ""),
            ))
            await self.session.merge(ValidationObservationRecord(
                id=hashlib.sha256(material.encode()).hexdigest(), tenant_id=tenant_id,
                incident_id=report.incident_id, report_id=report.id,
                remediation_action_id=report.remediation_action_id,
                validator_id=self._require("validation.validator_id", observation.get("validator_id")),
                connector_id=self._require("validation.connector_id", observation.get("connector_id")),
                target_resource_id=self._require("validation.target_resource_id", observation.get("target_resource_id")),
                observed_at=observed_at, collected_at=utc_now(),
                authoritative_source=self._require("validation.authoritative_source", observation.get("connector_id")),
                result_checksum=self._require("validation.result_checksum", observation.get("result_checksum")),
                passed=observation.get("passed") is True, payload=observation,
            ))

    async def save_recommendation_as_audit(self, recommendation: Recommendation, *, tenant_id: str | None = None) -> None:
        verified_tenant = require_tenant_id(recommendation.tenant_id, source="recommendation audit persistence")
        if tenant_id is not None and require_tenant_id(tenant_id, source="recommendation audit persistence") != verified_tenant:
            raise ValueError("recommendation tenant does not match persistence tenant")
        await self.session.merge(
            AuditLogRecord(
                id=self._require("recommendation.id", recommendation.id),
                tenant_id=verified_tenant,
                actor=self._require("audit.actor", "resolution-agent"),
                action=self._require("audit.action", "recommendation.generated"),
                resource_type="incident",
                resource_id=self._require("audit.resource_id", str(recommendation.incident_id)),
                payload=recommendation.model_dump(mode="json"),
            )
        )
        metadata = recommendation.metadata if isinstance(recommendation.metadata, dict) else {}
        analysis_request_id = self._parse_uuid(metadata.get("analysis_request_id"))
        context_snapshot_id = self._parse_uuid(metadata.get("context_snapshot_id"))
        alert_id = self._parse_uuid(metadata.get("alert_id"))
        context_fingerprint = str(metadata.get("context_fingerprint") or "").strip()
        try:
            rca_version = int(metadata.get("rca_version") or 0)
        except (TypeError, ValueError):
            rca_version = 0
        if not all((analysis_request_id, context_snapshot_id, alert_id, context_fingerprint, rca_version > 0)):
            # Historical recommendations remain readable but explicitly
            # unbound; never fabricate normalized identities for them.
            return
        snapshot = await self.session.get(ContextSnapshotRecord, context_snapshot_id)
        if (
            snapshot is None
            or snapshot.tenant_id != verified_tenant
            or str(snapshot.incident_id) != str(recommendation.incident_id)
            or snapshot.context_fingerprint != context_fingerprint
        ):
            raise ValueError("recommendation context binding is not valid for persistence")
        plan = metadata.get("execution_plan") if isinstance(metadata.get("execution_plan"), dict) else {}
        values = {
            "binding_id": recommendation.id,
            "tenant_id": verified_tenant,
            "project_id": self._require("recommendation.project_id", metadata.get("project_id")),
            "incident_id": recommendation.incident_id,
            "alert_id": alert_id,
            "analysis_request_id": analysis_request_id,
            "context_snapshot_id": context_snapshot_id,
            "context_fingerprint": context_fingerprint,
            "recommendation_id": recommendation.id,
            "rca_version": rca_version,
            "resolution_plan_id": self._parse_uuid(plan.get("plan_id") or plan.get("id")),
            "plan_fingerprint": str(plan.get("plan_fingerprint") or plan.get("fingerprint") or "") or None,
            "status": str(metadata.get("rca_status") or "pending"),
            "created_at": recommendation.created_at,
            "expires_at": snapshot.expires_at,
        }
        existing = await self.session.get(IncidentInvestigationBindingRecord, recommendation.id)
        if existing is not None:
            immutable = (
                existing.tenant_id, existing.project_id, existing.incident_id, existing.alert_id,
                existing.analysis_request_id, existing.context_snapshot_id, existing.context_fingerprint,
                existing.recommendation_id, existing.rca_version,
            )
            incoming = tuple(values[key] for key in (
                "tenant_id", "project_id", "incident_id", "alert_id", "analysis_request_id",
                "context_snapshot_id", "context_fingerprint", "recommendation_id", "rca_version",
            ))
            if immutable != incoming:
                raise ValueError("immutable investigation binding already exists with different identities")
            return
        self.session.add(IncidentInvestigationBindingRecord(**values))

    async def save_knowledge_base(self, report: ResolutionReport, service: str = "unknown", *, tenant_id: str | None = None) -> None:
        verified_tenant = require_tenant_id(report.tenant_id, source="resolution knowledge persistence")
        if tenant_id is not None and require_tenant_id(tenant_id, source="resolution knowledge persistence") != verified_tenant:
            raise ValueError("report tenant does not match knowledge tenant")
        await self.session.merge(
            KnowledgeBaseRecord(
                id=self._require("knowledge_base.id", report.id),
                tenant_id=verified_tenant,
                service=self._require("knowledge_base.service", service),
                title=self._require("knowledge_base.title", f"RCA for incident {report.incident_id}"),
                content=self._require("knowledge_base.content", report.knowledge_base_entry),
                embedding_ref=self._require("knowledge_base.embedding_ref", str(report.id)),
                payload=report.model_dump(mode="json"),
            )
        )

    async def find_context_knowledge(
        self,
        *,
        tenant_id: str,
        service: str,
        environment: str,
        alert_name: str,
        alert_signature: str,
        not_before: datetime,
    ) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(ContextKnowledgeRecord)
            .where(
                ContextKnowledgeRecord.tenant_id == tenant_id,
                ContextKnowledgeRecord.service == service,
                ContextKnowledgeRecord.environment == environment,
                or_(
                    ContextKnowledgeRecord.alert_signature == alert_signature,
                    func.lower(ContextKnowledgeRecord.alert_name) == alert_name.strip().lower(),
                ),
                ContextKnowledgeRecord.collected_at >= not_before,
            )
            .order_by(ContextKnowledgeRecord.collected_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        # Transparently migrate knowledge created with an older, label-sensitive
        # signature. Subsequent occurrences use the stable alert-type key.
        match_type = "signature" if record.alert_signature == alert_signature else "alert_type"
        record.alert_signature = alert_signature
        record.reuse_count = int(record.reuse_count or 0) + 1
        return {
            "id": str(record.id),
            "source_alert_id": str(record.source_alert_id) if record.source_alert_id else None,
            "source_incident_id": str(record.source_incident_id) if record.source_incident_id else None,
            "reuse_count": record.reuse_count,
            "match_type": match_type,
            "payload": record.payload if isinstance(record.payload, dict) else {},
            "resolution_payload": record.resolution_payload if isinstance(record.resolution_payload, dict) else {},
            "collected_at": record.collected_at.isoformat(),
        }

    async def save_context_knowledge(
        self,
        *,
        tenant_id: str,
        service: str,
        environment: str,
        alert_name: str,
        alert_signature: str,
        source_alert_id: UUID,
        source_incident_id: UUID,
        payload: dict[str, Any],
    ) -> str:
        result = await self.session.execute(
            select(ContextKnowledgeRecord)
            .where(
                ContextKnowledgeRecord.tenant_id == tenant_id,
                ContextKnowledgeRecord.service == service,
                ContextKnowledgeRecord.environment == environment,
                ContextKnowledgeRecord.alert_signature == alert_signature,
            )
            .order_by(ContextKnowledgeRecord.updated_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = ContextKnowledgeRecord(
                tenant_id=tenant_id,
                service=service,
                environment=environment,
                alert_name=alert_name,
                alert_signature=alert_signature,
            )
            self.session.add(record)
        record.alert_name = alert_name
        record.source_alert_id = source_alert_id
        record.source_incident_id = source_incident_id
        record.collected_at = utc_now()
        record.payload = payload
        record.resolution_payload = {}
        record.updated_at = utc_now()
        await self.session.flush()
        return str(record.id)

    async def attach_context_knowledge_resolution(
        self,
        knowledge_id: str | UUID,
        resolution_payload: dict[str, Any],
    ) -> bool:
        record_id = self._parse_uuid(knowledge_id)
        if record_id is None:
            return False
        record = await self.session.get(ContextKnowledgeRecord, record_id)
        if record is None:
            return False
        record.resolution_payload = resolution_payload
        await self.session.flush()
        return True

    async def save_context_snapshot(
        self,
        *,
        snapshot_id: UUID,
        tenant_id: str,
        incident_id: str,
        source_incident_id: str | None,
        alert_signature: str,
        subject_fingerprint: str,
        context_fingerprint: str,
        contract_version: str,
        quality_score: float,
        reusable: bool,
        source_manifest: dict[str, Any],
        payload: dict[str, Any],
        collected_at: datetime,
        expires_at: datetime,
    ) -> None:
        if await self.session.get(ContextSnapshotRecord, snapshot_id) is not None:
            return
        self.session.add(
            ContextSnapshotRecord(
                snapshot_id=snapshot_id,
                tenant_id=tenant_id,
                incident_id=self._require("context_snapshot.incident_id", incident_id),
                source_incident_id=source_incident_id,
                alert_signature=self._require("context_snapshot.alert_signature", alert_signature),
                subject_fingerprint=self._require("context_snapshot.subject_fingerprint", subject_fingerprint),
                context_fingerprint=self._require("context_snapshot.context_fingerprint", context_fingerprint),
                contract_version=contract_version or "kaiops.context.v2",
                quality_score=max(0.0, min(float(quality_score), 1.0)),
                reusable=bool(reusable),
                source_manifest=source_manifest if isinstance(source_manifest, dict) else {},
                payload=payload if isinstance(payload, dict) else {},
                collected_at=collected_at,
                expires_at=expires_at,
            )
        )
        await self.session.flush()

    async def latest_context_snapshot(self, incident_id: str, *, tenant_id: str = "default") -> dict[str, Any] | None:
        row = (
            await self.session.execute(
                select(ContextSnapshotRecord)
                .where(
                    ContextSnapshotRecord.tenant_id == (tenant_id or "default"),
                    ContextSnapshotRecord.incident_id == incident_id,
                )
                .order_by(ContextSnapshotRecord.collected_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "snapshot_id": str(row.snapshot_id),
            "tenant_id": row.tenant_id,
            "incident_id": row.incident_id,
            "source_incident_id": row.source_incident_id,
            "alert_signature": row.alert_signature,
            "subject_fingerprint": row.subject_fingerprint,
            "context_fingerprint": row.context_fingerprint,
            "contract_version": row.contract_version,
            "quality_score": float(row.quality_score or 0.0),
            "reusable": bool(row.reusable),
            "source_manifest": row.source_manifest if isinstance(row.source_manifest, dict) else {},
            "context": row.payload if isinstance(row.payload, dict) else {},
            "collected_at": row.collected_at.isoformat(),
            "expires_at": row.expires_at.isoformat(),
        }

    async def context_snapshot_by_id(
        self, snapshot_id: UUID | str, *, tenant_id: str, incident_id: UUID | str,
    ) -> dict[str, Any] | None:
        snapshot_uuid = self._parse_uuid(snapshot_id)
        if snapshot_uuid is None:
            return None
        row = (
            await self.session.execute(
                select(ContextSnapshotRecord).where(
                    ContextSnapshotRecord.snapshot_id == snapshot_uuid,
                    ContextSnapshotRecord.tenant_id == str(self._require("context_snapshot.tenant_id", tenant_id)),
                    ContextSnapshotRecord.incident_id
                    == str(self._require("context_snapshot.incident_id", incident_id)),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "snapshot_id": str(row.snapshot_id),
            "tenant_id": row.tenant_id,
            "incident_id": row.incident_id,
            "context_fingerprint": row.context_fingerprint,
            "context": row.payload if isinstance(row.payload, dict) else {},
            "collected_at": row.collected_at.isoformat(),
            "expires_at": row.expires_at.isoformat(),
        }

    async def get_bound_incident_investigation(
        self,
        *,
        tenant_id: str,
        incident_id: UUID | str,
        alert_id: UUID | str,
        recommendation_id: UUID | str | None,
    ) -> dict[str, Any]:
        """Load one immutable recommendation/context pair and verify its binding.

        This deliberately has no "latest snapshot" fallback.  Callers may still
        render the alert and incident when integrity fails, but must not present
        an independently selected context snapshot as RCA support.
        """
        normalized_tenant_id = str(self._require("tenant_id", tenant_id))
        incident_uuid = self._parse_uuid(incident_id)
        alert_uuid = self._parse_uuid(alert_id)
        recommendation_uuid = self._parse_uuid(recommendation_id)
        reasons: list[str] = []
        referenced_snapshot_id: UUID | None = None

        def result(
            status: str,
            *,
            recommendation: dict[str, Any] | None = None,
            snapshot: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            if not reasons:
                reasons.append(status.replace("_", " "))
            return {
                "recommendation": recommendation or {},
                "context_snapshot": snapshot or {},
                "investigation_integrity": {
                    "status": status,
                    "verified": status == "verified",
                    "blocking_reasons": [] if status == "verified" else list(dict.fromkeys(reasons)),
                    "recommendation_id": str(recommendation_uuid) if recommendation_uuid else None,
                    "context_snapshot_id": (
                        str((snapshot or {}).get("snapshot_id") or referenced_snapshot_id or "").strip() or None
                    ),
                },
            }

        if incident_uuid is None or alert_uuid is None:
            return result("contract_invalid")
        if recommendation_uuid is None:
            return result("missing_recommendation")

        recommendation_record = (
            await self.session.execute(
                select(AuditLogRecord).where(
                    AuditLogRecord.id == recommendation_uuid,
                    AuditLogRecord.tenant_id == normalized_tenant_id,
                    AuditLogRecord.resource_type == "incident",
                    AuditLogRecord.resource_id == str(incident_uuid),
                    AuditLogRecord.action == "recommendation.generated",
                )
            )
        ).scalar_one_or_none()
        if recommendation_record is None:
            return result("missing_recommendation")
        recommendation = (
            dict(recommendation_record.payload)
            if isinstance(recommendation_record.payload, dict)
            else {}
        )
        metadata = recommendation.get("metadata") if isinstance(recommendation.get("metadata"), dict) else {}
        binding_record = await self.session.get(IncidentInvestigationBindingRecord, recommendation_uuid)
        if binding_record is None:
            reasons.append("recommendation predates the normalized investigation binding contract")
            return result("legacy_unbound", recommendation=recommendation)
        if binding_record.tenant_id != normalized_tenant_id:
            return result("tenant_mismatch", recommendation=recommendation)
        if binding_record.incident_id != incident_uuid:
            return result("incident_mismatch", recommendation=recommendation)
        if binding_record.alert_id != alert_uuid:
            return result("alert_mismatch", recommendation=recommendation)
        if binding_record.recommendation_id != recommendation_uuid:
            return result("contract_invalid", recommendation=recommendation)
        if str(metadata.get("analysis_request_id") or "") != str(binding_record.analysis_request_id):
            return result("contract_invalid", recommendation=recommendation)
        if str(metadata.get("project_id") or "") != binding_record.project_id:
            return result("project_mismatch", recommendation=recommendation)
        referenced_snapshot_id = self._parse_uuid(metadata.get("context_snapshot_id"))
        if referenced_snapshot_id is None:
            reasons.append("recommendation does not reference a context snapshot")
            status = "missing_snapshot_reference" if metadata.get("analysis_request_id") else "legacy_unbound"
            return result(status, recommendation=recommendation)
        if referenced_snapshot_id != binding_record.context_snapshot_id:
            return result("contract_invalid", recommendation=recommendation)

        # Query by immutable ID first so a cross-tenant record is distinguishable
        # from a missing record without ever returning its contents.
        snapshot_record = await self.session.get(ContextSnapshotRecord, referenced_snapshot_id)
        if snapshot_record is None:
            return result("snapshot_not_found", recommendation=recommendation)
        if snapshot_record.tenant_id != normalized_tenant_id:
            return result("tenant_mismatch", recommendation=recommendation)
        if str(snapshot_record.incident_id) != str(incident_uuid):
            return result("incident_mismatch", recommendation=recommendation)

        snapshot_payload = dict(snapshot_record.payload) if isinstance(snapshot_record.payload, dict) else {}
        snapshot_metadata = (
            snapshot_payload.get("metadata")
            if isinstance(snapshot_payload.get("metadata"), dict)
            else {}
        )
        bound_alert_id = str(
            metadata.get("alert_id")
            or snapshot_metadata.get("alert_id")
            or snapshot_payload.get("alert_id")
            or ""
        ).strip()
        if bound_alert_id and bound_alert_id != str(alert_uuid):
            return result("alert_mismatch", recommendation=recommendation)

        expected_fingerprint = str(metadata.get("context_fingerprint") or "").strip()
        if not expected_fingerprint or expected_fingerprint != str(snapshot_record.context_fingerprint):
            return result("fingerprint_mismatch", recommendation=recommendation)

        expected_project = str(metadata.get("project_id") or "").strip()
        snapshot_project = str(
            snapshot_metadata.get("project_id") or snapshot_payload.get("project_id") or ""
        ).strip()
        if expected_project and snapshot_project and expected_project != snapshot_project:
            return result("project_mismatch", recommendation=recommendation)

        now = datetime.now(UTC)
        expires_at = snapshot_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            return result("context_expired", recommendation=recommendation)

        evidence_buckets = snapshot_metadata.get("context_evidence")
        if not isinstance(evidence_buckets, dict):
            evidence_buckets = snapshot_payload.get("context_evidence")
        available_evidence_ids = {
            str(item.get("evidence_id") or item.get("id") or "").strip()
            for rows in (evidence_buckets.values() if isinstance(evidence_buckets, dict) else [])
            if isinstance(rows, list)
            for item in rows
            if isinstance(item, dict)
        }
        available_evidence_ids.discard("")
        accepted_evidence = metadata.get("evidence_ids")
        if not isinstance(accepted_evidence, list):
            rca_analysis = metadata.get("rca_analysis") if isinstance(metadata.get("rca_analysis"), dict) else {}
            accepted_evidence = rca_analysis.get("evidence_used", [])
        missing_ids = sorted(
            str(item).strip()
            for item in accepted_evidence
            if str(item).strip() and str(item).strip() not in available_evidence_ids
        )
        if missing_ids:
            reasons.append("accepted RCA evidence is absent from the bound context snapshot")
            return result("evidence_mismatch", recommendation=recommendation)

        snapshot = {
            "snapshot_id": str(snapshot_record.snapshot_id),
            "tenant_id": snapshot_record.tenant_id,
            "incident_id": snapshot_record.incident_id,
            "context_fingerprint": snapshot_record.context_fingerprint,
            "contract_version": snapshot_record.contract_version,
            "quality_score": float(snapshot_record.quality_score or 0.0),
            "reusable": bool(snapshot_record.reusable),
            "source_manifest": snapshot_record.source_manifest or {},
            "context": snapshot_payload,
            "collected_at": snapshot_record.collected_at.isoformat(),
            "expires_at": snapshot_record.expires_at.isoformat(),
        }
        return result("verified", recommendation=recommendation, snapshot=snapshot)

    async def current_incident_investigation_binding(
        self, *, tenant_id: str, incident_id: UUID | str, alert_id: UUID | str,
    ) -> dict[str, str] | None:
        incident_uuid = self._parse_uuid(incident_id)
        alert_uuid = self._parse_uuid(alert_id)
        if incident_uuid is None or alert_uuid is None:
            return None
        row = (
            await self.session.execute(
                select(IncidentProjectionRecord).where(
                    IncidentProjectionRecord.tenant_id == self._require("tenant_id", tenant_id),
                    IncidentProjectionRecord.incident_id == incident_uuid,
                    IncidentProjectionRecord.alert_id == alert_uuid,
                )
            )
        ).scalar_one_or_none()
        if row is None or row.recommendation_id is None:
            return None
        return {
            "tenant_id": row.tenant_id,
            "incident_id": str(row.incident_id),
            "alert_id": str(row.alert_id),
            "recommendation_id": str(row.recommendation_id),
        }

    @staticmethod
    def build_incident_investigation_contract(
        *,
        tenant_id: str,
        project_id: str,
        incident_id: UUID | str,
        alert_id: UUID | str,
        recommendation: dict[str, Any],
        context_snapshot: dict[str, Any],
        approval: dict[str, Any] | None = None,
        remediation_action: dict[str, Any] | None = None,
        validation_status: str = "pending",
    ) -> dict[str, Any]:
        """Construct and validate the versioned runtime contract.

        Required immutable identifiers are intentionally not synthesized.  A
        malformed or legacy payload raises validation failure so its caller can
        downgrade integrity to ``contract_invalid``.
        """
        metadata = recommendation.get("metadata") if isinstance(recommendation.get("metadata"), dict) else {}
        context = context_snapshot.get("context") if isinstance(context_snapshot.get("context"), dict) else {}
        context_metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
        quality = (
            context_metadata.get("context_quality")
            if isinstance(context_metadata.get("context_quality"), dict)
            else {}
        )
        source_manifest = (
            context_metadata.get("context_sources")
            if isinstance(context_metadata.get("context_sources"), dict)
            else {}
        )
        evidence_buckets = (
            context_metadata.get("context_evidence")
            if isinstance(context_metadata.get("context_evidence"), dict)
            else {}
        )
        evidence_rows = [
            item
            for bucket in evidence_buckets.values()
            if isinstance(bucket, list)
            for item in bucket
            if isinstance(item, dict)
        ]
        sources = []
        for source_id, details in source_manifest.items():
            row = details if isinstance(details, dict) else {}
            raw_status = str(row.get("status") or row.get("collection_status") or "skipped").lower()
            status_aliases = {
                "collected": "completed",
                "success": "completed",
                "stale": "completed",
                "fresh": "completed",
                "no_matches": "empty",
                "failed": "unavailable",
            }
            status = status_aliases.get(raw_status, raw_status)
            collected_at = row.get("collected_at") or context_snapshot.get("collected_at")
            sources.append({
                "source_id": str(source_id),
                "category": str(row.get("category") or source_id),
                "connector": str(row.get("connector") or row.get("provider") or source_id),
                "status": status,
                "collected_at": collected_at,
                "error": str(row.get("error") or "") or None,
            })
        evidence = [{
            "evidence_id": item.get("evidence_id") or item.get("id"),
            "category": item.get("category") or item.get("source_type") or "unknown",
            "source_id": item.get("source_id") or item.get("source") or item.get("connector") or "unknown",
            "connector": item.get("connector") or item.get("source") or "unknown",
            "tenant_id": item.get("tenant_id") or tenant_id,
            "project_id": item.get("project_id") or project_id,
            "service": item.get("service") or context.get("alert", {}).get("service") or "unknown",
            "resource_id": item.get("resource_id"),
            "observed_at": item.get("observed_at"),
            "collected_at": (
                item.get("collected_at")
                or (item.get("provenance") or {}).get("generated_at")
                or context_snapshot.get("collected_at")
            ),
            "observation_window": item.get("observation_window"),
            "freshness": str(item.get("freshness") or "unknown").lower(),
            "provenance": item.get("provenance") if isinstance(item.get("provenance"), dict) else {},
            "citation": (
                item.get("citation")
                or item.get("source_uri")
                or item.get("uri")
                or (item.get("provenance") or {}).get("primary_source")
            ),
            "epistemic_role": item.get("epistemic_role") or "current_observation",
            "current_observation": item.get("current_observation") is not False,
        } for item in evidence_rows]
        analysis = metadata.get("rca_analysis") if isinstance(metadata.get("rca_analysis"), dict) else {}
        investigation = (
            metadata.get("iterative_investigation")
            if isinstance(metadata.get("iterative_investigation"), dict)
            else metadata.get("investigation_report")
            if isinstance(metadata.get("investigation_report"), dict)
            else {}
        )
        plan = metadata.get("execution_plan") if isinstance(metadata.get("execution_plan"), dict) else {}
        accepted = (
            metadata.get("evidence_ids")
            if isinstance(metadata.get("evidence_ids"), list)
            else analysis.get("evidence_used", [])
        )
        missing = analysis.get("missing_evidence", []) if isinstance(analysis.get("missing_evidence"), list) else []
        conflicting = (
            analysis.get("conflicting_evidence", [])
            if isinstance(analysis.get("conflicting_evidence"), list)
            else []
        )
        conclusive = (
            investigation.get("conclusive") is True
            and str(investigation.get("status") or "").lower() == "conclusive"
        )
        grounded = str(metadata.get("rca_status") or "").lower() == "grounded" and bool(accepted)
        plan_blocks = plan.get("readiness_blocks") if isinstance(plan.get("readiness_blocks"), list) else []
        plan_id = plan.get("plan_id") or plan.get("id")
        plan_fingerprint = plan.get("plan_fingerprint") or plan.get("fingerprint")
        readiness_blocks = list(dict.fromkeys([
            *[str(item) for item in missing],
            *[str(item) for item in conflicting],
            *[str(item) for item in plan_blocks],
            *([] if conclusive else ["investigation is not conclusive"]),
            *([] if grounded else ["RCA is not grounded in accepted evidence"]),
            *([] if plan_id and plan_fingerprint else ["exact resolution plan is not ready"]),
        ]))
        execution_ready = bool(
            conclusive and grounded and plan.get("execution_ready") is True
            and plan.get("mutating") is True and plan_id and plan_fingerprint and not readiness_blocks
        )
        approval_payload = approval if isinstance(approval, dict) else {}
        approval_status = str(approval_payload.get("decision") or approval_payload.get("status") or "not_ready").lower()
        if approval_status not in {"not_ready", "pending", "approved", "rejected", "stale"}:
            approval_status = "not_ready"
        raw_investigation_status = str(investigation.get("status") or "pending").lower()
        investigation_status = {
            "budget_exhausted": "inconclusive",
            "completed": "conclusive" if conclusive else "inconclusive",
            "running": "investigating",
        }.get(raw_investigation_status, raw_investigation_status)
        payload = {
            "contract_version": "kaiops.incident-investigation.v1",
            "tenant_id": tenant_id,
            "project_id": project_id,
            "incident_id": incident_id,
            "alert_id": alert_id,
            "analysis_request_id": metadata.get("analysis_request_id"),
            "context_snapshot_id": context_snapshot.get("snapshot_id"),
            "context_fingerprint": context_snapshot.get("context_fingerprint"),
            "context_contract_version": context_snapshot.get("contract_version"),
            "context_collected_at": context_snapshot.get("collected_at"),
            "context_expires_at": context_snapshot.get("expires_at"),
            "context_quality": {
                "evidence_count": len(evidence),
                "category_coverage": float(quality.get("coverage_score") or quality.get("category_coverage") or 0),
                "freshness_score": float(quality.get("freshness_score") or 0),
                "provenance_score": float(quality.get("provenance_score") or 0),
                "independent_source_count": int(quality.get("independent_source_count") or 0),
                "direct_observation_count": int(quality.get("direct_observation_count") or 0),
                "valid": bool(quality.get("valid", quality.get("reusable", False))),
                "blocking_reasons": [str(item) for item in quality.get("blocking_reasons", [])],
            },
            "context_sources": sources,
            "context_evidence": evidence,
            "investigation_id": investigation.get("investigation_id"),
            "investigation_status": investigation_status,
            "investigation_conclusive": conclusive,
            "rca_version": metadata.get("rca_version"),
            "rca_status": metadata.get("rca_status") or "pending",
            "accepted_evidence_ids": [str(item) for item in accepted],
            "missing_evidence": [str(item) for item in missing],
            "conflicting_evidence": [str(item) for item in conflicting],
            "recommendation_id": recommendation.get("id"),
            "resolution_plan_id": plan_id,
            "plan_fingerprint": plan_fingerprint,
            "execution_ready": execution_ready,
            "readiness_blocks": readiness_blocks,
            "approval_status": approval_status,
            "remediation_status": str((remediation_action or {}).get("status") or "not_started"),
            "validation_status": validation_status,
            "readiness": {
                "investigation_ready": bool(evidence),
                "rca_ready": conclusive and grounded,
                "resolution_ready": conclusive and grounded and bool(plan_id),
                "execution_ready": execution_ready,
                "blocking_reasons": readiness_blocks,
            },
        }
        return IncidentInvestigationContract.model_validate(payload).model_dump(mode="json")

    async def create_resolution_investigation(self, payload: dict[str, Any]) -> None:
        await self.session.execute(
            text(
                "INSERT INTO resolution_investigations "
                "(investigation_id,tenant_id,incident_id,alert_id,status,step_budget,steps_used,evidence_count,"
                "tool_budget,source_coverage,missing_sources,conclusion,payload,started_at) "
                "VALUES (:investigation_id,:tenant_id,:incident_id,:alert_id,:status,:step_budget,0,:evidence_count,"
                ":tool_budget,:source_coverage,:missing_sources,:conclusion,:payload,NOW(6)) "
                "ON DUPLICATE KEY UPDATE status=VALUES(status), updated_at=NOW(6)"
            ),
            {
                "investigation_id": self._require("investigation_id", payload.get("investigation_id")),
                "tenant_id": str(payload.get("tenant_id") or "default"),
                "incident_id": self._require("incident_id", payload.get("incident_id")),
                "alert_id": str(payload.get("alert_id") or "") or None,
                "status": str(payload.get("status") or "running"),
                "step_budget": int(payload.get("step_budget") or 1),
                "evidence_count": int(payload.get("evidence_count") or 0),
                "tool_budget": json.dumps({"max_steps": int(payload.get("step_budget") or 1)}),
                "source_coverage": json.dumps({}),
                "missing_sources": json.dumps([]),
                "conclusion": json.dumps({}),
                "payload": json.dumps(payload, default=str),
            },
        )

    async def append_resolution_investigation_step(self, payload: dict[str, Any]) -> None:
        await self.session.execute(
            text(
                "INSERT INTO resolution_investigation_steps "
                "(step_id,investigation_id,sequence_no,tool_name,query_payload,status,result_count,evidence_ids,"
                "hypothesis_updates,error_message,started_at,completed_at) "
                "VALUES (:step_id,:investigation_id,:sequence_no,:tool_name,:query_payload,:status,:result_count,"
                ":evidence_ids,:hypothesis_updates,:error_message,:started_at,:completed_at) "
                "ON DUPLICATE KEY UPDATE status=VALUES(status),result_count=VALUES(result_count),"
                "evidence_ids=VALUES(evidence_ids),hypothesis_updates=VALUES(hypothesis_updates),"
                "error_message=VALUES(error_message),completed_at=VALUES(completed_at)"
            ),
            {
                "step_id": self._require("step_id", payload.get("step_id")),
                "investigation_id": self._require("investigation_id", payload.get("investigation_id")),
                "sequence_no": int(payload.get("sequence_no") or 0),
                "tool_name": self._require("tool_name", payload.get("tool_name")),
                "query_payload": json.dumps(payload.get("query") or {}, default=str),
                "status": str(payload.get("status") or "completed"),
                "result_count": int(payload.get("result_count") or 0),
                "evidence_ids": json.dumps(payload.get("evidence_ids") or []),
                "hypothesis_updates": json.dumps(payload.get("hypothesis_updates") or [], default=str),
                "error_message": str(payload.get("error") or "")[:1000] or None,
                "started_at": payload.get("started_at") or utc_now(),
                "completed_at": payload.get("completed_at") or utc_now(),
            },
        )

    async def complete_resolution_investigation(self, payload: dict[str, Any]) -> None:
        investigation_id = self._require("investigation_id", payload.get("investigation_id"))
        await self.session.execute(
            text(
                "UPDATE resolution_investigations SET status=:status,stop_reason=:stop_reason,steps_used=:steps_used,"
                "evidence_count=:evidence_count,source_coverage=:source_coverage,missing_sources=:missing_sources,"
                "conclusion=:conclusion,payload=:payload,completed_at=NOW(6),updated_at=NOW(6) "
                "WHERE investigation_id=:investigation_id"
            ),
            {
                "investigation_id": investigation_id,
                "status": str(payload.get("status") or "inconclusive"),
                "stop_reason": str(payload.get("stop_reason") or "")[:128] or None,
                "steps_used": int(payload.get("steps_used") or 0),
                "evidence_count": int(payload.get("evidence_count") or 0),
                "source_coverage": json.dumps(payload.get("source_coverage") or {}),
                "missing_sources": json.dumps(payload.get("missing_sources") or []),
                "conclusion": json.dumps(payload.get("conclusion") or {}, default=str),
                "payload": json.dumps(payload, default=str),
            },
        )
        for hypothesis in payload.get("hypotheses") or []:
            if not isinstance(hypothesis, dict) or not str(hypothesis.get("claim") or "").strip():
                continue
            claim = str(hypothesis["claim"]).strip()
            digest = hashlib.sha256(claim.lower().encode()).hexdigest()
            await self.session.execute(
                text(
                    "INSERT INTO resolution_hypotheses "
                    "(hypothesis_id,investigation_id,claim_digest,claim_text,status,confidence,supporting_evidence_ids,"
                    "contradicting_evidence_ids,falsification_query,source,payload) "
                    "VALUES (:hypothesis_id,:investigation_id,:claim_digest,:claim_text,:status,:confidence,"
                    ":supporting,:contradicting,:falsification,:source,:payload) "
                    "ON DUPLICATE KEY UPDATE status=VALUES(status),confidence=VALUES(confidence),"
                    "supporting_evidence_ids=VALUES(supporting_evidence_ids),"
                    "contradicting_evidence_ids=VALUES(contradicting_evidence_ids),payload=VALUES(payload),updated_at=NOW(6)"
                ),
                {
                    "hypothesis_id": str(hypothesis.get("hypothesis_id") or uuid4()),
                    "investigation_id": investigation_id,
                    "claim_digest": digest,
                    "claim_text": claim,
                    "status": str(hypothesis.get("status") or "viable"),
                    "confidence": max(0.0, min(float(hypothesis.get("confidence") or 0.0), 1.0)),
                    "supporting": json.dumps(hypothesis.get("supporting_evidence_ids") or []),
                    "contradicting": json.dumps(hypothesis.get("contradicting_evidence_ids") or []),
                    "falsification": json.dumps(hypothesis.get("falsification_query") or {}, default=str),
                    "source": str(hypothesis.get("source") or "unknown")[:64],
                    "payload": json.dumps(hypothesis, default=str),
                },
            )

    async def latest_resolution_investigation(
        self, incident_id: str, *, tenant_id: str = "default"
    ) -> dict[str, Any] | None:
        row = (
            await self.session.execute(
                text(
                    "SELECT payload FROM resolution_investigations "
                    "WHERE tenant_id=:tenant_id AND incident_id=:incident_id "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"tenant_id": tenant_id or "default", "incident_id": incident_id},
            )
        ).scalar_one_or_none()
        if isinstance(row, dict):
            return row
        if isinstance(row, str):
            try:
                parsed = json.loads(row)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    async def record_resolution_transition(self, payload: dict[str, Any]) -> bool:
        """Append one idempotent lifecycle transition; duplicate events are no-ops."""
        result = await self.session.execute(
            text(
                "INSERT IGNORE INTO resolution_state_transitions "
                "(transition_id,tenant_id,incident_id,recommendation_id,execution_plan_id,previous_state,new_state,"
                "event_id,correlation_id,causation_id,idempotency_key,actor,reason_code,evidence_ids,policy_decision,payload) "
                "VALUES (:transition_id,:tenant_id,:incident_id,:recommendation_id,:execution_plan_id,:previous_state,"
                ":new_state,:event_id,:correlation_id,:causation_id,:idempotency_key,:actor,:reason_code,"
                ":evidence_ids,:policy_decision,:payload)"
            ),
            {
                "transition_id": str(payload.get("transition_id") or uuid4()),
                "tenant_id": str(payload.get("tenant_id") or "default"),
                "incident_id": self._require("incident_id", payload.get("incident_id")),
                "recommendation_id": str(payload.get("recommendation_id") or "") or None,
                "execution_plan_id": str(payload.get("execution_plan_id") or "") or None,
                "previous_state": self._require("previous_state", payload.get("previous_state")),
                "new_state": self._require("new_state", payload.get("new_state")),
                "event_id": self._require("event_id", payload.get("event_id")),
                "correlation_id": str(payload.get("correlation_id") or "") or None,
                "causation_id": str(payload.get("causation_id") or "") or None,
                "idempotency_key": self._require("idempotency_key", payload.get("idempotency_key")),
                "actor": self._require("actor", payload.get("actor")),
                "reason_code": self._require("reason_code", payload.get("reason_code")),
                "evidence_ids": json.dumps(payload.get("evidence_ids") or []),
                "policy_decision": json.dumps(payload.get("policy_decision") or {}, default=str),
                "payload": json.dumps(payload, default=str),
            },
        )
        return bool(result.rowcount)

    async def get_approved_runbook_version(
        self, runbook_id: str, version: int, *, tenant_id: str = "default"
    ) -> dict[str, Any] | None:
        normalized_runbook_id = self._parse_uuid(runbook_id).hex
        row = (
            await self.session.execute(
                text(
                    "SELECT rv.content,rv.owner,rv.risk_level,rv.success_count,rv.failure_count,"
                    "ra.approver,ra.approver_role,ra.approved_at "
                    "FROM runbook_versions rv JOIN runbook_approvals ra "
                    "ON ra.runbook_id=rv.runbook_id AND ra.version=rv.version AND ra.status='approved' "
                    "WHERE rv.tenant_id=:tenant_id AND rv.runbook_id=:runbook_id AND rv.version=:version "
                    "AND rv.approval_status='approved' LIMIT 1"
                ),
                {"tenant_id": tenant_id, "runbook_id": normalized_runbook_id, "version": int(version)},
            )
        ).mappings().first()
        if row is None:
            return None
        content = row["content"]
        if isinstance(content, str):
            content = json.loads(content)
        attempts = int(row["success_count"] or 0) + int(row["failure_count"] or 0)
        return {
            **(content if isinstance(content, dict) else {}),
            "runbook_id": str(UUID(normalized_runbook_id)),
            "version": int(version),
            "status": "approved",
            "owner": row["owner"],
            "risk": row["risk_level"],
            "success_rate": int(row["success_count"] or 0) / attempts if attempts else 0.0,
            "approved_by": row["approver"],
            "approver_role": row["approver_role"],
            "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
        }

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

    async def resolve_context_integrations(
        self, *, tenant_id: str, project_candidates: list[str],
    ) -> list[dict[str, Any]]:
        """Resolve active onboarding connectors by exact tenant/project identity."""
        candidates = {str(value).strip().lower() for value in project_candidates if str(value).strip()}
        if not candidates:
            return []
        integrations = (
            await self.session.execute(
                select(MonitoringIntegrationRecord).where(
                    MonitoringIntegrationRecord.tenant_id
                    == self._require("monitoring_integration.tenant_id", tenant_id),
                    MonitoringIntegrationRecord.active.is_(True),
                    func.lower(MonitoringIntegrationRecord.project_name).in_(candidates),
                )
            )
        ).scalars().all()
        if not integrations:
            return []
        integration_ids = [row.id for row in integrations]
        credentials = (
            await self.session.execute(
                select(MonitoringCredentialRecord).where(
                    MonitoringCredentialRecord.integration_id.in_(integration_ids)
                )
            )
        ).scalars().all()
        credential_by_integration = {row.integration_id: row for row in credentials}
        return [
            {
                "integration_id": str(row.id),
                "tenant_id": row.tenant_id,
                "project_id": row.project_name,
                "provider": row.provider,
                "status": row.status,
                "endpoint_identity": row.endpoint_url,
                "auth_type": row.auth_type,
                "secret_ref": (
                    credential_by_integration[row.id].secret_ref
                    if row.id in credential_by_integration else None
                ),
                "config": dict(row.config_payload or {}),
            }
            for row in integrations
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
            "expires_at": row.expires_at,
            "artifact_signature": row.artifact_signature,
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
                tenant_id=audit_event.tenant_id or "default",
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
        tenant_id: str = "default",
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
                tenant_id=self._require("onboarding.tenant_id", tenant_id),
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

    async def list_onboarding_state(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(
                OnboardingStateRecord.tenant_id,
                OnboardingStateRecord.project_name,
                OnboardingStateRecord.provider_name,
                OnboardingStateRecord.owner_team,
                OnboardingStateRecord.environment,
                OnboardingStateRecord.region,
                OnboardingStateRecord.endpoint_url,
                OnboardingStateRecord.test_status,
                OnboardingStateRecord.test_message,
                OnboardingStateRecord.project_payload,
                OnboardingStateRecord.connectivity_payload,
                OnboardingStateRecord.updated_at,
                OnboardingStateRecord.last_tested_at,
            )
            .where(OnboardingStateRecord.tenant_id == self._require("onboarding.tenant_id", tenant_id))
            .order_by(OnboardingStateRecord.project_name, OnboardingStateRecord.provider_name)
        )
        rows = result.all()
        return [
            {
                "tenant_id": row.tenant_id,
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

    async def save_onboarding_control_plane(self, payload: dict[str, Any]) -> None:
        onboarding_id = UUID(str(payload["onboarding_id"]))
        existing = await self.session.get(OnboardingControlPlaneRecord, onboarding_id)
        if existing is None:
            self.session.add(OnboardingControlPlaneRecord(
                onboarding_id=onboarding_id,
                tenant_id=self._require("onboarding.tenant_id", payload.get("tenant_id")),
                project_name=self._require("onboarding.project_name", payload.get("project", {}).get("name")),
                current_step=int(payload.get("current_step") or 1),
                status=str(payload.get("status") or "DRAFT"),
                version=int(payload.get("version") or 1),
                payload=payload,
            ))
            return
        existing.project_name = self._require("onboarding.project_name", payload.get("project", {}).get("name"))
        existing.current_step = int(payload.get("current_step") or 1)
        existing.status = str(payload.get("status") or "DRAFT")
        existing.version = int(payload.get("version") or 1)
        existing.payload = payload

    async def get_onboarding_control_plane(self, onboarding_id: UUID, tenant_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(select(OnboardingControlPlaneRecord).where(
            OnboardingControlPlaneRecord.onboarding_id == onboarding_id,
            OnboardingControlPlaneRecord.tenant_id == require_tenant_id(tenant_id, source="onboarding lookup"),
        ))
        row = result.scalar_one_or_none()
        return dict(row.payload) if row else None

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

        incoming_status_token = str(event_record.status or "").strip().lower()
        existing_status_token = str(projection.status or "").strip().lower()
        if (
            existing_status_token in _CLOSED_INCIDENT_STATUSES
            and incoming_status_token not in _CLOSED_INCIDENT_STATUSES
            and event_record.event_type != "incident.reopened"
        ):
            # Event delivery is at-least-once and cross-service timestamps can
            # be tied at database precision. A late remediation/alert event is
            # not an authorized reopen operation, so terminal state wins.
            await self.session.merge(projection)
            return

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
        incoming_status = event_record.status or projection.status or "open"
        if event_record.event_type == "incident.recommendation.generated" and str(incoming_status).lower() == "remediating":
            # A recommendation establishes readiness, never proof that an
            # executor started. This also protects projection rebuild/replay
            # from restoring the legacy false-remediating state.
            incoming_status = "awaiting_approval" if event_record.requires_approval else "approved"
        projection.status = incoming_status
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
        # This worker is a repair path, not a second lifecycle consumer. Replaying
        # historical events into an existing projection can undo a newer status
        # written by remediation/closure (especially for legacy events with tied
        # timestamps). Only reconstruct projections that are actually missing.
        incident_ids = {row.incident_id for row in rows}
        existing_ids: set[UUID] = set()
        if incident_ids:
            existing_result = await self.session.execute(
                select(IncidentProjectionRecord.incident_id).where(
                    IncidentProjectionRecord.incident_id.in_(incident_ids)
                )
            )
            existing_ids = set(existing_result.scalars().all())
        rebuilt_ids = incident_ids - existing_ids
        for row in rows:
            if row.incident_id in rebuilt_ids:
                await self._upsert_projection_from_record(row)
        # Legacy batches may contain a recommendation marked remediating and a
        # policy-blocked action event with the same timestamp. Normalize after
        # the whole ordered replay so tie-breaking cannot leave a projection
        # claiming execution without an active executor action.
        await self.session.execute(
            text(
                "UPDATE incident_projections p SET "
                "p.status=CASE "
                "WHEN EXISTS (SELECT 1 FROM actions a WHERE a.incident_id=p.incident_id "
                "AND a.status IN ('awaiting_approval','policy_blocked')) THEN 'awaiting_approval' "
                "WHEN COALESCE(p.requires_approval,0)=1 THEN 'awaiting_approval' ELSE 'approved' END, "
                "p.projection_payload=JSON_SET(COALESCE(p.projection_payload, JSON_OBJECT()), '$.status', "
                "CASE WHEN EXISTS (SELECT 1 FROM actions a WHERE a.incident_id=p.incident_id "
                "AND a.status IN ('awaiting_approval','policy_blocked')) THEN 'awaiting_approval' "
                "WHEN COALESCE(p.requires_approval,0)=1 THEN 'awaiting_approval' ELSE 'approved' END) "
                "WHERE p.status='remediating' "
                "AND NOT EXISTS (SELECT 1 FROM actions active WHERE active.incident_id=p.incident_id "
                "AND active.status IN ('pending','dispatching','executor_accepted','running','verifying','rolling_back'))"
            )
        )

        return len(rebuilt_ids)

    @staticmethod
    def _incident_group_cursor(
        row: IncidentCorrelationOwnershipRecord,
        direction: str,
        filter_fingerprint: str,
    ) -> str:
        payload = json.dumps(
            {
                "at": row.first_seen_at.isoformat(),
                "id": str(row.id),
                "direction": direction,
                "filter": filter_fingerprint,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    async def list_unified_inbox(
        self,
        *,
        tenant_id: str,
        limit: int = 25,
        cursor: str | None = None,
        project_id: str | None = None,
        risk_tier: str | None = None,
        execution_mode: str | None = None,
        transport_provider: str | None = None,
        status: str | None = None,
        service: str | None = None,
        inbox_view: str = "all",
        record_type: str = "all",
        severity: str | None = None,
    ) -> dict[str, Any]:
        """Return a snapshot-consistent, database-filtered incident and alert feed."""
        tenant_id = self._require("tenant_id", tenant_id)
        safe_limit = max(1, min(int(limit), 100))
        normalized = {
            "tenant_id": tenant_id,
            "project_id": str(project_id or "").strip().lower(),
            "risk_tier": str(risk_tier or "").strip().lower(),
            "execution_mode": str(execution_mode or "").strip().lower(),
            "transport_provider": str(transport_provider or "").strip().lower(),
            "status": str(status or "").strip().lower(),
            "service": str(service or "").strip().lower(),
            "inbox_view": str(inbox_view or "all").strip().lower(),
            "record_type": str(record_type or "all").strip().lower(),
            "severity": str(severity or "").strip().lower(),
        }
        views = ("all", "needs_me", "kai_handling", "critical", "watching", "resolved")
        if normalized["inbox_view"] not in views:
            raise ValueError("Unsupported inbox view")
        if normalized["record_type"] not in {"all", "incidents", "alerts"}:
            raise ValueError("Unsupported inbox record type")
        fingerprint = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        snapshot = datetime.now(UTC)
        cursor_score: int | None = None
        cursor_at: datetime | None = None
        cursor_id: UUID | None = None
        if cursor:
            try:
                padding = "=" * (-len(cursor) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
                if decoded.get("filter") != fingerprint:
                    raise ValueError("filter mismatch")
                snapshot = datetime.fromisoformat(str(decoded["snapshot"]).replace("Z", "+00:00"))
                cursor_score = int(decoded["score"])
                cursor_at = datetime.fromisoformat(str(decoded["at"]).replace("Z", "+00:00"))
                cursor_id = UUID(str(decoded["id"]))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError("Invalid unified inbox cursor") from exc

        terminal = ("closed", "resolved", "recovered", "cancelled", "canceled")
        attention = (
            "failed",
            "blocked",
            "manual_intervention",
            "validation_failed",
            "rollback_failed",
            "awaiting_approval",
            "pending_approval",
            "approval_required",
        )
        latest_generation = (
            select(
                IncidentCorrelationOwnershipRecord.correlation_family_id.label("family_id"),
                func.max(IncidentCorrelationOwnershipRecord.correlation_generation).label("generation"),
            )
            .where(IncidentCorrelationOwnershipRecord.tenant_id == tenant_id)
            .group_by(IncidentCorrelationOwnershipRecord.correlation_family_id)
            .subquery()
        )
        incident_score = case(
            (IncidentCorrelationOwnershipRecord.lifecycle_state.in_(attention), 200), else_=100,
        ) + case((func.lower(func.coalesce(IncidentProjectionRecord.severity, "")) == "critical", 80), else_=0)
        incident_query = (
            select(
                literal("incident").label("record_type"),
                IncidentCorrelationOwnershipRecord.canonical_incident_id.label("record_id"),
                IncidentCorrelationOwnershipRecord.last_seen_at.label("observed_at"),
                incident_score.label("score"),
                IncidentCorrelationOwnershipRecord.lifecycle_state.label("row_status"),
                func.lower(func.coalesce(IncidentProjectionRecord.severity, "")).label("row_severity"),
            )
            .join(latest_generation, and_(
                latest_generation.c.family_id == IncidentCorrelationOwnershipRecord.correlation_family_id,
                latest_generation.c.generation == IncidentCorrelationOwnershipRecord.correlation_generation,
            ))
            .outerjoin(IncidentProjectionRecord, and_(
                IncidentProjectionRecord.incident_id == IncidentCorrelationOwnershipRecord.canonical_incident_id,
                IncidentProjectionRecord.tenant_id == tenant_id,
            ))
            .where(
                IncidentCorrelationOwnershipRecord.tenant_id == tenant_id,
                IncidentCorrelationOwnershipRecord.last_seen_at <= snapshot,
            )
        )
        if normalized["project_id"]:
            incident_query = incident_query.where(
                func.lower(IncidentCorrelationOwnershipRecord.project_id) == normalized["project_id"]
            )
        if normalized["service"]:
            incident_query = incident_query.where(
                func.lower(IncidentCorrelationOwnershipRecord.service) == normalized["service"]
            )
        if normalized["status"]:
            incident_query = incident_query.where(
                func.lower(IncidentCorrelationOwnershipRecord.lifecycle_state) == normalized["status"]
            )
        if normalized["severity"]:
            incident_query = incident_query.where(
                func.lower(IncidentProjectionRecord.severity) == normalized["severity"]
            )
        projection_filters = (
            ("risk_tier", IncidentProjectionRecord.risk_tier),
            ("execution_mode", IncidentProjectionRecord.execution_mode),
            ("transport_provider", IncidentProjectionRecord.transport_provider),
        )
        for field, column in projection_filters:
            if normalized[field]:
                incident_query = incident_query.where(func.lower(column) == normalized[field])

        alert_project = func.lower(
            func.coalesce(
                AlertRecord.payload["project_id"].as_string(),
                AlertRecord.payload["project"].as_string(),
                "",
            )
        )
        alert_score = case((func.lower(AlertRecord.severity) == "critical", 175), else_=75)
        alert_query = select(
            literal("alert").label("record_type"), AlertRecord.id.label("record_id"),
            AlertRecord.created_at.label("observed_at"), alert_score.label("score"),
            literal("open").label("row_status"), func.lower(AlertRecord.severity).label("row_severity"),
        ).where(
            AlertRecord.tenant_id == tenant_id,
            AlertRecord.created_at <= snapshot,
            ~exists(select(IncidentOccurrenceRecord.id).where(and_(
                IncidentOccurrenceRecord.tenant_id == tenant_id,
                IncidentOccurrenceRecord.occurrence_id == AlertRecord.id,
            ))),
        )
        if normalized["project_id"]:
            alert_query = alert_query.where(alert_project == normalized["project_id"])
        if normalized["service"]:
            alert_query = alert_query.where(func.lower(AlertRecord.service) == normalized["service"])
        if normalized["severity"]:
            alert_query = alert_query.where(func.lower(AlertRecord.severity) == normalized["severity"])
        if normalized["status"] and normalized["status"] != "open":
            alert_query = alert_query.where(literal(False))
        if any(normalized[key] for key in ("risk_tier", "execution_mode", "transport_provider")):
            alert_query = alert_query.where(literal(False))

        selected = []
        if normalized["record_type"] in {"all", "incidents"}:
            selected.append(incident_query)
        if normalized["record_type"] in {"all", "alerts"}:
            selected.append(alert_query)
        candidates = (selected[0] if len(selected) == 1 else union_all(*selected)).subquery()

        def view_clause(view: str):
            is_incident = candidates.c.record_type == "incident"
            is_terminal = candidates.c.row_status.in_(terminal)
            is_attention = candidates.c.row_status.in_(attention)
            if view == "needs_me":
                return or_(
                    and_(is_incident, is_attention),
                    and_(
                        ~is_incident,
                        candidates.c.row_severity.in_(("critical", "high", "p1", "p2", "sev1", "sev2")),
                    ),
                )
            if view == "kai_handling":
                return and_(~is_terminal, or_(~is_incident, ~is_attention))
            if view == "critical":
                return and_(~is_terminal, candidates.c.row_severity.in_(("critical", "p1", "sev1")))
            if view == "watching":
                return and_(~is_terminal, candidates.c.row_severity.in_(("medium", "warning", "low", "info")))
            if view == "resolved":
                return and_(is_incident, is_terminal)
            return literal(True)

        total_count = int((await self.session.scalar(select(func.count()).select_from(candidates))) or 0)
        view_counts = {
            view: int(
                (await self.session.scalar(select(func.count()).select_from(candidates).where(view_clause(view))))
                or 0
            )
            for view in views
        }
        page_query = select(candidates).where(view_clause(normalized["inbox_view"]))
        if cursor_score is not None and cursor_at is not None and cursor_id is not None:
            page_query = page_query.where(or_(
                candidates.c.observed_at < cursor_at,
                and_(candidates.c.observed_at == cursor_at, candidates.c.score < cursor_score),
                and_(
                    candidates.c.observed_at == cursor_at,
                    candidates.c.score == cursor_score,
                    candidates.c.record_id < cursor_id,
                ),
            ))
        page_rows = (await self.session.execute(page_query.order_by(
            candidates.c.observed_at.desc(), candidates.c.score.desc(), candidates.c.record_id.desc(),
        ).limit(safe_limit + 1))).mappings().all()
        has_more = len(page_rows) > safe_limit
        page_rows = page_rows[:safe_limit]
        incident_ids = [row["record_id"] for row in page_rows if row["record_type"] == "incident"]
        alert_ids = [row["record_id"] for row in page_rows if row["record_type"] == "alert"]
        projections = await self.list_incident_projections(
            limit=safe_limit,
            tenant_id=tenant_id,
            include_enrichment=False,
            incident_ids=incident_ids,
        )
        projection_by_id = {str(row.get("incident_id") or row.get("id")): row for row in projections}
        alert_rows = (
            (await self.session.execute(select(AlertRecord).where(AlertRecord.id.in_(alert_ids)))).scalars().all()
            if alert_ids
            else []
        )
        alert_by_id = {
            str(row.id): {
                **dict(row.payload or {}),
                "id": str(row.id),
                "alert_id": str(row.id),
                "service": row.service,
                "environment": row.environment,
                "severity": row.severity,
                "source": row.source,
                "created_at": row.created_at.isoformat(),
            }
            for row in alert_rows
        }
        rows = []
        for item in page_rows:
            record_id = str(item["record_id"])
            row = (
                dict(projection_by_id.get(record_id, {}))
                if item["record_type"] == "incident"
                else dict(alert_by_id.get(record_id, {}))
            )
            row.setdefault("id", record_id)
            if item["record_type"] == "incident":
                row.update({"incident_id": record_id, "status": item["row_status"]})
            rows.append(
                {
                    "record_type": item["record_type"],
                    "score": int(item["score"]),
                    "observed_at": item["observed_at"].isoformat(),
                    "row": row,
                }
            )

        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            payload = json.dumps(
                {
                    "filter": fingerprint,
                    "snapshot": snapshot.isoformat(),
                    "score": int(last["score"]),
                    "at": last["observed_at"].isoformat(),
                    "id": str(last["record_id"]),
                },
                separators=(",", ":"),
            ).encode()
            next_cursor = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        return {
            "rows": rows,
            "next_cursor": next_cursor,
            "previous_cursor": None,
            "total_count": total_count,
            "filtered_count": total_count,
            "view_counts": view_counts,
            "snapshot_at": snapshot.isoformat(),
        }

    async def list_incident_groups(
        self,
        *,
        tenant_id: str,
        limit: int = 25,
        cursor: str | None = None,
        status: str | None = None,
        service: str | None = None,
        risk_tier: str | None = None,
        execution_mode: str | None = None,
    ) -> dict[str, Any]:
        """Return canonical correlation families before applying cursor pagination."""
        tenant_id = self._require("tenant_id", tenant_id)
        safe_limit = max(1, min(int(limit), 10000))
        terminal = ("closed", "resolved", "cancelled", "canceled")
        attention = ("failed", "blocked", "awaiting_approval", "pending_approval", "approval_required")
        filter_fingerprint = hashlib.sha256(json.dumps({
            "tenant_id": tenant_id,
            "status": str(status or "").strip().lower(),
            "service": str(service or "").strip(),
            "risk_tier": str(risk_tier or "").strip().lower(),
            "execution_mode": str(execution_mode or "").strip().lower(),
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        latest_generation = (
            select(
                IncidentCorrelationOwnershipRecord.correlation_family_id.label("family_id"),
                func.max(IncidentCorrelationOwnershipRecord.correlation_generation).label("generation"),
            )
            .where(IncidentCorrelationOwnershipRecord.tenant_id == tenant_id)
            .group_by(IncidentCorrelationOwnershipRecord.correlation_family_id)
            .subquery()
        )

        def scoped_query(*, apply_filters: bool):
            query = (
                select(IncidentCorrelationOwnershipRecord)
                .join(
                    latest_generation,
                    and_(
                        latest_generation.c.family_id == IncidentCorrelationOwnershipRecord.correlation_family_id,
                        latest_generation.c.generation == IncidentCorrelationOwnershipRecord.correlation_generation,
                    ),
                )
                .outerjoin(
                    IncidentProjectionRecord,
                    IncidentProjectionRecord.incident_id == IncidentCorrelationOwnershipRecord.canonical_incident_id,
                )
                .where(IncidentCorrelationOwnershipRecord.tenant_id == tenant_id)
            )
            if apply_filters:
                if status:
                    query = query.where(IncidentCorrelationOwnershipRecord.lifecycle_state == status.strip().lower())
                if service:
                    query = query.where(IncidentCorrelationOwnershipRecord.service == service.strip())
                if risk_tier:
                    query = query.where(IncidentProjectionRecord.risk_tier == risk_tier.strip().lower())
                if execution_mode:
                    query = query.where(IncidentProjectionRecord.execution_mode == execution_mode.strip().lower())
            return query

        total_count = int(
            (await self.session.scalar(select(func.count()).select_from(scoped_query(apply_filters=False).subquery())))
            or 0
        )
        filtered_count = int(
            (await self.session.scalar(select(func.count()).select_from(scoped_query(apply_filters=True).subquery())))
            or 0
        )
        active_count = int((await self.session.scalar(
            select(func.count()).select_from(
                scoped_query(apply_filters=False)
                .where(IncidentCorrelationOwnershipRecord.lifecycle_state.not_in(terminal))
                .subquery()
            )
        )) or 0)
        needs_attention_count = int((await self.session.scalar(
            select(func.count()).select_from(
                scoped_query(apply_filters=False)
                .where(IncidentCorrelationOwnershipRecord.lifecycle_state.in_(attention))
                .subquery()
            )
        )) or 0)
        unlinked_signal_count = int((await self.session.scalar(
            select(func.count(AlertRecord.id))
            .select_from(AlertRecord)
            .outerjoin(
                IncidentOccurrenceRecord,
                and_(
                    IncidentOccurrenceRecord.tenant_id == AlertRecord.tenant_id,
                    IncidentOccurrenceRecord.occurrence_id == AlertRecord.id,
                ),
            )
            .where(AlertRecord.tenant_id == tenant_id, IncidentOccurrenceRecord.id.is_(None))
        )) or 0)

        # Expand/backfill/cutover safety: deployments can contain durable
        # incident projections before canonical ownership has been backfilled.
        # Keep those incidents visible instead of presenting an empty inbox.
        # The explicit legacy scope prevents unverified project attribution.
        if total_count == 0:
            legacy_rows = await self.list_incident_projections(
                limit=safe_limit,
                tenant_id=tenant_id,
                include_enrichment=False,
                risk_tier=risk_tier,
                execution_mode=execution_mode,
                status=status,
                service=service,
            )
            projection_scope = select(IncidentProjectionRecord).where(
                IncidentProjectionRecord.tenant_id == tenant_id
            )
            filtered_scope = projection_scope
            if status:
                filtered_scope = filtered_scope.where(
                    IncidentProjectionRecord.status == status.strip().lower()
                )
            if service:
                filtered_scope = filtered_scope.where(IncidentProjectionRecord.service == service.strip())
            if risk_tier:
                filtered_scope = filtered_scope.where(
                    IncidentProjectionRecord.risk_tier == risk_tier.strip().lower()
                )
            if execution_mode:
                filtered_scope = filtered_scope.where(
                    IncidentProjectionRecord.execution_mode == execution_mode.strip().lower()
                )
            legacy_total = int((await self.session.scalar(
                select(func.count()).select_from(projection_scope.subquery())
            )) or 0)
            legacy_filtered = int((await self.session.scalar(
                select(func.count()).select_from(filtered_scope.subquery())
            )) or 0)
            legacy_active = int((await self.session.scalar(
                select(func.count()).select_from(
                    projection_scope.where(IncidentProjectionRecord.status.not_in(terminal)).subquery()
                )
            )) or 0)
            legacy_attention = int((await self.session.scalar(
                select(func.count()).select_from(
                    projection_scope.where(IncidentProjectionRecord.status.in_(attention)).subquery()
                )
            )) or 0)
            response_rows = []
            for projection in legacy_rows:
                incident_id = str(projection.get("incident_id") or projection.get("id") or "")
                lifecycle = str(projection.get("status") or "open").strip().lower()
                first_seen = str(
                    projection.get("first_seen_at")
                    or projection.get("created_at")
                    or projection.get("latest_event_at")
                    or datetime.now(UTC).isoformat()
                )
                last_seen = str(projection.get("latest_event_at") or projection.get("updated_at") or first_seen)
                projection.update({
                    "canonical_incident_id": incident_id,
                    "incident_id": incident_id,
                    "correlation_family_id": str(uuid5(NAMESPACE_URL, f"kaims-legacy:{tenant_id}:{incident_id}")),
                    "generation": 1,
                    "correlation_generation": 1,
                    "canonical_status": lifecycle,
                    "status": lifecycle,
                    "active_occurrence_count": 0,
                    "total_occurrence_count": 0,
                    "first_seen_at": first_seen,
                    "last_seen_at": last_seen,
                    "latest_occurrences": [],
                    "terminal_history_count": 1 if lifecycle in terminal else 0,
                    "attention_state": (
                        "needs_attention" if lifecycle in attention
                        else "active" if lifecycle not in terminal else "terminal"
                    ),
                    "project_id": "legacy-unassigned",
                    "needs_scope_review": True,
                    "correlation_backfill_status": "pending",
                })
                response_rows.append(projection)
            return {
                "rows": response_rows,
                "next_cursor": None,
                "previous_cursor": None,
                "total_count": legacy_total,
                "filtered_count": legacy_filtered,
                "active_count": legacy_active,
                "needs_attention_count": legacy_attention,
                "unlinked_signal_count": unlinked_signal_count,
                "migration_state": "legacy_fallback",
                "generated_at": datetime.now(UTC).isoformat(),
            }

        direction = "next"
        cursor_at: datetime | None = None
        cursor_id: UUID | None = None
        if cursor:
            try:
                padding = "=" * (-len(cursor) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
                cursor_at = datetime.fromisoformat(str(decoded["at"]).replace("Z", "+00:00"))
                cursor_id = UUID(str(decoded["id"]))
                direction = "previous" if decoded.get("direction") == "previous" else "next"
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError("Invalid incident group cursor") from exc
            if decoded.get("filter") != filter_fingerprint:
                raise ValueError("Incident group cursor does not match the active filters")

        page_query = scoped_query(apply_filters=True)
        if cursor_at is not None and cursor_id is not None:
            if direction == "previous":
                page_query = page_query.where(or_(
                    IncidentCorrelationOwnershipRecord.first_seen_at > cursor_at,
                    and_(
                        IncidentCorrelationOwnershipRecord.first_seen_at == cursor_at,
                        IncidentCorrelationOwnershipRecord.id > cursor_id,
                    ),
                ))
            else:
                page_query = page_query.where(or_(
                    IncidentCorrelationOwnershipRecord.first_seen_at < cursor_at,
                    and_(
                        IncidentCorrelationOwnershipRecord.first_seen_at == cursor_at,
                        IncidentCorrelationOwnershipRecord.id < cursor_id,
                    ),
                ))
        if direction == "previous":
            page_query = page_query.order_by(
                IncidentCorrelationOwnershipRecord.first_seen_at.asc(),
                IncidentCorrelationOwnershipRecord.id.asc(),
            )
        else:
            page_query = page_query.order_by(
                IncidentCorrelationOwnershipRecord.first_seen_at.desc(),
                IncidentCorrelationOwnershipRecord.id.desc(),
            )
        ownership_rows = list((await self.session.execute(page_query.limit(safe_limit + 1))).scalars().all())
        has_more = len(ownership_rows) > safe_limit
        ownership_rows = ownership_rows[:safe_limit]
        if direction == "previous":
            ownership_rows.reverse()

        canonical_ids = [row.canonical_incident_id for row in ownership_rows]
        projections = await self.list_incident_projections(
            limit=safe_limit,
            tenant_id=tenant_id,
            include_enrichment=False,
            incident_ids=canonical_ids,
        )
        projection_by_id = {str(row.get("incident_id") or row.get("id")): row for row in projections}
        occurrence_counts: dict[UUID, int] = {}
        occurrences_by_incident: dict[UUID, list[dict[str, Any]]] = {}
        terminal_history: dict[UUID, int] = {}
        if canonical_ids:
            count_rows = await self.session.execute(
                select(IncidentOccurrenceRecord.canonical_incident_id, func.count(IncidentOccurrenceRecord.id))
                .where(IncidentOccurrenceRecord.canonical_incident_id.in_(canonical_ids))
                .group_by(IncidentOccurrenceRecord.canonical_incident_id)
            )
            occurrence_counts = {incident_id: int(count) for incident_id, count in count_rows.all()}
            occurrence_rows = (
                await self.session.execute(
                    select(IncidentOccurrenceRecord)
                    .where(IncidentOccurrenceRecord.canonical_incident_id.in_(canonical_ids))
                    .order_by(IncidentOccurrenceRecord.observed_at.desc(), IncidentOccurrenceRecord.id.desc())
                )
            ).scalars().all()
            for occurrence in occurrence_rows:
                bucket = occurrences_by_incident.setdefault(occurrence.canonical_incident_id, [])
                if len(bucket) < 5:
                    bucket.append({
                        "occurrence_id": str(occurrence.occurrence_id),
                        "observed_at": occurrence.observed_at.isoformat(),
                        "idempotency_key": occurrence.idempotency_key,
                    })
            family_ids = [row.correlation_family_id for row in ownership_rows]
            history_rows = await self.session.execute(
                select(
                    IncidentCorrelationOwnershipRecord.correlation_family_id,
                    func.count(IncidentCorrelationOwnershipRecord.id),
                )
                .where(
                    IncidentCorrelationOwnershipRecord.correlation_family_id.in_(family_ids),
                    IncidentCorrelationOwnershipRecord.lifecycle_state.in_(terminal),
                )
                .group_by(IncidentCorrelationOwnershipRecord.correlation_family_id)
            )
            terminal_history = {family_id: int(count) for family_id, count in history_rows.all()}

        response_rows: list[dict[str, Any]] = []
        for ownership in ownership_rows:
            projection = dict(projection_by_id.get(str(ownership.canonical_incident_id), {}))
            count = occurrence_counts.get(ownership.canonical_incident_id, 0)
            lifecycle = str(ownership.lifecycle_state or "").lower()
            projection.update({
                "canonical_incident_id": str(ownership.canonical_incident_id),
                "incident_id": str(ownership.canonical_incident_id),
                "correlation_family_id": str(ownership.correlation_family_id),
                "generation": ownership.correlation_generation,
                "correlation_generation": ownership.correlation_generation,
                "canonical_status": lifecycle,
                "status": lifecycle,
                "active_occurrence_count": count if lifecycle not in terminal else 0,
                "total_occurrence_count": count,
                "first_seen_at": ownership.first_seen_at.isoformat(),
                "last_seen_at": ownership.last_seen_at.isoformat(),
                "latest_occurrences": occurrences_by_incident.get(ownership.canonical_incident_id, []),
                "terminal_history_count": terminal_history.get(ownership.correlation_family_id, 0),
                "attention_state": (
                    "needs_attention"
                    if lifecycle in attention
                    else "active"
                    if lifecycle not in terminal
                    else "terminal"
                ),
                "project_id": ownership.project_id,
                "service": ownership.service,
                "environment": ownership.environment,
            })
            response_rows.append(projection)

        next_cursor = None
        previous_cursor = None
        if ownership_rows:
            if direction == "next" and has_more:
                next_cursor = self._incident_group_cursor(ownership_rows[-1], "next", filter_fingerprint)
            elif direction == "previous" or cursor:
                next_cursor = self._incident_group_cursor(ownership_rows[-1], "next", filter_fingerprint)
            if cursor or direction == "previous":
                previous_cursor = self._incident_group_cursor(ownership_rows[0], "previous", filter_fingerprint)
        return {
            "rows": response_rows,
            "next_cursor": next_cursor,
            "previous_cursor": previous_cursor,
            "total_count": total_count,
            "filtered_count": filtered_count,
            "active_count": active_count,
            "needs_attention_count": needs_attention_count,
            "unlinked_signal_count": unlinked_signal_count,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    async def list_incident_projections(
        self,
        *,
        limit: int = 100,
        tenant_id: str | None = None,
        include_enrichment: bool = True,
        risk_tier: str | None = None,
        execution_mode: str | None = None,
        transport_provider: str | None = None,
        status: str | None = None,
        service: str | None = None,
        incident_id: str | None = None,
        incident_ids: list[UUID] | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 10000))
        # Apply ordering and the limit to narrow scalar columns before loading
        # projection_payload. On databases that drifted without the updated_at
        # index, sorting full JSON-bearing rows can exhaust MySQL's sort buffer.
        latest_stmt = select(
            IncidentProjectionRecord.incident_id.label("incident_id"),
            IncidentProjectionRecord.updated_at.label("updated_at"),
        )
        if tenant_id is not None:
            latest_stmt = latest_stmt.where(
                IncidentProjectionRecord.tenant_id == self._require("tenant_id", tenant_id)
            )
        if incident_id:
            parsed_incident_id = self._parse_uuid(incident_id)
            if parsed_incident_id is None:
                return []
            latest_stmt = latest_stmt.where(IncidentProjectionRecord.incident_id == parsed_incident_id)
        if incident_ids is not None:
            if not incident_ids:
                return []
            latest_stmt = latest_stmt.where(IncidentProjectionRecord.incident_id.in_(incident_ids))
        if risk_tier:
            latest_stmt = latest_stmt.where(
                IncidentProjectionRecord.risk_tier == str(risk_tier).strip().lower()
            )
        if execution_mode:
            latest_stmt = latest_stmt.where(
                IncidentProjectionRecord.execution_mode == str(execution_mode).strip().lower()
            )
        if transport_provider:
            latest_stmt = latest_stmt.where(
                IncidentProjectionRecord.transport_provider == str(transport_provider).strip().lower()
            )
        if service:
            latest_stmt = latest_stmt.where(IncidentProjectionRecord.service == str(service).strip())
        # Status is intentionally filtered after lifecycle reduction below. The
        # projection value can lag a newer approval or remediation action, and
        # filtering it here would make the summary omit incidents whose visible
        # canonical status matches the requested filter.
        query_limit = 1000 if status else safe_limit
        latest = latest_stmt.order_by(IncidentProjectionRecord.updated_at.desc()).limit(query_limit).subquery()
        stmt = (
            select(IncidentProjectionRecord)
            .join(latest, IncidentProjectionRecord.incident_id == latest.c.incident_id)
            .order_by(latest.c.updated_at.desc())
        )
        if not include_enrichment:
            # Inbox/dashboard reads must never hydrate multi-megabyte context
            # JSON for every row. The opened incident performs a separate,
            # exact enriched read.
            stmt = stmt.options(
                load_only(
                    IncidentProjectionRecord.incident_id,
                    IncidentProjectionRecord.alert_id,
                    IncidentProjectionRecord.trace_id,
                    IncidentProjectionRecord.recommendation_id,
                    IncidentProjectionRecord.flow_id,
                    IncidentProjectionRecord.tenant_id,
                    IncidentProjectionRecord.service,
                    IncidentProjectionRecord.environment,
                    IncidentProjectionRecord.severity,
                    IncidentProjectionRecord.status,
                    IncidentProjectionRecord.owner,
                    IncidentProjectionRecord.risk_tier,
                    IncidentProjectionRecord.execution_mode,
                    IncidentProjectionRecord.requires_approval,
                    IncidentProjectionRecord.policy_version,
                    IncidentProjectionRecord.policy_reason,
                    IncidentProjectionRecord.transport_provider,
                    IncidentProjectionRecord.latest_event_id,
                    IncidentProjectionRecord.latest_event_type,
                    IncidentProjectionRecord.latest_event_at,
                    IncidentProjectionRecord.first_seen_at,
                    IncidentProjectionRecord.document_available,
                    IncidentProjectionRecord.updated_at,
                )
            )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        ticket_by_incident: dict[UUID, str] = {}
        canonical_status_by_incident: dict[UUID, str] = {}
        canonical_updated_at_by_incident: dict[UUID, datetime] = {}
        canonical_alert_by_incident: dict[UUID, UUID] = {}
        projection_incident_ids = [row.incident_id for row in rows]
        if projection_incident_ids:
            ticket_result = await self.session.execute(
                select(IncidentRecord.id, IncidentRecord.ticket_id, IncidentRecord.status, IncidentRecord.updated_at).where(
                    IncidentRecord.id.in_(projection_incident_ids)
                )
            )
            incident_rows = ticket_result.all()
            ticket_by_incident = {
                incident_id: str(ticket_id).strip()
                for incident_id, ticket_id, _incident_status, _updated_at in incident_rows
                if str(ticket_id or "").strip()
            }
            canonical_status_by_incident = {
                incident_id: str(incident_status).strip().lower()
                for incident_id, _ticket_id, incident_status, _updated_at in incident_rows
                if str(incident_status or "").strip()
            }
            canonical_updated_at_by_incident = {
                incident_id: updated_at
                for incident_id, _ticket_id, _incident_status, updated_at in incident_rows
                if updated_at is not None
            }
            # Older projections predate the alert_id projection column, while
            # their immutable incident events still retain the canonical alert
            # relationship. Recover it in the read model so every incident
            # opens the same guided cockpit without rewriting production data.
            alert_event_result = await self.session.execute(
                select(IncidentEventRecord.incident_id, IncidentEventRecord.alert_id)
                .where(
                    IncidentEventRecord.incident_id.in_(projection_incident_ids),
                    IncidentEventRecord.alert_id.is_not(None),
                )
                .order_by(IncidentEventRecord.created_at.desc())
            )
            for incident_id, alert_id in alert_event_result.all():
                if alert_id is not None:
                    canonical_alert_by_incident.setdefault(incident_id, alert_id)

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

        action_by_incident: dict[UUID, ActionRecord] = {}
        incident_ids = [row.incident_id for row in rows]
        if incident_ids:
            action_stmt = (
                select(ActionRecord)
                .where(ActionRecord.incident_id.in_(incident_ids))
                .order_by(ActionRecord.updated_at.desc(), ActionRecord.created_at.desc())
            )
            if not include_enrichment:
                action_stmt = action_stmt.options(
                    load_only(
                        ActionRecord.id,
                        ActionRecord.incident_id,
                        ActionRecord.status,
                        ActionRecord.updated_at,
                        ActionRecord.created_at,
                    )
                )
            action_result = await self.session.execute(action_stmt)
            for action in action_result.scalars().all():
                action_by_incident.setdefault(action.incident_id, action)

        approval_by_incident: dict[UUID, ApprovalRecord] = {}
        if incident_ids:
            approval_result = await self.session.execute(
                select(ApprovalRecord)
                .where(ApprovalRecord.incident_id.in_(incident_ids))
                .order_by(ApprovalRecord.updated_at.desc(), ApprovalRecord.created_at.desc())
                .options(
                    load_only(
                        ApprovalRecord.id,
                        ApprovalRecord.incident_id,
                        ApprovalRecord.decision,
                        ApprovalRecord.updated_at,
                        ApprovalRecord.created_at,
                    )
                )
            )
            for approval in approval_result.scalars().all():
                approval_by_incident.setdefault(approval.incident_id, approval)

        evaluation_by_incident: dict[UUID, EvaluationRecord] = {}
        if include_enrichment and incident_ids:
            evaluation_result = await self.session.execute(
                select(EvaluationRecord)
                .where(EvaluationRecord.incident_id.in_(incident_ids))
                .order_by(EvaluationRecord.created_at.desc())
            )
            for evaluation in evaluation_result.scalars().all():
                evaluation_by_incident.setdefault(evaluation.incident_id, evaluation)

        source_alert_by_id: dict[UUID, dict[str, Any]] = {}
        if incident_ids:
            source_alert_ids = {
                row.alert_id or canonical_alert_by_incident.get(row.incident_id)
                for row in rows
                if row.alert_id is not None or canonical_alert_by_incident.get(row.incident_id) is not None
            }
            if source_alert_ids:
                source_alert_result = await self.session.execute(
                    select(AlertRecord).where(AlertRecord.id.in_(source_alert_ids))
                )
                for alert_record in source_alert_result.scalars().all():
                    alert_payload = (
                        dict(alert_record.payload)
                        if isinstance(alert_record.payload, dict)
                        else {}
                    )
                    alert_payload.setdefault("id", str(alert_record.id))
                    alert_payload.setdefault("source", alert_record.source)
                    alert_payload.setdefault("name", alert_record.name)
                    alert_payload.setdefault("service", alert_record.service)
                    alert_payload.setdefault("environment", alert_record.environment)
                    alert_payload.setdefault("severity", alert_record.severity)
                    alert_payload.setdefault("fingerprint", alert_record.fingerprint)
                    alert_payload.setdefault("correlation_id", alert_record.correlation_id)
                    source_alert_by_id[alert_record.id] = alert_payload

        historical_context_event_by_incident: dict[UUID, dict[str, Any]] = {}
        if include_enrichment and incident_ids:
            historical_context_result = await self.session.execute(
                select(IncidentEventRecord.incident_id, IncidentEventRecord.payload)
                .where(
                    IncidentEventRecord.incident_id.in_(incident_ids),
                    IncidentEventRecord.event_type == "incident.context.collected",
                )
                .order_by(IncidentEventRecord.created_at.desc())
            )
            for historical_incident_id, historical_payload in historical_context_result.all():
                if isinstance(historical_payload, dict):
                    historical_context_event_by_incident.setdefault(
                        historical_incident_id,
                        dict(historical_payload),
                    )

        recommendation_by_id: dict[UUID, dict[str, Any]] = {}
        recommendation_ids = [row.recommendation_id for row in rows if row.recommendation_id is not None]
        if include_enrichment and recommendation_ids:
            recommendation_result = await self.session.execute(
                select(AuditLogRecord).where(
                    AuditLogRecord.id.in_(recommendation_ids),
                    AuditLogRecord.action == "recommendation.generated",
                )
            )
            recommendation_by_id = {
                record.id: dict(record.payload or {})
                for record in recommendation_result.scalars().all()
            }

        context_snapshot_by_id: dict[str, ContextSnapshotRecord] = {}
        referenced_snapshot_ids: set[UUID] = set()
        for recommendation_payload in recommendation_by_id.values():
            metadata = (
                recommendation_payload.get("metadata")
                if isinstance(recommendation_payload.get("metadata"), dict)
                else {}
            )
            snapshot_uuid = self._parse_uuid(metadata.get("context_snapshot_id"))
            if snapshot_uuid is not None:
                referenced_snapshot_ids.add(snapshot_uuid)
        if include_enrichment and referenced_snapshot_ids:
            context_snapshot_result = await self.session.execute(
                select(ContextSnapshotRecord).where(ContextSnapshotRecord.snapshot_id.in_(referenced_snapshot_ids))
            )
            context_snapshot_by_id = {
                str(snapshot.snapshot_id): snapshot for snapshot in context_snapshot_result.scalars().all()
            }

        response_rows: list[dict[str, Any]] = []
        for row in rows:
            canonical_alert_id = row.alert_id or canonical_alert_by_incident.get(row.incident_id)
            # An immutable incident event can outlive (or predate) its durable
            # AlertRecord.  Such an identity is useful provenance, but it is
            # not a navigable alert contract: processed-result and analysis
            # regeneration are both keyed by a tenant-scoped AlertRecord.
            # Never advertise a dead alert link from incident metadata.
            navigable_alert_id = (
                canonical_alert_id
                if canonical_alert_id is not None and canonical_alert_id in source_alert_by_id
                else None
            )
            pending = pending_by_incident.get(row.incident_id)
            merged_recommendation_id = row.recommendation_id or (pending.recommendation_id if pending is not None else None)
            recommendation_payload = recommendation_by_id.get(merged_recommendation_id, {})
            recommendation_metadata = (
                recommendation_payload.get("metadata")
                if isinstance(recommendation_payload.get("metadata"), dict)
                else {}
            )
            merged_flow_id = row.flow_id or (pending.flow_id if pending is not None else None)
            projection_payload = dict(row.projection_payload or {}) if include_enrichment else {}
            if recommendation_payload:
                for stale_context_key in ("context", "context_metadata", "context_snapshot"):
                    projection_payload.pop(stale_context_key, None)
            if navigable_alert_id is not None:
                projection_payload["alert_id"] = str(navigable_alert_id)
            else:
                projection_payload.pop("alert_id", None)
            event_payload = (
                projection_payload.get("event_payload")
                if isinstance(projection_payload.get("event_payload"), dict)
                else {}
            )
            historical_context_event = (
                historical_context_event_by_incident.get(row.incident_id, {})
                if not recommendation_payload
                else {}
            )
            event_context = (
                event_payload.get("context")
                if isinstance(event_payload.get("context"), dict)
                else historical_context_event.get("context")
                if isinstance(historical_context_event.get("context"), dict)
                else {}
            )
            if event_context:
                projection_payload.setdefault("context", event_context)
            historical_context_metadata = historical_context_event.get("context_metadata")
            if isinstance(historical_context_metadata, dict) and historical_context_metadata:
                projection_payload.setdefault("context_metadata", historical_context_metadata)
            historical_context_snapshot = historical_context_event.get("context_snapshot")
            if isinstance(historical_context_snapshot, dict) and historical_context_snapshot:
                projection_payload.setdefault("context_snapshot", historical_context_snapshot)
            event_context_alert = (
                event_context.get("alert")
                if isinstance(event_context.get("alert"), dict)
                else {}
            )
            durable_source_alert = source_alert_by_id.get(canonical_alert_id, {}) if canonical_alert_id else {}
            if durable_source_alert:
                projection_payload["source_alert"] = durable_source_alert
            elif event_context_alert:
                projection_payload.setdefault("source_alert", event_context_alert)
            bound_snapshot_id = str(recommendation_metadata.get("context_snapshot_id") or "").strip()
            context_snapshot = context_snapshot_by_id.get(bound_snapshot_id)
            binding_status = "not_applicable"
            if recommendation_payload:
                binding_status = "missing_snapshot_reference" if not bound_snapshot_id else "snapshot_not_found"
            if context_snapshot is not None:
                if context_snapshot.tenant_id != row.tenant_id or str(context_snapshot.incident_id) != str(
                    row.incident_id
                ):
                    context_snapshot = None
                    binding_status = "identity_mismatch"
                elif str(context_snapshot.context_fingerprint) != str(
                    recommendation_metadata.get("context_fingerprint") or ""
                ):
                    context_snapshot = None
                    binding_status = "fingerprint_mismatch"
                else:
                    binding_status = "verified"
            if context_snapshot is not None:
                snapshot_context = (
                    dict(context_snapshot.payload)
                    if isinstance(context_snapshot.payload, dict)
                    else {}
                )
                if snapshot_context:
                    projection_payload["context"] = snapshot_context
                    snapshot_metadata = (
                        snapshot_context.get("metadata")
                        if isinstance(snapshot_context.get("metadata"), dict)
                        else {}
                    )
                    if snapshot_metadata:
                        projection_payload["context_metadata"] = snapshot_metadata
                projection_payload["context_snapshot"] = {
                    "snapshot_id": str(context_snapshot.snapshot_id),
                    "source_incident_id": context_snapshot.source_incident_id,
                    "context_fingerprint": context_snapshot.context_fingerprint,
                    "contract_version": context_snapshot.contract_version,
                    "quality_score": float(context_snapshot.quality_score or 0.0),
                    "reusable": bool(context_snapshot.reusable),
                    "source_manifest": context_snapshot.source_manifest or {},
                    "collected_at": context_snapshot.collected_at,
                    "expires_at": context_snapshot.expires_at,
                }
            projection_payload["investigation_integrity"] = {
                "status": binding_status,
                "recommendation_id": str(merged_recommendation_id) if merged_recommendation_id else None,
                "context_snapshot_id": bound_snapshot_id or None,
            }
            evaluation = evaluation_by_incident.get(row.incident_id)
            if evaluation is not None:
                evaluation_payload = dict(evaluation.report_payload or {})
                projection_payload.setdefault("evaluation", evaluation_payload)
                projection_payload.setdefault(
                    "quality",
                    {
                        "overall_score": evaluation.overall_score,
                        "quality_label": evaluation.quality_label,
                        "requires_review": evaluation.requires_review,
                    },
                )
            action = action_by_incident.get(row.incident_id)
            approval_record = approval_by_incident.get(row.incident_id)
            canonical_status = canonical_status_by_incident.get(row.incident_id, "")
            if action is not None:
                action_status = str(action.status or "").lower()
                if include_enrichment:
                    projection_payload["remediation_action"] = action.payload or {}
                projection_payload["remediation_status"] = action_status

            action_payload = action.payload if include_enrichment and action is not None and isinstance(action.payload, dict) else {}
            lifecycle_candidates = (
                event_payload.get("resolution_lifecycle"),
                (action_payload.get("parameters") or {}).get("resolution_lifecycle") if isinstance(action_payload.get("parameters"), dict) else None,
                (action_payload.get("metadata") or {}).get("resolution_lifecycle") if isinstance(action_payload.get("metadata"), dict) else None,
            )
            resolution_lifecycle = select_current_lifecycle(
                *({"resolution_lifecycle": item} for item in lifecycle_candidates if isinstance(item, dict))
            )
            if resolution_lifecycle:
                projection_payload["resolution_lifecycle"] = resolution_lifecycle

            if recommendation_payload:
                # The projection stores the latest lifecycle event, while the
                # full RCA/recommendation is durably stored in the audit log.
                # Rejoin it into the read model so UI consumers do not have to
                # reconstruct a report from whichever event happened last.
                projection_payload["recommendation"] = recommendation_payload
            elif any(
                event_payload.get(key) is not None
                for key in ("recommended_action", "root_cause", "impact", "risk")
            ):
                projection_payload.setdefault(
                    "recommendation",
                    {
                        "id": event_payload.get("recommendation_id"),
                        "recommended_action": event_payload.get("recommended_action"),
                        "root_cause": event_payload.get("root_cause"),
                        "impact": event_payload.get("impact"),
                        "risk": event_payload.get("risk"),
                        "confidence": event_payload.get("confidence"),
                    },
                )
            orchestration_path = (
                recommendation_metadata.get("orchestration_path")
                if isinstance(recommendation_metadata.get("orchestration_path"), dict)
                else {}
            )
            if not orchestration_path:
                lifecycle_control = (
                    resolution_lifecycle.get("control")
                    if isinstance(resolution_lifecycle, dict) and isinstance(resolution_lifecycle.get("control"), dict)
                    else {}
                )
                disposition = str(lifecycle_control.get("disposition") or "").strip().lower()
                analysis_reused = recommendation_metadata.get("analysis_reused") is True
                diagnostic = "diagnostic" in str(row.execution_mode or "").lower() or disposition in {"watch_only", "investigate"}
                path_id = "diagnostic" if diagnostic else "guided_reuse" if analysis_reused and row.requires_approval else "verified_fast_path" if analysis_reused else "guided" if row.requires_approval else "autonomous"
                labels = {
                    "diagnostic": "Diagnostic completion",
                    "guided_reuse": "Reused analysis with approval",
                    "verified_fast_path": "Verified context fast path",
                    "guided": "Fresh analysis guided path",
                    "autonomous": "Fresh analysis autonomous path",
                }
                orchestration_path = {
                    "schema_version": "kaims.orchestration-path.v1",
                    "id": path_id,
                    "label": labels[path_id],
                    "context_reused": bool(recommendation_metadata.get("context_reused")),
                    "analysis_reused": analysis_reused,
                    "disposition": disposition or ("investigate" if diagnostic else "approval_required" if row.requires_approval else "execution_ready"),
                    "skipped_stages": ["approval", "execution"] if diagnostic else ["context_collection", "rca_generation"] if analysis_reused else ["approval"] if not row.requires_approval else [],
                    "derived_for_legacy_record": True,
                }
            projection_payload["orchestration_path"] = orchestration_path

            approval_payload = projection_payload.get("approval") if isinstance(projection_payload.get("approval"), dict) else {}
            approval_event_payload = projection_payload.get("event_payload") if isinstance(projection_payload.get("event_payload"), dict) else {}
            approval_event_decision = (
                approval_event_payload.get("decision")
                if str(row.latest_event_type or "").strip().lower() == "incident.approval.recorded"
                else None
            )
            approval_status = str(
                (approval_record.decision if approval_record is not None else None)
                or projection_payload.get("approval_status")
                or approval_payload.get("status")
                or approval_payload.get("decision")
                or approval_event_decision
                or ""
            ).strip().lower().replace("-", "_").replace(" ", "_")
            closure_report = event_payload.get("report") if isinstance(event_payload.get("report"), dict) else {}
            closure_metadata = (
                closure_report.get("metadata")
                if isinstance(closure_report.get("metadata"), dict)
                else {}
            )
            lifecycle_validation = (
                resolution_lifecycle.get("validation")
                if isinstance(resolution_lifecycle, dict)
                and isinstance(resolution_lifecycle.get("validation"), dict)
                else {}
            )
            closure_kind = str(closure_metadata.get("closure_kind") or "").strip().lower()
            if not closure_kind and lifecycle_validation.get("administrative_disposition") is True:
                closure_kind = "manual"
            if not closure_kind and str((resolution_lifecycle or {}).get("reason_code") or "").strip().lower() == "watch_only_policy_completed":
                closure_kind = "diagnostic"
            lifecycle_status = reduce_incident_status(
                projection_status=row.status,
                projection_updated_at=row.updated_at,
                canonical_status=canonical_status,
                canonical_updated_at=canonical_updated_at_by_incident.get(row.incident_id),
                approval_status=approval_status,
                approval_updated_at=approval_record.updated_at if approval_record is not None else None,
                action_status=action.status if action is not None else None,
                action_updated_at=action.updated_at if action is not None else None,
                closure_kind=closure_kind,
            )
            projected_status = lifecycle_status["status"]
            projection_payload["status"] = projected_status
            projection_payload["status_source"] = lifecycle_status["source"]
            projection_payload["status_reason"] = lifecycle_status["reason"]

            ticket_id = ticket_by_incident.get(row.incident_id) or projection_payload.get("ticket_id")

            import os
            jira_base = str(os.environ.get("JIRA_URL") or os.environ.get("JIRA_API_BASE_URL") or "").rstrip("/")
            jira_link = f"{jira_base}/browse/{ticket_id}" if (ticket_id and jira_base) else None

            status_lower = str(projected_status or "").strip().lower()
            jira_status = None
            if ticket_id:
                if status_lower in {"closed", "resolved", "done"}:
                    jira_status = "Done"
                elif status_lower in {"pending", "awaiting_approval"}:
                    jira_status = "Awaiting Approval"
                else:
                    jira_status = "In Progress"

            projection_payload["ticket_id"] = ticket_id or None
            projection_payload["jira_link"] = jira_link
            projection_payload["jira_status"] = jira_status
            projection_payload["jira_key"] = ticket_id or None
            projection_payload["jira_url"] = jira_link

            normalized_context = (
                projection_payload.get("context")
                if isinstance(projection_payload.get("context"), dict)
                else {}
            )
            normalized_source_alert = (
                projection_payload.get("source_alert")
                if isinstance(projection_payload.get("source_alert"), dict)
                else {}
            )
            normalized_recommendation = (
                projection_payload.get("recommendation")
                if isinstance(projection_payload.get("recommendation"), dict)
                else {}
            )
            source_labels = (
                normalized_source_alert.get("labels")
                if isinstance(normalized_source_alert.get("labels"), dict)
                else {}
            )
            source_annotations = (
                normalized_source_alert.get("annotations")
                if isinstance(normalized_source_alert.get("annotations"), dict)
                else {}
            )
            source_metadata = (
                normalized_source_alert.get("metadata")
                if isinstance(normalized_source_alert.get("metadata"), dict)
                else {}
            )
            deduplication = (
                source_metadata.get("deduplication")
                if isinstance(source_metadata.get("deduplication"), dict)
                else {}
            )
            root_cause = next(
                (
                    str(value).strip()
                    for value in (
                        normalized_recommendation.get("root_cause"),
                        event_payload.get("root_cause"),
                        projection_payload.get("root_cause"),
                        source_annotations.get("root_cause"),
                    )
                    if str(value or "").strip()
                ),
                None,
            )
            customer_impact = next(
                (
                    str(value).strip()
                    for value in (
                        normalized_recommendation.get("impact"),
                        event_payload.get("impact"),
                        projection_payload.get("customer_impact"),
                        projection_payload.get("business_impact"),
                        source_annotations.get("business_impact"),
                        source_annotations.get("summary"),
                        normalized_source_alert.get("description"),
                    )
                    if str(value or "").strip()
                ),
                None,
            )
            confidence = next(
                (
                    value
                    for value in (
                        normalized_recommendation.get("confidence"),
                        event_payload.get("confidence"),
                        projection_payload.get("confidence"),
                    )
                    if value is not None
                ),
                None,
            )
            deduplicated_count = next(
                (
                    value
                    for value in (
                        normalized_source_alert.get("deduplicated_count"),
                        normalized_source_alert.get("occurrence_count"),
                        event_context_alert.get("deduplicated_count"),
                        event_context_alert.get("occurrence_count"),
                    )
                    if value is not None
                ),
                None,
            )
            deduplication_reason = (
                deduplication.get("reason")
                or deduplication.get("disposition")
                or deduplication.get("match_type")
            )
            if not deduplication_reason:
                try:
                    if int(deduplicated_count or 0) > 1:
                        deduplication_reason = "Correlated monitoring occurrences"
                except (TypeError, ValueError):
                    pass
            source_name = next(
                (
                    str(value).strip()
                    for value in (
                        normalized_source_alert.get("source"),
                        source_labels.get("origin_system"),
                        source_labels.get("transport"),
                    )
                    if str(value or "").strip()
                ),
                None,
            )
            origin_system = next(
                (
                    str(value).strip()
                    for value in (
                        source_labels.get("origin_system"),
                        normalized_source_alert.get("origin_system"),
                        source_name,
                    )
                    if str(value or "").strip()
                ),
                None,
            )
            summary = next(
                (
                    str(value).strip()
                    for value in (
                        source_annotations.get("summary"),
                        normalized_source_alert.get("summary"),
                        normalized_source_alert.get("description"),
                        customer_impact,
                    )
                    if str(value or "").strip()
                ),
                None,
            )
            if include_enrichment:
                response_projection_payload = projection_payload
                response_context = normalized_context
                response_context_snapshot = projection_payload.get("context_snapshot")
                response_source_alert = normalized_source_alert
                response_recommendation = normalized_recommendation
            else:
                compact_projection_keys = {
                    "alert_id",
                    "approval_status",
                    "event_stage",
                    "event_type",
                    "flow_id",
                    "jira_key",
                    "jira_link",
                    "jira_status",
                    "jira_url",
                    "orchestration_path",
                    "remediation_status",
                    "resolution_lifecycle",
                    "status",
                    "status_reason",
                    "status_source",
                    "ticket_id",
                    "transport_channel",
                }
                response_projection_payload = {
                    key: value
                    for key, value in projection_payload.items()
                    if key in compact_projection_keys
                }
                if normalized_context:
                    compact_context_metadata = (
                        normalized_context.get("metadata")
                        if isinstance(normalized_context.get("metadata"), dict)
                        else {}
                    )
                    response_projection_payload["context_metadata"] = {
                        "available": True,
                        "contract_version": compact_context_metadata.get("contract_version"),
                        "recovered": compact_context_metadata.get("recovered") is True,
                    }
                response_context = {}
                response_context_snapshot = None
                response_source_alert = {}
                response_recommendation = {}

            response_rows.append(
                {
                    "incident_id": str(row.incident_id),
                    "alert_id": str(navigable_alert_id) if navigable_alert_id else None,
                    "trace_id": row.trace_id,
                    "recommendation_id": str(merged_recommendation_id) if merged_recommendation_id else None,
                    "flow_id": merged_flow_id,
                    "tenant_id": row.tenant_id,
                    "service": row.service,
                    "environment": row.environment,
                    "severity": row.severity,
                    "status": projected_status,
                    "status_source": lifecycle_status["source"],
                    "status_reason": lifecycle_status["reason"],
                    "approval_status": approval_status or None,
                    "owner": row.owner,
                    "risk_tier": row.risk_tier,
                    "execution_mode": row.execution_mode,
                    "requires_approval": row.requires_approval,
                    "policy_version": row.policy_version,
                    "policy_reason": row.policy_reason,
                    "resolution_lifecycle": resolution_lifecycle,
                    "orchestration_path": orchestration_path,
                    "transport_provider": row.transport_provider,
                    "latest_event_id": str(row.latest_event_id) if row.latest_event_id else None,
                    "latest_event_type": row.latest_event_type,
                    "latest_event_at": row.latest_event_at,
                    "created_at": row.first_seen_at,
                    "updated_at": row.updated_at,
                    "ticket_id": ticket_id or None,
                    "jira_link": jira_link,
                    "jira_status": jira_status,
                    "jira_key": ticket_id or None,
                    "jira_url": jira_link,
                    "title": normalized_source_alert.get("name") or source_labels.get("alertname") or summary,
                    "summary": summary,
                    "source": source_name,
                    "origin_system": origin_system,
                    # Keep the durable alert identity available on compact incident
                    # responses.  The inbox uses these fields to collapse historical
                    # projections that were created for the same correlated signal.
                    "fingerprint": normalized_source_alert.get("fingerprint"),
                    "correlation_id": normalized_source_alert.get("correlation_id"),
                    "deduplicated_count": deduplicated_count,
                    "deduplication_reason": deduplication_reason,
                    "customer_impact": customer_impact,
                    "root_cause": root_cause,
                    "confidence": confidence,
                    "context": response_context,
                    "context_snapshot": response_context_snapshot,
                    "source_alert": response_source_alert,
                    "recommendation": response_recommendation,
                    "projection_payload": response_projection_payload,
                }
            )

        if status:
            requested_status = str(status).strip().lower().replace("-", "_").replace(" ", "_")
            response_rows = [
                item
                for item in response_rows
                if str(item.get("status") or "").strip().lower().replace("-", "_").replace(" ", "_")
                == requested_status
            ]
        return response_rows[:safe_limit]

    async def list_closed_incidents(
        self,
        *,
        limit: int = 100,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        normalized_tenant_id = self._require("tenant_id", tenant_id)
        stmt = (
            select(
                IncidentProjectionRecord.incident_id,
                IncidentProjectionRecord.alert_id,
                IncidentProjectionRecord.trace_id,
                IncidentProjectionRecord.recommendation_id,
                IncidentProjectionRecord.flow_id,
                IncidentProjectionRecord.service,
                IncidentProjectionRecord.environment,
                IncidentProjectionRecord.severity,
                IncidentProjectionRecord.status,
                IncidentProjectionRecord.risk_tier,
                IncidentProjectionRecord.execution_mode,
                IncidentProjectionRecord.transport_provider,
                IncidentProjectionRecord.first_seen_at,
                IncidentProjectionRecord.latest_event_at,
                IncidentProjectionRecord.updated_at,
                IncidentProjectionRecord.projection_payload,
            )
            # This endpoint feeds closure/MTTR reporting. Failed incidents are
            # unresolved terminal attempts and must not be counted as closures.
            .where(
                IncidentProjectionRecord.status.in_(["closed", "resolved"]),
                IncidentProjectionRecord.tenant_id == normalized_tenant_id,
            )
            .order_by(IncidentProjectionRecord.latest_event_at.desc())
            .limit(safe_limit)
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        incident_ids = [row.incident_id for row in rows]
        ticket_id_by_incident: dict[UUID, str] = {}
        if incident_ids:
            ticket_result = await self.session.execute(
                select(IncidentRecord.id, IncidentRecord.ticket_id)
                .where(
                    IncidentRecord.id.in_(incident_ids),
                    IncidentRecord.tenant_id == normalized_tenant_id,
                )
            )
            for inc_id, t_id in ticket_result.all():
                if t_id:
                    ticket_id_by_incident[inc_id] = t_id

        response_rows: list[dict[str, Any]] = []
        for row in rows:
            projection_payload = dict(row.projection_payload) if isinstance(row.projection_payload, dict) else {}
            event_payload = projection_payload.get("event_payload") if isinstance(projection_payload.get("event_payload"), dict) else {}
            source_alert = projection_payload.get("source_alert") if isinstance(projection_payload.get("source_alert"), dict) else {}
            alert_payload = event_payload.get("alert") if isinstance(event_payload.get("alert"), dict) else {}
            alert_labels = alert_payload.get("labels") if isinstance(alert_payload.get("labels"), dict) else {}
            closed_severity = next(
                (
                    str(value).strip()
                    for value in (
                        row.severity,
                        event_payload.get("severity"),
                        alert_payload.get("severity"),
                        alert_labels.get("severity"),
                        source_alert.get("severity"),
                    )
                    if str(value or "").strip()
                ),
                None,
            )

            ticket_id = ticket_id_by_incident.get(row.incident_id) or projection_payload.get("ticket_id")

            import os
            jira_base = str(os.environ.get("JIRA_URL") or os.environ.get("JIRA_API_BASE_URL") or "").rstrip("/")
            jira_link = f"{jira_base}/browse/{ticket_id}" if (ticket_id and jira_base) else None

            status_lower = str(row.status or "").strip().lower()
            jira_status = None
            if ticket_id:
                jira_status = "Done" if status_lower in {"closed", "resolved", "done"} else "In Progress"

            projection_payload["ticket_id"] = ticket_id or None
            projection_payload["jira_link"] = jira_link
            projection_payload["jira_status"] = jira_status
            projection_payload["jira_key"] = ticket_id or None
            projection_payload["jira_url"] = jira_link

            response_rows.append(
                {
                    "incident_id": str(row.incident_id),
                    "alert_id": str(row.alert_id) if row.alert_id else None,
                    "trace_id": row.trace_id,
                    "recommendation_id": str(row.recommendation_id) if row.recommendation_id else None,
                    "flow_id": row.flow_id,
                    "service": row.service,
                    "environment": row.environment,
                    "severity": closed_severity,
                    "status": row.status,
                    "risk_tier": row.risk_tier,
                    "execution_mode": row.execution_mode,
                    "transport_provider": row.transport_provider,
                    "health_restored": bool(event_payload.get("health_restored")) if "health_restored" in event_payload else None,
                    "alerts_cleared": bool(event_payload.get("alerts_cleared")) if "alerts_cleared" in event_payload else None,
                    "created_at": row.first_seen_at,
                    "closed_at": row.latest_event_at or row.updated_at,
                    "updated_at": row.updated_at,
                    "ticket_id": ticket_id or None,
                    "jira_link": jira_link,
                    "jira_status": jira_status,
                    "jira_key": ticket_id or None,
                    "jira_url": jira_link,
                    "projection_payload": projection_payload,
                }
            )
        return response_rows


class DraftPullRequestOutboxRepository:
    """Persistence boundary for bounded draft-PR delivery and reconciliation."""

    TERMINAL_STATUSES = frozenset({"completed", "dead_letter"})

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        idempotency_key: str,
        tenant_id: str,
        proposal_id: UUID | str,
        request_payload: dict[str, Any],
        max_attempts: int = 3,
    ) -> tuple[str, bool]:
        normalized_key = str(idempotency_key).strip()
        normalized_tenant = require_tenant_id(tenant_id, source="draft PR outbox")
        if not normalized_key:
            raise ValueError("draft PR idempotency_key is required")
        existing = await self.session.scalar(
            select(DraftPullRequestOutboxRecord).where(
                DraftPullRequestOutboxRecord.idempotency_key == normalized_key
            ).limit(1)
        )
        if existing is not None:
            if existing.tenant_id != normalized_tenant or str(existing.proposal_id) != str(proposal_id):
                raise ValueError("draft PR idempotency key is already bound to another request")
            return str(existing.job_id), False
        job_id = uuid4()
        self.session.add(
            DraftPullRequestOutboxRecord(
                job_id=job_id,
                idempotency_key=normalized_key,
                tenant_id=normalized_tenant,
                proposal_id=UUID(str(proposal_id)),
                request_payload=request_payload,
                status="pending",
                attempts=0,
                max_attempts=max(1, min(int(max_attempts), 5)),
                next_attempt_at=utc_now(),
            )
        )
        return str(job_id), True

    async def list_due(self, *, now: datetime | None = None, limit: int = 25) -> list[DraftPullRequestOutboxRecord]:
        result = await self.session.execute(
            select(DraftPullRequestOutboxRecord).where(
                DraftPullRequestOutboxRecord.status.in_(("pending", "retry")),
                DraftPullRequestOutboxRecord.next_attempt_at <= (now or utc_now()),
            ).order_by(DraftPullRequestOutboxRecord.created_at.asc()).limit(max(1, min(int(limit), 100)))
        )
        return list(result.scalars().all())

    async def mark_completed(self, job_id: UUID | str, *, provider_response: dict[str, Any]) -> None:
        row = await self.session.get(DraftPullRequestOutboxRecord, UUID(str(job_id)))
        if row is None or row.status in self.TERMINAL_STATUSES:
            return
        row.status = "completed"
        row.attempts = int(row.attempts or 0) + 1
        row.provider_response = provider_response
        row.last_error = None
        row.completed_at = utc_now()
        self.session.add(AuditLogRecord(
            tenant_id=row.tenant_id,
            actor="draft-pr-outbox-worker",
            action="draft_pull_request.created",
            resource_type="code_patch_proposal",
            resource_id=str(row.proposal_id),
            payload={
                "job_id": str(row.job_id),
                "provider_pull_request_id": provider_response.get("provider_pull_request_id"),
                "url": provider_response.get("url"),
                "state": provider_response.get("state"),
                "attempts": row.attempts,
            },
        ))

    async def mark_failed(self, job_id: UUID | str, *, error: str, now: datetime | None = None) -> str:
        row = await self.session.get(DraftPullRequestOutboxRecord, UUID(str(job_id)))
        if row is None:
            raise ValueError("draft PR outbox job not found")
        if row.status in self.TERMINAL_STATUSES:
            return row.status
        attempts = int(row.attempts or 0) + 1
        row.attempts = attempts
        row.last_error = str(error)[:2000]
        if attempts >= int(row.max_attempts or 1):
            row.status = "dead_letter"
            action = "draft_pull_request.dead_lettered"
        else:
            row.status = "retry"
            row.next_attempt_at = (now or utc_now()) + timedelta(seconds=min(300, 2 ** attempts))
            action = "draft_pull_request.retry_scheduled"
        self.session.add(AuditLogRecord(
            tenant_id=row.tenant_id,
            actor="draft-pr-outbox-worker",
            action=action,
            resource_type="code_patch_proposal",
            resource_id=str(row.proposal_id),
            payload={"job_id": str(row.job_id), "attempts": attempts, "max_attempts": row.max_attempts},
        ))
        return row.status

    async def get_by_idempotency_key(self, idempotency_key: str, *, tenant_id: str) -> dict[str, Any] | None:
        row = await self.session.scalar(select(DraftPullRequestOutboxRecord).where(
            DraftPullRequestOutboxRecord.idempotency_key == str(idempotency_key).strip(),
            DraftPullRequestOutboxRecord.tenant_id == require_tenant_id(tenant_id, source="draft PR reconciliation"),
        ).limit(1))
        if row is None:
            return None
        return {
            "job_id": str(row.job_id), "proposal_id": str(row.proposal_id), "status": row.status,
            "attempts": row.attempts, "max_attempts": row.max_attempts,
            "provider_response": row.provider_response, "last_error": row.last_error,
            "completed_at": row.completed_at,
        }


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
            "tenant_id": row.tenant_id,
            "expires_at": row.expires_at,
            "artifact_signature": row.artifact_signature,
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
        tenant_id: str = "default",
        expires_at: datetime | None = None,
        artifact_signature: str | None = None,
    ) -> str:
        record_id = self._to_uuid(evaluation_id) or uuid4()
        await self.session.merge(
            EvaluationRecord(
                id=record_id,
                tenant_id=self._require("tenant_id", tenant_id),
                expires_at=expires_at,
                artifact_signature=artifact_signature,
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

    async def get_evaluation(self, evaluation_id: UUID | str, *, tenant_id: str = "default") -> dict[str, Any] | None:
        result = await self.session.execute(
            select(EvaluationRecord).where(
                EvaluationRecord.id == self._to_uuid(evaluation_id),
                EvaluationRecord.tenant_id == self._require("tenant_id", tenant_id),
            )
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
        tenant_id: str = "default",
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        stmt = select(EvaluationRecord).where(EvaluationRecord.tenant_id == self._require("tenant_id", tenant_id))
        if incident_id:
            stmt = stmt.where(EvaluationRecord.incident_id == self._to_uuid(incident_id))
        if agent:
            stmt = stmt.where(EvaluationRecord.agent == str(agent))
        if min_score is not None:
            stmt = stmt.where(EvaluationRecord.overall_score >= float(min_score))
        stmt = stmt.order_by(EvaluationRecord.created_at.desc()).limit(safe_limit)
        result = await self.session.execute(stmt)
        return [self._row_to_dict(row) for row in result.scalars().all()]

    async def purge_expired_evaluations(
        self,
        *,
        tenant_id: str,
        now: datetime,
        limit: int = 100,
        actor: str = "evaluation-retention-sweeper",
    ) -> list[str]:
        """Delete a bounded tenant slice while retaining non-sensitive audit evidence."""
        normalized_tenant = self._require("tenant_id", tenant_id)
        safe_limit = max(1, min(int(limit), 1000))
        result = await self.session.execute(
            select(EvaluationRecord).where(
                EvaluationRecord.tenant_id == normalized_tenant,
                EvaluationRecord.expires_at.is_not(None),
                EvaluationRecord.expires_at <= now,
            ).order_by(EvaluationRecord.expires_at.asc()).limit(safe_limit)
        )
        rows = list(result.scalars().all())
        for row in rows:
            expired_at = row.expires_at
            if expired_at is not None and expired_at.tzinfo is None:
                expired_at = expired_at.replace(tzinfo=UTC)
            await self.session.delete(row)
            self.session.add(
                AuditLogRecord(
                    tenant_id=normalized_tenant,
                    actor=self._require("audit.actor", actor),
                    action="evaluation.retention.expired",
                    resource_type="evaluation",
                    resource_id=str(row.id),
                    payload={
                        "expired_at": expired_at.isoformat() if expired_at else None,
                        "had_artifact_signature": bool(row.artifact_signature),
                    },
                )
            )
        await self.session.flush()
        return [str(row.id) for row in rows]

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
