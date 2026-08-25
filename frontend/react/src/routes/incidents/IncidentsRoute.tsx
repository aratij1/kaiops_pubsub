import { useEffect, useMemo, useState } from "react";
import { Activity, Bell, BrainCircuit, Check, CircleSlash2, ClipboardCheck, Copy, ExternalLink, FileCheck2, Filter, Gauge, GitMerge, List, RefreshCw, Rows3, ScanSearch, Server, ShieldCheck, TicketCheck, Workflow, Wrench } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useRouteRuntimeSlice, type AlertStreamRow, type IncidentFilters, type IncidentRow } from "../../app/routeRuntime";
import { OperationsWorkflowNav } from "../../components/operations/OperationsWorkflowNav";
import { effectiveIncidentStatus } from "../../domain/incidentStatus";
import { formatIstTimestamp } from "../../appHelpers.jsx";
import "./IncidentsRoute.css";

const PAGE_SIZE = 10;
type InboxView = "needs_me" | "kai_handling" | "critical" | "watching" | "resolved" | "all";
type RecordType = "all" | "incidents" | "alerts";

function attentionScore(row: IncidentRow) {
  const severity = String(row.severity || "").toLowerCase();
  const status = String(row.status || "").toLowerCase();
  const payload = row.projection_payload && typeof row.projection_payload === "object" ? row.projection_payload : {};
  const ageHours = Math.max(0, (Date.now() - new Date(String(row.created_at || row.updated_at || Date.now())).getTime()) / 3_600_000);
  return (["critical", "sev1", "p1"].includes(severity) ? 100 : ["high", "sev2", "p2"].includes(severity) ? 60 : severity === "medium" ? 30 : 10)
    + (status.includes("approval") ? 120 : 0)
    + (["failed", "blocked", "manual_intervention_required", "validation_failed", "rollback_failed"].some((value) => status.includes(value)) ? 140 : 0)
    + (payload.customer_impact || payload.business_impact || payload.impact ? 50 : 0)
    + (String(row.risk_tier || "").toLowerCase() === "high" ? 35 : 0)
    + Math.min(48, ageHours);
}

function belongsToInboxView(row: IncidentRow, view: InboxView) {
  const status = String(row.status || "").toLowerCase();
  const severity = String(row.severity || "").toLowerCase();
  const terminal = ["closed", "resolved", "recovered", "cancelled"].some((value) => status.includes(value));
  const needsHuman = status.includes("approval") || ["failed", "blocked", "manual_intervention_required", "validation_failed", "rollback_failed"].some((value) => status.includes(value));
  if (view === "needs_me") return !terminal && needsHuman;
  if (view === "kai_handling") return !terminal && !needsHuman;
  if (view === "critical") return !terminal && ["critical", "sev1", "p1"].includes(severity);
  if (view === "watching") return !terminal && ["medium", "warning", "low", "info"].includes(severity);
  if (view === "resolved") return terminal;
  return true;
}

function alertDisposition(row: AlertStreamRow) {
  const metadata = (row as AlertStreamRow & { metadata?: Record<string, unknown> }).metadata || {};
  const noiseMetadata = metadata.noise && typeof metadata.noise === "object" ? metadata.noise as Record<string, unknown> : {};
  const disposition = String(row.incident_disposition || "").toLowerCase();
  const noise = ["noise", "suppressed", "ignored", "non_actionable"].includes(disposition) || noiseMetadata.classified === true;
  const duplicate = !noise && (disposition === "duplicate" || Number(row.deduplicated_count || 1) > 1);
  return { noise, duplicate, noiseReason: String(noiseMetadata.reason || row.suppression_reason || "Non-actionable monitoring noise") };
}

function alertLinkedIncidentId(row: AlertStreamRow) {
  const candidate = String((row as AlertStreamRow & { incident_id?: string | number }).incident_id || "").trim();
  const alertId = String((row as AlertStreamRow & { alert_id?: string | number }).alert_id || row.id || "").trim();
  // Some source adapters reuse the alert identifier in incident_id before an
  // incident exists. Only a distinct identifier is an evidence-backed link.
  return candidate && candidate !== alertId ? candidate : "";
}

function alertAttentionScore(row: AlertStreamRow) {
  const severity = String(row.severity || row.priority || "").toLowerCase();
  const disposition = alertDisposition(row);
  const ageHours = Math.max(0, (Date.now() - new Date(String(row.received_at || row.created_at || row.first_seen || Date.now())).getTime()) / 3_600_000);
  return (["critical", "p1", "sev1"].includes(severity) ? 95 : ["high", "p2", "sev2"].includes(severity) ? 55 : severity === "medium" || severity === "warning" ? 25 : 8)
    + (disposition.noise ? -100 : disposition.duplicate ? -35 : 35)
    + Math.min(24, ageHours);
}

function alertBelongsToInboxView(row: AlertStreamRow, view: InboxView) {
  const severity = String(row.severity || row.priority || "").toLowerCase();
  const disposition = alertDisposition(row);
  if (view === "needs_me") return !disposition.noise && !disposition.duplicate && ["critical", "high", "p1", "p2", "sev1", "sev2"].includes(severity);
  if (view === "kai_handling") return !disposition.noise && !disposition.duplicate;
  if (view === "critical") return !disposition.noise && ["critical", "p1", "sev1"].includes(severity);
  if (view === "watching") return disposition.noise || disposition.duplicate || ["medium", "warning", "low", "info"].includes(severity);
  if (view === "resolved") return false;
  return true;
}

const stageOrder = [
  { id: "application", cockpit: "overview", label: "Application", detail: "Original source" },
  { id: "signal", cockpit: "overview", label: "Signal", detail: "Failure observed" },
  { id: "prometheus", cockpit: "overview", label: "Prometheus", detail: "Rule fired" },
  { id: "ingest", cockpit: "overview", label: "Alert landing", detail: "KaiOps received" },
  { id: "normalize", cockpit: "overview", label: "Normalize", detail: "Canonical alert" },
  { id: "deduplicate", cockpit: "overview", label: "Deduplicate", detail: "Occurrence decision" },
  { id: "jira", cockpit: "overview", label: "Jira", detail: "Ticket created" },
  { id: "decision", cockpit: "overview", label: "Decision", detail: "Incident or noise" },
  { id: "context", cockpit: "evidence", label: "Context", detail: "Evidence collected" },
  { id: "understand", cockpit: "evidence", label: "Evidence & Understanding", detail: "Evidence, RCA, and impact" },
  { id: "approval", cockpit: "execution", label: "Approval", detail: "Decision gate" },
  { id: "resolve", cockpit: "execution", label: "Resolve", detail: "Plan and remediate" },
  { id: "validate", cockpit: "audit", label: "Validate", detail: "Verify and close" },
];

type StageState = "complete" | "current" | "reused" | "stopped" | "failed";
type LifecycleStage = (typeof stageOrder)[number] & { state: StageState; caption: string };
type Presentation = "summary" | "flow" | "details";
type GroupedIncidentRow = IncidentRow & { duplicateIncidents: IncidentRow[] };

const stageIcons = {
  application: Server,
  signal: Gauge,
  prometheus: Activity,
  ingest: Bell,
  normalize: Filter,
  deduplicate: GitMerge,
  jira: TicketCheck,
  decision: ScanSearch,
  context: ScanSearch,
  understand: BrainCircuit,
  approval: ClipboardCheck,
  resolve: Wrench,
  validate: ShieldCheck,
} as const;

function normalizedStatus(row: IncidentRow) {
  const event = projectionEvent(row);
  return effectiveIncidentStatus(row.status || "open", row.approval_status || event.approval_status);
}

function lifecycleFor(row: IncidentRow): LifecycleStage[] {
  const status = normalizedStatus(row);
  const event = projectionEvent(row);
  const labels = projectionLabels(row);
  const mode = String(row.execution_mode || event.execution_mode || "human-approval").toLowerCase();
  const decision = String(row.approval_status || event.approval_status || "").toLowerCase();
  const jiraReady = Boolean(row.ticket_id || row.jira_key);
  const contextState = contextPresentation(row);
  const contextReady = !["Context pending", "Historical context unavailable"].includes(contextState.label);
  const projection = row.projection_payload && typeof row.projection_payload === "object" ? row.projection_payload : {};
  const latestEvent = String(row.latest_event_type || projection.event_type || "").toLowerCase();
  const noise = incidentNoise(row).noise;
  const deduplication = event.deduplication && typeof event.deduplication === "object" ? event.deduplication as Record<string, unknown> : {};
  const duplicate = String(row.incident_disposition || deduplication.disposition || "").toLowerCase() === "duplicate";
  const understood = ["awaiting_approval", "approved", "remediating", "validating", "resolved", "closed", "failed"].includes(status);
  const approvalStarted = mode.includes("human") && (["awaiting_approval", "approved", "remediating", "validating", "resolved", "closed"].includes(status) || Boolean(decision));
  const approvalComplete = ["approved", "modified", "rejected"].includes(decision) || ["approved", "remediating", "validating", "resolved", "closed"].includes(status);
  const validated = ["resolved", "closed"].includes(status);
  const hasContextEvidence = Boolean(
    projection.context_metadata || projection.context || event.context_metadata || event.context
    || event.context_source || projection.context_source || latestEvent.includes("context"),
  );
  const complete = (id: string, caption: string): LifecycleStage => ({ ...stageOrder.find((stage) => stage.id === id)!, state: "complete", caption });
  const application = value(labels.application, labels.project_name, event.application, row.service);
  const target = value(labels.instance, event.instance, event.target);
  const alertName = value(labels.alertname, event.alert_name, event.name);
  const source = value(row.source, row.origin_system, labels.origin_system, labels.source);
  const prometheusObserved = /prometheus|blackbox|alertmanager/i.test([source, labels.job, labels.transport, event.ingestion_channel].join(" "));
  const stage = (id: string) => stageOrder.find((item) => item.id === id)!;
  const stages: LifecycleStage[] = [
    ...(application !== "Not recorded" ? [complete("application", application)] : []),
    ...(target !== "Not recorded" ? [complete("signal", target)] : []),
    ...(prometheusObserved ? [complete("prometheus", alertName !== "Not recorded" ? alertName : "Alert rule fired")] : []),
    ...(row.alert_id ? [complete("ingest", value(event.received_at, row.created_at, "Alert received"))] : []),
    ...(/normaliz/.test(latestEvent) || Boolean(event.normalized_alert || projection.normalized_alert) ? [complete("normalize", value(row.service, "Canonical alert"))] : []),
    ...(duplicate || Number(row.deduplicated_count || 1) > 1 || Boolean(event.deduplication || projection.deduplication) ? [complete("deduplicate", duplicate ? "Duplicate linked" : Number(row.deduplicated_count || 1) > 1 ? `${row.deduplicated_count} occurrences merged` : "Unique signal")] : []),
    ...(jiraReady ? [complete("jira", String(row.ticket_id || row.jira_key))] : []),
  ];
  if (noise) {
    stages.push({ ...stage("decision"), state: "stopped", caption: "Noise / no action" });
    return stages;
  }
  if (duplicate) {
    stages.push({ ...stage("decision"), state: "stopped", caption: "Linked to canonical incident" });
    return stages;
  }
  stages.push(complete("decision", "Incident created"));
  if (hasContextEvidence) {
    stages.push({
      ...stage("context"),
      state: contextReady ? (contextState.source.includes("cache") || contextState.source === "ticket_payload" ? "reused" : "complete") : "current",
      caption: contextReady ? contextState.label : "Collecting evidence",
    });
  }
  if (row.recommendation_id || event.recommendation_id || latestEvent.includes("recommendation") || understood) {
    stages.push({ ...stage("understand"), state: understood ? "complete" : "current", caption: understood ? "RCA generated" : "Generating RCA" });
  }
  if (approvalStarted) {
    stages.push({ ...stage("approval"), state: approvalComplete ? "complete" : "current", caption: approvalComplete ? "Decision recorded" : "Awaiting decision" });
  }
  const hasRemediation = Boolean(projection.remediation_action || projection.remediation_status || event.remediation_action || latestEvent.includes("remediation"));
  const hasValidation = Boolean(projection.closure_report || projection.validation || event.closure_report || latestEvent.includes("closure") || latestEvent.includes("validation"));
  if (status === "approved") {
    stages.push({ ...stage("resolve"), state: "current", caption: "Awaiting confirmation and execution" });
  } else if (status === "remediating") {
    stages.push({ ...stage("resolve"), state: "current", caption: "Executing remediation" });
  } else if (status === "validating") {
    stages.push({ ...stage("resolve"), state: "complete", caption: "Remediation completed" });
    stages.push({ ...stage("validate"), state: "current", caption: "Verifying recovery" });
  } else if (status === "failed") {
    if (hasValidation) {
      stages.push({ ...stage("resolve"), state: "complete", caption: "Remediation completed" });
      stages.push({ ...stage("validate"), state: "failed", caption: "Recovery validation failed" });
    } else {
      stages.push({ ...stage("resolve"), state: "failed", caption: "Remediation failed or was blocked" });
    }
  } else if (validated) {
    stages.push({ ...stage("resolve"), state: "complete", caption: "Remediation completed" });
    stages.push({ ...stage("validate"), state: "complete", caption: "Verified and closed" });
  } else {
    if (hasRemediation) stages.push({ ...stage("resolve"), state: "complete", caption: "Remediation recorded" });
    if (hasValidation) stages.push({ ...stage("validate"), state: "current", caption: "Verifying recovery" });
  }
  return stages;
}

function projectionEvent(row: IncidentRow) {
  const projection = row.projection_payload && typeof row.projection_payload === "object" ? row.projection_payload : {};
  const event = projection.event_payload && typeof projection.event_payload === "object" ? projection.event_payload as Record<string, unknown> : {};
  return event;
}

function projectionLabels(row: IncidentRow) {
  const projection = row.projection_payload && typeof row.projection_payload === "object" ? row.projection_payload : {};
  const event = projectionEvent(row);
  const candidates = [row.source_alert?.labels, event.labels, projection.labels, event.alert_labels, projection.alert_labels];
  return (candidates.find((candidate) => candidate && typeof candidate === "object") || {}) as Record<string, unknown>;
}

function sourceEvidence(row: IncidentRow) {
  const alert = row.source_alert && typeof row.source_alert === "object" ? row.source_alert : {};
  const annotations = alert.annotations && typeof alert.annotations === "object" ? alert.annotations : {};
  const metadata = alert.metadata && typeof alert.metadata === "object" ? alert.metadata : {};
  const log = [metadata.application_log, metadata.log_line, alert.log, alert.message]
    .map((candidate) => String(candidate || "").trim())
    .find(Boolean) || "";
  return {
    alert,
    annotations,
    metadata,
    log,
    observation: value(alert.description, annotations.description, annotations.summary),
    timestamp: value(alert.starts_at, alert.created_at, annotations.startsAt, row.created_at),
    uri: value(annotations.generatorURL, metadata.source_uri, metadata.uri),
    trace: value(alert.trace_id, row.trace_id),
  };
}

function alertSourceLabel(row: IncidentRow) {
  const evidence = sourceEvidence(row);
  const labels = projectionLabels(row);
  const event = projectionEvent(row);
  return value(
    evidence.alert.origin_system,
    evidence.alert.source,
    evidence.alert.source_channel,
    row.origin_system,
    row.source,
    row.ingestion_channel,
    event.origin_system,
    event.source,
    labels.source,
  );
}

function fullAlertPayload(row: IncidentRow) {
  const event = projectionEvent(row);
  const sourceAlert = row.source_alert && typeof row.source_alert === "object" ? row.source_alert : {};
  return Object.keys(sourceAlert).length
    ? sourceAlert
    : (event.normalized_alert && typeof event.normalized_alert === "object" ? event.normalized_alert : event);
}

function incidentNoise(row: IncidentRow) {
  const event = projectionEvent(row);
  const candidate = event.incident_candidate && typeof event.incident_candidate === "object"
    ? event.incident_candidate as Record<string, unknown>
    : {};
  const noise = candidate.noise === true || candidate.false_positive === true || candidate.actionable === false;
  return {
    noise,
    reason: String(candidate.actionability_reason || candidate.description || "Classified as non-actionable monitoring noise."),
  };
}

function contextPresentation(row: IncidentRow) {
  const projection = row.projection_payload && typeof row.projection_payload === "object" ? row.projection_payload : {};
  const event = projectionEvent(row);
  const nested = [projection.context_metadata, projection.context, event.context_metadata, event.context]
    .find((candidate) => candidate && typeof candidate === "object") as Record<string, unknown> | undefined;
  const source = String(nested?.context_source || event.context_source || projection.context_source || "").toLowerCase();
  const strategy = String(nested?.context_strategy || event.context_strategy || projection.context_strategy || "auto").toLowerCase();
  const realtime = nested?.realtime_collection_performed ?? event.realtime_collection_performed ?? projection.realtime_collection_performed;
  const status = normalizedStatus(row);
  const downstreamComplete = ["awaiting_approval", "approved", "remediating", "validating", "resolved", "closed", "failed"].includes(status)
    || Boolean(row.recommendation_id || event.recommendation_id || projection.recommendation_id);
  if (source === "ticket_payload") return { label: "Available in ticket", source, strategy, realtime: false };
  if (["cache", "periodic_cache"].includes(source)) return { label: source === "periodic_cache" ? "Historical snapshot reused" : "Cached context reused", source, strategy, realtime: false };
  if (source === "historical_cache_miss") return { label: "Historical context unavailable", source, strategy, realtime: false };
  if (source === "realtime_collection" || realtime === true) return { label: "Realtime context collected", source: source || "realtime_collection", strategy, realtime: true };
  if (downstreamComplete) return { label: "Context available", source: "provenance_not_recorded", strategy, realtime: null };
  return { label: "Context pending", source: source || "not_recorded", strategy, realtime: false };
}

function value(...candidates: unknown[]) {
  const match = candidates.find((candidate) => candidate !== undefined && candidate !== null && String(candidate).trim());
  return match === undefined ? "Not recorded" : String(match);
}

function incidentTitle(row: IncidentRow) {
  return String(row.title || row.summary || `${row.service || "Service"} incident`).trim();
}

function incidentStatusLabel(row: IncidentRow) {
  return normalizedStatus(row) === "failed" ? "Action required" : String(row.status || "open").replaceAll("_", " ");
}

function incidentTime(row: IncidentRow) {
  const timestamp = Date.parse(String(row.updated_at || row.created_at || ""));
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function incidentProgress(row: IncidentRow) {
  const lifecycle = lifecycleFor(row);
  const furthestStage = lifecycle.reduce((furthest, stage) => {
    const index = stageOrder.findIndex((candidate) => candidate.id === stage.id);
    return Math.max(furthest, index);
  }, -1);
  const terminalBonus = ["closed", "resolved", "failed"].includes(normalizedStatus(row)) ? stageOrder.length : 0;
  return terminalBonus + furthestStage;
}

function groupIncidentsByJira(rows: IncidentRow[]): GroupedIncidentRow[] {
  const groups = new Map<string, IncidentRow[]>();
  rows.forEach((row) => {
    const jiraKey = String(row.ticket_id || row.jira_key || "").trim().toUpperCase();
    // Incidents without a Jira ticket are still independent workflow records.
    const incidentId = String(row.incident_id || row.id || "").trim();
    const key = jiraKey ? `jira:${jiraKey}` : `incident:${incidentId}`;
    groups.set(key, [...(groups.get(key) || []), row]);
  });
  return Array.from(groups.values()).map((group) => {
    // A newer duplicate can still be near the start of processing while an
    // older record for the same Jira has context, RCA, or approval results.
    // Represent the Jira with the furthest-progressed workflow so opening the
    // row does not hide those results; use recency only between equal stages.
    const sorted = group.slice().sort((left, right) => (
      incidentProgress(right) - incidentProgress(left)
      || incidentTime(right) - incidentTime(left)
    ));
    return { ...sorted[0], duplicateIncidents: sorted.slice(1) };
  });
}

export default function IncidentsRoute() {
  const incidents = useRouteRuntimeSlice("incidents");
  const alerts = useRouteRuntimeSlice("alerts");
  const [searchParams] = useSearchParams();
  const [recordType, setRecordType] = useState<RecordType>(() => {
    const requested = searchParams.get("type");
    return requested === "alerts" || requested === "incidents" ? requested : "all";
  });
  const [presentation, setPresentation] = useState<Presentation>(() => {
    const saved = window.localStorage.getItem("kaiops.incident-presentation");
    return saved === "flow" || saved === "details" ? saved : "summary";
  });
  const [page, setPage] = useState(1);
  const [inboxView, setInboxView] = useState<InboxView>("all");
  const [inspector, setInspector] = useState<{ incidentId: string; stage: string } | null>(null);
  const groupedIncidents = useMemo(() => {
    const alertsById = new Map(alerts.rows.map((alert) => [String(alert.id || (alert as typeof alert & { alert_id?: string }).alert_id || ""), alert]));
    return groupIncidentsByJira(incidents.rows.map((row) => ({
      ...row,
      source_alert: row.source_alert || alertsById.get(String(row.alert_id || "")),
    }))).sort((left, right) => attentionScore(right) - attentionScore(left));
  }, [incidents.rows, alerts.rows]);
  const filteredIncidents = useMemo(() => groupedIncidents.filter((row) => belongsToInboxView(row, inboxView)), [groupedIncidents, inboxView]);
  useEffect(() => window.localStorage.setItem("kaiops.incident-presentation", presentation), [presentation]);
  useEffect(() => setPage(1), [incidents.filters.risk_tier, incidents.filters.execution_mode, incidents.filters.status, incidents.filters.service, inboxView, recordType]);
  const incidentAlertIds = useMemo(() => new Set(incidents.rows.map((row) => String(row.alert_id || "")).filter(Boolean)), [incidents.rows]);
  const unlinkedAlerts = useMemo(() => alerts.rows.filter((alert) => {
    const alertId = String((alert as typeof alert & { alert_id?: string | number }).alert_id || alert.id || "");
    return !alertLinkedIncidentId(alert) && (!alertId || !incidentAlertIds.has(alertId));
  }), [alerts.rows, incidentAlertIds]);
  const filteredAlerts = useMemo(() => {
    const candidates = recordType === "alerts" ? alerts.rows : unlinkedAlerts;
    const serviceQuery = incidents.filters.service.trim().toLowerCase();
    return candidates.filter((alert) => {
      if (!alertBelongsToInboxView(alert, inboxView)) return false;
      if (!serviceQuery) return true;
      return [alert.service, alert.application, alert.project_name, alert.name, alert.alert_name]
        .some((value) => String(value || "").toLowerCase().includes(serviceQuery));
    });
  }, [alerts.rows, incidents.filters.service, inboxView, recordType, unlinkedAlerts]);
  const unifiedRecords = useMemo(() => [
    ...filteredIncidents.map((row) => ({ kind: "incident" as const, score: attentionScore(row), row })),
    ...filteredAlerts.map((row) => ({ kind: "alert" as const, score: alertAttentionScore(row), row })),
  ].sort((left, right) => right.score - left.score), [filteredAlerts, filteredIncidents]);
  const totalRecords = recordType === "all" ? unifiedRecords.length : recordType === "alerts" ? filteredAlerts.length : filteredIncidents.length;
  const pages = Math.max(1, Math.ceil(totalRecords / PAGE_SIZE));
  useEffect(() => setPage((current) => Math.min(current, pages)), [pages]);
  const rows = useMemo(() => filteredIncidents.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), [filteredIncidents, page]);
  const visibleAlerts = useMemo(() => filteredAlerts.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), [filteredAlerts, page]);
  const visibleUnifiedRecords = useMemo(() => unifiedRecords.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), [page, unifiedRecords]);
  const select = (label: string, name: keyof IncidentFilters, options: string[]) => <label>{label}<select value={incidents.filters[name]} onChange={(event) => incidents.updateFilter(name, event.target.value)}>{options.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>;
  const active = groupedIncidents.filter((row) => !["closed", "resolved", "recovered", "cancelled"].includes(normalizedStatus(row))).length;
  const needsAttention = groupedIncidents.filter((row) => belongsToInboxView(row, "needs_me")).length + unlinkedAlerts.filter((row) => alertBelongsToInboxView(row, "needs_me")).length;
  const viewCount = (view: InboxView) => {
    const incidentCount = groupedIncidents.filter((row) => belongsToInboxView(row, view)).length;
    const alertCount = unlinkedAlerts.filter((row) => alertBelongsToInboxView(row, view)).length;
    return recordType === "incidents" ? incidentCount : recordType === "alerts" ? alerts.rows.filter((row) => alertBelongsToInboxView(row, view)).length : incidentCount + alertCount;
  };
  const showUnified = recordType === "all";
  const showAlerts = recordType === "alerts";
  const showIncidents = recordType === "incidents";

  return <section className="grid single-col operations-center">
    <OperationsWorkflowNav active="incidents" />
    <header className="incident-list-heading unified-inbox-heading">
      <div><span className="inbox-eyebrow"><Activity size={14} /> Operations command queue</span><h2>Unified Inbox</h2><p>One prioritized workspace for signals, incidents, and decisions that need attention.</p></div>
      <div className="operations-kpis" aria-label="Operational totals"><span className={needsAttention ? "is-urgent" : ""}><small>Needs attention</small><strong>{needsAttention}</strong></span><span><small>Active incidents</small><strong>{active}</strong></span><span><small>Unlinked signals</small><strong>{unlinkedAlerts.length}</strong></span><span><small>Total incidents</small><strong>{groupedIncidents.length}</strong></span></div>
    </header>
    <nav className="incident-inbox-views" aria-label="Incident inbox views">{([
      ["needs_me", "Needs me"], ["kai_handling", "Kai handling"], ["critical", "Critical"], ["watching", "Watching"], ["resolved", "Resolved recently"], ["all", "All"],
    ] as const).map(([id, label]) => <button type="button" key={id} className={inboxView === id ? "active" : ""} aria-pressed={inboxView === id} onClick={() => { setInboxView(id); setPage(1); }}>{label}<span>{viewCount(id)}</span></button>)}</nav>
    <div className="inbox-source-tabs" role="tablist" aria-label="Inbox source">
      <button type="button" role="tab" aria-selected={showUnified} className={showUnified ? "active" : ""} onClick={() => { setRecordType("all"); setPresentation("summary"); setPage(1); }}><span>All activity</span><strong>{groupedIncidents.length + unlinkedAlerts.length}</strong><small>Incidents + unlinked signals</small></button>
      <button type="button" role="tab" aria-selected={showIncidents} className={showIncidents ? "active" : ""} onClick={() => { setRecordType("incidents"); setPage(1); }}><span>Incidents</span><strong>{groupedIncidents.length}</strong><small>Correlated operational work</small></button>
      <button type="button" role="tab" aria-selected={showAlerts} className={showAlerts ? "active" : ""} onClick={() => { setRecordType("alerts"); setPage(1); }}><span>Signals</span><strong>{alerts.rows.length}</strong><small>Raw intake and outcomes</small></button>
    </div>
    <div className={`compact-filter-bar inbox-filter-bar ${showUnified ? "is-unified" : showAlerts ? "is-signals" : ""}`}>
      {showIncidents ? <>{select("Risk", "risk_tier", ["all", "high", "medium", "low"])}{select("Status", "status", ["all", "open", "investigating", "awaiting_approval", "remediating", "validating", "closed", "failed"])}</> : null}
      <label className="filter-grow">Service<input value={incidents.filters.service} placeholder="Search service, application, or signal" onChange={(event) => incidents.updateFilter("service", event.target.value)} /></label>
      {showAlerts ? <div className="alert-view-note"><ScanSearch size={15} /> Raw intake with deduplication and noise outcomes</div> : null}
      <button className="icon-button" type="button" onClick={() => { incidents.refresh(); alerts.refresh(); }} title="Refresh queue" aria-label="Refresh queue"><RefreshCw size={17} /></button>
    </div>
    {!showUnified ? <div className="incident-presentation" role="radiogroup" aria-label={`${showAlerts ? "Signal" : "Incident"} workspace view`}>
      <span>View</span>
      <button type="button" role="radio" aria-checked={presentation === "summary"} className={presentation === "summary" ? "active" : ""} onClick={() => setPresentation("summary")}><List size={15} /><span><strong>Triage queue</strong><small>Compact prioritized list</small></span></button>
      <button type="button" role="radio" aria-checked={presentation === "details"} className={presentation === "details" ? "active" : ""} onClick={() => setPresentation("details")}><Rows3 size={15} /><span><strong>Split Workspace</strong><small>{showAlerts ? "Alert and evidence" : "Incident and evidence"}</small></span></button>
      <button type="button" role="radio" aria-checked={presentation === "flow"} className={presentation === "flow" ? "active" : ""} onClick={() => setPresentation("flow")}><Workflow size={15} /><span><strong>Correlation Timeline</strong><small>{showAlerts ? "Signal processing path" : "Executed lifecycle"}</small></span></button>
    </div> : null}
    {incidents.error ? <p className="error">{incidents.error}</p> : null}
    <div className={`incident-summary-list view-${presentation}`} aria-busy={incidents.loading || alerts.loading}>
      {showUnified ? <div className="unified-inbox-stack" aria-label="Prioritized operational activity">{visibleUnifiedRecords.map((record, index) => {
        if (record.kind === "incident") {
          const row = record.row;
          const incidentId = String(row.incident_id || row.id || index);
          const lifecycle = lifecycleFor(row);
          const currentStage = lifecycle.find((stage) => ["current", "failed", "stopped"].includes(stage.state)) || lifecycle[lifecycle.length - 1];
          const event = projectionEvent(row);
          const needsHuman = belongsToInboxView(row, "needs_me");
          const severity = String(row.severity || row.risk_tier || "not-set").toLowerCase();
          return <article className={`unified-inbox-card is-incident severity-${severity}`} key={`incident-${incidentId}`}>
            <span className="unified-card-rail" aria-hidden="true" />
            <div className={`unified-card-icon ${needsHuman ? "is-urgent" : ""}`}>{needsHuman ? <FileCheck2 size={20} /> : <BrainCircuit size={20} />}</div>
            <div className="unified-card-body">
              <div className="unified-card-kicker"><span>Incident</span><code>{incidentId}</code>{row.duplicateIncidents.length ? <em>{row.duplicateIncidents.length + 1} occurrences</em> : null}</div>
              <button type="button" className="unified-card-title" onClick={() => incidents.open(row, "overview")}>{incidentTitle(row)}</button>
              <div className="unified-card-context"><span><Server size={13} /> {row.service || "Unknown service"}</span><span>{row.environment || "Environment not set"}</span><span>{formatIstTimestamp(row.updated_at || row.created_at)}</span></div>
              <p className="unified-card-summary">{value(event.customer_impact, event.business_impact, event.impact, row.summary, "Kai is coordinating diagnosis and resolution.")}</p>
              <div className="unified-card-progress"><span className="unified-progress-node"><Workflow size={14} /></span><div><small>Current stage</small><strong>{currentStage?.label || "Awaiting intake"}</strong><span>{currentStage?.caption || "No executed stage recorded"}</span></div></div>
            </div>
            <aside className="unified-card-aside">
              <span className={`pill ${normalizedStatus(row) === "failed" ? "status-warning" : `status-${normalizedStatus(row)}`}`}>{incidentStatusLabel(row)}</span>
              <span className={`unified-attention-label ${needsHuman ? "is-urgent" : ""}`}>{needsHuman ? <><FileCheck2 size={13} /> Human decision</> : <><BrainCircuit size={13} /> Kai handling</>}</span>
              <button type="button" className="button-primary" onClick={() => incidents.open(row, "overview")}>Open incident</button>
            </aside>
          </article>;
        }
        const alert = record.row;
        const alertId = String(alert.id || alert.file || index);
        const disposition = alertDisposition(alert);
        const linkedIncident = alertLinkedIncidentId(alert);
        const severity = String(alert.severity || alert.priority || "not-set").toLowerCase();
        return <article className={`unified-inbox-card is-signal severity-${severity} ${disposition.noise ? "is-muted" : ""}`} key={`signal-${alertId}`}>
          <span className="unified-card-rail" aria-hidden="true" />
          <div className={`unified-card-icon ${disposition.noise ? "is-muted" : disposition.duplicate ? "is-duplicate" : "is-signal"}`}>{disposition.noise ? <CircleSlash2 size={20} /> : disposition.duplicate ? <Copy size={20} /> : <Bell size={20} />}</div>
          <div className="unified-card-body">
            <div className="unified-card-kicker"><span>Signal</span><code>{alertId}</code></div>
            <button type="button" className="unified-card-title" onClick={() => alerts.open(alert, "overview")}>{alert.name || alert.alert_name || "Unnamed signal"}</button>
            <div className="unified-card-context"><span><Activity size={13} /> {alert.service || "Unknown service"}</span><span>{alert.origin_system || alert.source || alert.source_channel || "Unknown source"}</span><span>{formatIstTimestamp(alert.received_at || alert.created_at || alert.first_seen)}</span></div>
            <p className="unified-card-summary">{value(alert.description, alert.annotations?.description, alert.summary, alert.message, disposition.noise ? disposition.noiseReason : "A new operational signal is awaiting correlation.")}</p>
            <div className="unified-card-progress"><span className="unified-progress-node"><GitMerge size={14} /></span><div><small>Correlation outcome</small><strong>{disposition.noise ? "No incident required" : disposition.duplicate ? "Duplicate signal" : linkedIncident ? "Incident linked" : "Awaiting correlation"}</strong><span>{disposition.noise ? disposition.noiseReason : disposition.duplicate ? "Matched to an existing operational record" : linkedIncident ? linkedIncident : "Kai is evaluating impact and related activity"}</span></div></div>
          </div>
          <aside className="unified-card-aside">
            <span className="pill status-open">{String(alert.severity || alert.priority || "Severity not set")}</span>
            <span className={`alert-classification ${disposition.noise ? "is-noise" : disposition.duplicate ? "is-duplicate" : "is-unique"}`}>{disposition.noise ? "Noise" : disposition.duplicate ? "Duplicate" : "Unique signal"}</span>
            <button type="button" className="button-secondary" onClick={() => alerts.open(alert, "overview")}>Review signal</button>
          </aside>
        </article>;
      })}</div> : null}
      {showAlerts && presentation === "summary" ? <div className="incident-table-wrap"><table className="incident-summary-table alert-summary-table"><thead><tr><th>Alert</th><th>Source</th><th>Severity</th><th>Classification</th><th>Linked record</th><th>Received</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{visibleAlerts.map((alert, index) => {
        const metadata = (alert as typeof alert & { metadata?: Record<string, unknown> }).metadata || {};
        const noiseMetadata = metadata.noise && typeof metadata.noise === "object" ? metadata.noise as Record<string, unknown> : {};
        const disposition = String(alert.incident_disposition || "").toLowerCase();
        const noise = ["noise", "suppressed", "ignored", "non_actionable"].includes(disposition) || noiseMetadata.classified === true;
        const duplicate = !noise && (disposition === "duplicate" || Number(alert.deduplicated_count || 1) > 1);
        const linkedIncident = alertLinkedIncidentId(alert);
        return <tr key={String(alert.id || alert.file || index)}><td><button type="button" className="incident-table-title" onClick={() => alerts.open(alert, "overview")}>{alert.name || alert.alert_name || "Unnamed alert"}</button><code>{String(alert.id || alert.file || "No alert ID")}</code></td><td><strong>{alert.service || "Unknown service"}</strong><small>{alert.origin_system || alert.source || alert.source_channel || "Unknown source"}</small></td><td>{alert.severity || "Not set"}</td><td><span className={`alert-classification ${noise ? "is-noise" : duplicate ? "is-duplicate" : "is-unique"}`}>{noise ? "Noise" : duplicate ? "Duplicate" : "Unique"}</span></td><td>{linkedIncident || alert.ticket_id || alert.jira_key || (noise ? "No incident" : "Processing")}</td><td>{formatIstTimestamp(alert.received_at || alert.created_at || alert.first_seen)}</td><td><button type="button" className="button-secondary" onClick={() => { setPresentation("details"); }}>View details</button></td></tr>;
      })}</tbody></table></div> : null}
      {showAlerts && presentation !== "summary" ? visibleAlerts.map((alert, index) => {
        const metadata = (alert as typeof alert & { metadata?: Record<string, unknown> }).metadata || {};
        const noiseMetadata = metadata.noise && typeof metadata.noise === "object" ? metadata.noise as Record<string, unknown> : {};
        const disposition = String(alert.incident_disposition || "").toLowerCase();
        const noise = ["noise", "suppressed", "ignored", "non_actionable"].includes(disposition) || noiseMetadata.classified === true;
        const duplicate = !noise && (disposition === "duplicate" || Number(alert.deduplicated_count || 1) > 1);
        const noiseReason = String(noiseMetadata.reason || alert.suppression_reason || "Non-actionable monitoring noise");
        const linkedIncident = alertLinkedIncidentId(alert);
        const alertId = String(alert.id || alert.file || index);
        return <article className={`unified-alert-row ${presentation === "details" ? "is-detail" : ""}`} key={alertId}>
          <span className={`unified-record-icon ${noise ? "is-noise" : duplicate ? "is-duplicate" : ""}`}>{noise ? <CircleSlash2 size={16} /> : duplicate ? <Copy size={16} /> : <Bell size={16} />}</span>
          <div><small>Alert</small><strong>{alert.name || alert.alert_name || "Unnamed alert"}</strong><p>{alert.service || "Unknown service"} · {alert.origin_system || alert.source || alert.source_channel || "Unknown source"}</p></div>
          <span className="unified-alert-outcome">{duplicate ? "Duplicate · linked to incident" : "New incident signal"}</span>
          <ol className="alert-processing-story"><li>Ingested</li><li>Normalized</li><li>{duplicate ? "Duplicate matched" : "Unique after dedup"}</li><li>{noise ? "Noise / stopped" : linkedIncident ? "Incident created" : "Decision pending"}</li></ol>
          <span className={`unified-alert-result ${noise ? "is-noise" : ""}`} title={noise ? noiseReason : undefined}>{noise ? "Noise / no action" : duplicate ? "Linked to existing incident" : linkedIncident ? "Incident created" : "Processing"}</span>
          <button type="button" className="button-secondary" onClick={() => alerts.open(alert, "overview")}>{noise ? "View alert" : "Open summary"}</button>
          {presentation === "details" ? <section className="alert-detail-panel"><header><small>Alert details</small><strong>{noise ? "Processing stopped as noise" : duplicate ? "Merged with an existing incident" : linkedIncident ? "Incident created" : "Processing in progress"}</strong></header><dl><div><dt>Alert ID</dt><dd>{alertId}</dd></div><div><dt>Source channel</dt><dd>{value(alert.source_channel, alert.ingestion_channel, alert.origin_system, alert.source)}</dd></div><div><dt>Description</dt><dd>{value(alert.description, alert.annotations?.description, alert.summary, alert.message)}</dd></div><div><dt>First seen</dt><dd>{value(alert.first_seen, alert.received_at, alert.created_at)}</dd></div><div><dt>Occurrences</dt><dd>{value(alert.deduplicated_count, alert.occurrence_count, 1)}</dd></div><div><dt>Decision reason</dt><dd>{noise ? noiseReason : value(alert.deduplication_reason, alert.correlation_reason, duplicate ? "Fingerprint matched within deduplication window" : "Unique actionable signal")}</dd></div><div><dt>Linked incident</dt><dd>{linkedIncident || "Not created"}</dd></div><div><dt>Jira</dt><dd>{alert.ticket_id || alert.jira_key || "Pending"}</dd></div></dl></section> : null}
        </article>;
      }) : null}
      {showIncidents && presentation === "summary" ? <div className="incident-table-wrap"><table className="incident-summary-table"><thead><tr><th>Incident</th><th>Service</th><th>Status</th><th>Jira</th><th>Current stage</th><th>Updated</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{rows.map((row, index) => {
        const incidentId = String(row.incident_id || row.id || "-");
        const jiraKey = String(row.ticket_id || row.jira_key || "Pending");
        const lifecycle = lifecycleFor(row);
        const currentStage = lifecycle.find((stage) => ["current", "failed", "stopped"].includes(stage.state)) || lifecycle[lifecycle.length - 1];
        return <tr key={incidentId || index}><td><button type="button" className="incident-table-title" onClick={() => incidents.open(row, "overview")}>{incidentTitle(row)}</button><code>{incidentId}</code>{row.duplicateIncidents.length ? <small>{row.duplicateIncidents.length} duplicate {row.duplicateIncidents.length === 1 ? "incident" : "incidents"} grouped</small> : null}</td><td><strong>{row.service || "Unknown service"}</strong><small>{row.environment || "Environment not set"}</small></td><td><span className={`pill ${normalizedStatus(row) === "failed" ? "status-warning" : `status-${normalizedStatus(row)}`}`}>{incidentStatusLabel(row)}</span></td><td>{row.jira_url ? <a href={row.jira_url} target="_blank" rel="noreferrer">{jiraKey}<ExternalLink size={12} /></a> : jiraKey}</td><td><strong>{currentStage?.label || "Not started"}</strong><small>{currentStage?.caption || "No executed stage"}</small></td><td>{formatIstTimestamp(row.updated_at || row.created_at)}</td><td><button type="button" className="button-secondary" onClick={() => { setInspector(currentStage ? { incidentId, stage: currentStage.id } : null); setPresentation("details"); }}>View details</button></td></tr>;
      })}</tbody></table></div> : null}
      {showIncidents && presentation !== "summary" ? rows.map((row, index) => {
        const incidentId = String(row.incident_id || row.id || "-");
        const jiraKey = String(row.ticket_id || row.jira_key || "Pending");
        const lifecycle = lifecycleFor(row);
        const selectedStage = inspector?.incidentId === incidentId ? inspector.stage : presentation === "details" ? (lifecycle.find((stage) => ["current", "failed"].includes(stage.state)) || [...lifecycle].reverse().find((stage) => !["pending", "stopped"].includes(stage.state)))?.id || "" : "";
        const event = projectionEvent(row);
        const labels = projectionLabels(row);
        const context = contextPresentation(row);
        const evidence = sourceEvidence(row);
        const disposition = incidentNoise(row);
        const details: Record<string, Array<[string, string]>> = {
          application: [["Application", value(labels.application, labels.project_name, event.application, row.service)], ["Service", value(labels.service, row.service)], ["Environment", value(labels.environment, row.environment)], ["Captured application log", evidence.log || "No application log captured for this alert"], ["Observed evidence", evidence.observation], ["Observed at", evidence.timestamp], ["Trace ID", evidence.trace]],
          signal: [["Observed target / operation", value(labels.instance, labels.operation, event.instance, event.target)], ["Metric", value(event.metric, labels.__name__, labels.job === "blackbox" ? "probe_success" : labels.category)], ["Actual observation", evidence.observation], ["Evidence URI", evidence.uri], ["Fingerprint", value(evidence.alert.fingerprint, labels.alert_fingerprint, row.fingerprint)]],
          prometheus: [["Alert rule", value(labels.alertname, evidence.alert.name, event.alert_name, event.name)], ["Prometheus job", value(labels.job, labels.service)], ["Rule result", value(labels.alert_status, "firing")], ["Generator / query", evidence.uri], ["Transport", value(labels.transport, event.transport, "Alertmanager")], ["Produced alert ID", value(row.alert_id)]],
          ingest: [["Source", value(evidence.alert.source, row.source, row.origin_system, event.source)], ["Channel", value(labels.ingestion_channel, row.ingestion_channel, event.ingestion_channel)], ["Received", value(evidence.alert.created_at, row.created_at, event.created_at)], ["Alert ID", value(row.alert_id)], ["Status", value(labels.alert_status, evidence.alert.status)], ["Trace ID", evidence.trace]],
          normalize: [["Service", value(row.service, event.service)], ["Environment", value(row.environment, event.environment)], ["Severity", value(row.severity, event.severity)], ["Canonical alert", value(row.alert_id)]],
          deduplicate: [["Outcome", Number(row.deduplicated_count || 0) > 1 ? "Duplicate occurrence merged" : "Unique incident signal"], ["Occurrences", value(row.deduplicated_count || 1)], ["Fingerprint", value(row.fingerprint, event.fingerprint)], ["Correlation", value(row.correlation_id, event.correlation_id, row.deduplication_reason)]],
          jira: [["Ticket", jiraKey], ["Status", value(row.jira_status, jiraKey === "Pending" ? "Creation pending" : "Created")], ["Priority", value(row.jira_priority, row.risk_tier, row.severity)], ["Assignee", value(row.jira_assignee)]],
          decision: [["Outcome", disposition.noise ? "Noise / no action" : "Incident created"], ["Reason", disposition.noise ? disposition.reason : "Actionable signal accepted for investigation"], ["Incident", incidentId], ["Jira", jiraKey]],
          context: [["Status", context.label], ["Strategy", context.strategy], ["Source", context.source === "provenance_not_recorded" ? "Provenance not recorded" : context.source], ["Realtime collection", context.realtime === true ? "Performed" : context.realtime === false ? "Not required" : "Not recorded"]],
          understand: [["Status", lifecycle.some((stage) => stage.id === "understand" && stage.state === "complete") ? "RCA generated" : "Waiting for context"], ["Risk", value(row.risk_tier)], ["Recommendation", value(event.recommendation_id, row.recommendation_id)], ["Incident status", value(row.status)]],
          approval: [["Decision", value(row.approval_status, event.approval_status, String(row.execution_mode || event.execution_mode || "").includes("human") ? "Pending review" : "Not required")], ["Approver", value(row.approved_by, event.approved_by, event.approver)], ["Execution mode", value(row.execution_mode, event.execution_mode)], ["Comment", value(row.approval_comment, event.approval_comment, event.comment)]],
          resolve: [["Status", value(row.status)], ["Execution mode", value(row.execution_mode)], ["Recommendation", value(event.recommendation_id)], ["Service", value(row.service)]],
          validate: [["Status", lifecycle.some((stage) => stage.id === "validate" && stage.state === "complete") ? "Verified and closed" : "Pending validation"], ["Incident status", value(row.status)], ["Updated", value(row.updated_at)], ["Incident", incidentId]],
        };
        return <article className="incident-summary-row" key={incidentId || index}>
          <div className="incident-summary-identity">
            <div className="incident-summary-title"><button type="button" onClick={() => incidents.open(row, "overview")}>{incidentTitle(row)}</button><span className={`pill ${normalizedStatus(row) === "failed" ? "status-warning" : `status-${normalizedStatus(row)}`}`}>{incidentStatusLabel(row)}</span></div>
            <div className="incident-summary-meta"><span>{row.service || "Unknown service"}</span><span>{row.environment || "Environment not set"}</span><code>{incidentId}</code>{row.jira_url ? <a href={row.jira_url} target="_blank" rel="noreferrer">{jiraKey}<ExternalLink size={12} /></a> : <strong>{jiraKey}</strong>}</div>
          </div>
          {presentation === "flow" ? <div className="incident-flow-wrap">
            <div className="incident-flow-caption"><span>Source-to-resolution trace</span><strong>{lifecycle.length} evidenced stages</strong></div>
            <div className="incident-lifecycle" style={{ gridTemplateColumns: `repeat(${lifecycle.length}, minmax(112px, 1fr))` }} aria-label={`Lifecycle for ${incidentTitle(row)}`}>
            {lifecycle.map((stage, stageIndex) => {
              const selectable = !["pending", "stopped"].includes(stage.state);
              const StageIcon = stageIcons[stage.id as keyof typeof stageIcons] || FileCheck2;
              const domain = ["application", "signal", "prometheus"].includes(stage.id) ? "source-domain" : "kaiops-domain";
              return <button key={stage.id} type="button" className={`is-${stage.state} ${domain} ${selectedStage === stage.id ? "is-selected" : ""}`} disabled={!selectable} title={stage.state === "stopped" ? disposition.reason : stage.caption} onClick={() => { if (!selectable) return; setInspector({ incidentId, stage: stage.id }); if (presentation === "flow") setPresentation("details"); }} aria-expanded={selectedStage === stage.id} aria-label={`${stage.label}: ${stage.caption}`}>
                <span className="incident-stage-node"><StageIcon size={17} strokeWidth={2} />{["complete", "reused"].includes(stage.state) ? <i><Check size={9} strokeWidth={3} /></i> : null}</span><span className="incident-stage-copy"><strong>{stage.label}</strong><small>{stage.caption}</small></span><b className="incident-stage-sequence">{String(stageIndex + 1).padStart(2, "0")}</b>
              </button>;
            })}
            </div>
          </div> : null}
          {presentation === "details" ? <div className="incident-detail-view">
            <nav className="incident-detail-stage-nav" aria-label={`Detail stages for ${incidentTitle(row)}`}>
              {lifecycle.filter((stage) => !["pending", "stopped"].includes(stage.state)).map((stage) => <button type="button" key={stage.id} className={selectedStage === stage.id ? "active" : ""} onClick={() => setInspector({ incidentId, stage: stage.id })}><span>{stage.label}</span><small>{stage.caption}</small></button>)}
            </nav>
            {selectedStage ? <section className="incident-stage-inspector"><header><div><small>Stage details</small><h3>{stageOrder.find((stage) => stage.id === selectedStage)?.label}</h3></div>{selectedStage === "jira" && row.jira_url ? <a className="button-secondary" href={row.jira_url} target="_blank" rel="noreferrer">Open in Jira <ExternalLink size={14} /></a> : <button type="button" className="button-secondary" onClick={() => incidents.open(row, stageOrder.find((stage) => stage.id === selectedStage)?.cockpit || "overview")}>Open workspace</button>}</header><dl>{(details[selectedStage] || []).map(([label, detail]) => <div key={label}><dt>{label}</dt><dd>{detail}</dd></div>)}</dl></section> : <p className="empty-state">No completed stage details are available.</p>}
            <section className="incident-stage-inspector alert-source-inspector">
              <header><div><small>Original alert</small><h3>Source and complete alert</h3></div></header>
              <dl>
                <div><dt>Source</dt><dd>{alertSourceLabel(row)}</dd></div>
                <div><dt>Source channel</dt><dd>{value(evidence.alert.source_channel, evidence.alert.ingestion_channel, row.ingestion_channel, event.ingestion_channel)}</dd></div>
                <div><dt>Alert name</dt><dd>{value(evidence.alert.name, evidence.alert.alert_name, labels.alertname, event.alert_name, row.title)}</dd></div>
                <div><dt>Alert ID</dt><dd>{value(evidence.alert.id, row.alert_id)}</dd></div>
                <div><dt>Observed at</dt><dd>{formatIstTimestamp(evidence.alert.starts_at || evidence.alert.created_at || row.created_at)}</dd></div>
                <div><dt>Source location</dt><dd>{evidence.uri}</dd></div>
                <div className="alert-source-message"><dt>Full alert message</dt><dd>{value(evidence.alert.description, evidence.annotations.description, evidence.annotations.summary, evidence.alert.message, evidence.log, row.summary, row.title)}</dd></div>
              </dl>
              <details className="full-alert-payload"><summary>View complete alert payload</summary><pre>{JSON.stringify(fullAlertPayload(row), null, 2)}</pre></details>
            </section>
            {row.duplicateIncidents.length ? <details className="duplicate-occurrences"><summary><span><small>Grouped by Jira</small><strong>{row.duplicateIncidents.length + 1} total occurrences</strong></span><span>Duplicates are merged into {jiraKey}; view history</span></summary><div className="duplicate-occurrence-summary"><span><small>First observed</small><strong>{formatIstTimestamp([...row.duplicateIncidents, row].sort((a, b) => incidentTime(a) - incidentTime(b))[0]?.created_at)}</strong></span><span><small>Latest observed</small><strong>{formatIstTimestamp([...row.duplicateIncidents, row].sort((a, b) => incidentTime(b) - incidentTime(a))[0]?.updated_at)}</strong></span><span><small>Service</small><strong>{row.service || "Unknown service"}</strong></span></div><div className="duplicate-occurrence-list">{row.duplicateIncidents.map((duplicate) => { const duplicateId = String(duplicate.incident_id || duplicate.id || "Not recorded"); return <div key={duplicateId}><code>{duplicateId}</code><span>{formatIstTimestamp(duplicate.updated_at || duplicate.created_at)}</span><span>{incidentStatusLabel(duplicate)}</span></div>; })}</div></details> : null}
          </div> : null}
        </article>;
      }) : null}
      {showUnified && !visibleUnifiedRecords.length && !incidents.loading && !alerts.loading ? <p className="empty-state unified-empty-state"><ScanSearch size={22} />No unified inbox records match this view.<small>Try another attention view or clear the service search.</small></p> : null}
      {showAlerts && !visibleAlerts.length && !alerts.loading ? <p className="empty-state">No signals match this view.</p> : null}
      {showIncidents && !rows.length && !incidents.loading ? <p className="empty-state">No incidents match this view.</p> : null}
    </div>
    <footer className="table-pagination"><span>Showing {totalRecords ? ((page - 1) * PAGE_SIZE) + 1 : 0}-{Math.min(page * PAGE_SIZE, totalRecords)} of {totalRecords}</span><div><button className="button-secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button><span>{page} / {pages}</span><button className="button-secondary" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>Next</button></div></footer>
  </section>;
}
