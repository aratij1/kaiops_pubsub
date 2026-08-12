import { useEffect, useMemo, useState } from "react";
import { Activity, Bell, BrainCircuit, Check, CircleSlash2, ClipboardCheck, Copy, ExternalLink, FileCheck2, Filter, Gauge, GitMerge, List, RefreshCw, Rows3, ScanSearch, Server, ShieldCheck, TicketCheck, Workflow, Wrench } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useRouteRuntimeSlice, type IncidentFilters, type IncidentRow } from "../../app/routeRuntime";
import "./IncidentsRoute.css";

const PAGE_SIZE = 10;

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
  { id: "understand", cockpit: "rca", label: "Understand", detail: "RCA and impact" },
  { id: "approval", cockpit: "execution", label: "Approval", detail: "Decision gate" },
  { id: "resolve", cockpit: "execution", label: "Resolve", detail: "Plan and remediate" },
  { id: "validate", cockpit: "audit", label: "Validate", detail: "Verify and close" },
];

type StageState = "complete" | "current" | "reused" | "stopped" | "failed";
type LifecycleStage = (typeof stageOrder)[number] & { state: StageState; caption: string };
type Presentation = "summary" | "flow" | "details";

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
  return String(row.status || "open").trim().toLowerCase().replaceAll("-", "_");
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
  const resolved = ["remediating", "validating", "resolved", "closed"].includes(status);
  const validated = ["resolved", "closed"].includes(status);
  const contextStarted = contextReady || latestEvent.includes("context") || understood;
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
    complete("ingest", value(event.received_at, row.created_at, "Received")),
    complete("normalize", value(row.service, "Canonical alert")),
    complete("deduplicate", duplicate ? "Duplicate linked" : Number(row.deduplicated_count || 1) > 1 ? `${row.deduplicated_count} occurrences merged` : "Unique signal"),
    { ...stage("jira"), state: jiraReady ? "complete" : "current", caption: jiraReady ? String(row.ticket_id || row.jira_key) : "Creating ticket" },
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
  if (contextStarted) {
    stages.push({
      ...stage("context"),
      state: contextReady ? (contextState.source.includes("cache") || contextState.source === "ticket_payload" ? "reused" : "complete") : "current",
      caption: contextReady ? contextState.label : "Collecting evidence",
    });
  }
  if (contextReady || understood) {
    stages.push({ ...stage("understand"), state: understood ? "complete" : "current", caption: understood ? "RCA generated" : "Generating RCA" });
  }
  if (approvalStarted) {
    stages.push({ ...stage("approval"), state: approvalComplete ? "complete" : "current", caption: approvalComplete ? "Decision recorded" : "Awaiting decision" });
  }
  if (resolved || status === "failed") {
    stages.push({ ...stage("resolve"), state: status === "failed" ? "failed" : "complete", caption: status === "failed" ? "Action required" : "Remediation started" });
  }
  if (["validating", "resolved", "closed"].includes(status)) {
    stages.push({ ...stage("validate"), state: validated ? "complete" : "current", caption: validated ? "Verified and closed" : "Verifying recovery" });
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
  if (source === "ticket_payload") return { label: "Available in ticket", source, strategy, realtime: false };
  if (["cache", "periodic_cache"].includes(source)) return { label: source === "periodic_cache" ? "Historical snapshot reused" : "Cached context reused", source, strategy, realtime: false };
  if (source === "historical_cache_miss") return { label: "Historical context unavailable", source, strategy, realtime: false };
  if (source === "realtime_collection" || realtime === true) return { label: "Realtime context collected", source: source || "realtime_collection", strategy, realtime: true };
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

export default function IncidentsRoute() {
  const incidents = useRouteRuntimeSlice("incidents");
  const alerts = useRouteRuntimeSlice("alerts");
  const [searchParams] = useSearchParams();
  const [recordType, setRecordType] = useState(searchParams.get("type") === "alerts" ? "alerts" : "incidents");
  const [presentation, setPresentation] = useState<Presentation>(() => {
    const saved = window.localStorage.getItem("kaiops.incident-presentation");
    return saved === "flow" || saved === "details" ? saved : "summary";
  });
  const [page, setPage] = useState(1);
  const [inspector, setInspector] = useState<{ incidentId: string; stage: string } | null>(null);
  const pages = Math.max(1, Math.ceil(incidents.rows.length / PAGE_SIZE));
  useEffect(() => setPage((current) => Math.min(current, pages)), [pages]);
  useEffect(() => window.localStorage.setItem("kaiops.incident-presentation", presentation), [presentation]);
  useEffect(() => setPage(1), [incidents.filters.risk_tier, incidents.filters.execution_mode, incidents.filters.status, incidents.filters.service]);
  const rows = useMemo(() => incidents.rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), [incidents.rows, page]);
  const incidentAlertIds = useMemo(() => new Set(incidents.rows.map((row) => String(row.alert_id || "")).filter(Boolean)), [incidents.rows]);
  const visibleAlerts = useMemo(() => alerts.rows.filter((alert) => {
    if (recordType === "alerts") return true;
    const alertId = String((alert as typeof alert & { alert_id?: string | number }).alert_id || alert.id || "");
    return !alertId || !incidentAlertIds.has(alertId);
  }), [alerts.rows, incidentAlertIds, recordType]);
  const select = (label: string, name: keyof IncidentFilters, options: string[]) => <label>{label}<select value={incidents.filters[name]} onChange={(event) => incidents.updateFilter(name, event.target.value)}>{options.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>;
  const priority = incidents.rows.filter((row) => ["high", "critical"].includes(String(row.risk_tier || row.severity || "").toLowerCase())).length;
  const active = incidents.rows.filter((row) => !["closed", "resolved"].includes(normalizedStatus(row))).length;
  const showAlerts = recordType === "alerts";
  const showIncidents = recordType === "incidents";

  return <section className="grid single-col operations-center">
    <div className="incident-list-heading"><div><h2>Alerts &amp; Incidents</h2><p>One operational queue from signal arrival through verified closure.</p></div><div className="operations-kpis" aria-label="Operational totals"><span><strong>{alerts.rows.length}</strong> alerts</span><span><strong>{active}</strong> active</span><span><strong>{incidents.rows.length}</strong> incidents</span></div></div>
    <div className="compact-filter-bar">
      <label>View<select value={recordType} onChange={(event) => setRecordType(event.target.value)}><option value="incidents">Incidents</option><option value="alerts">Alerts</option></select></label>
      {showIncidents ? <>{select("Risk", "risk_tier", ["all", "high", "medium", "low"])}{select("Status", "status", ["all", "open", "investigating", "awaiting_approval", "remediating", "validating", "closed", "failed"])}<label className="filter-grow">Service<input value={incidents.filters.service} placeholder="Search service" onChange={(event) => incidents.updateFilter("service", event.target.value)} /></label></> : <div className="alert-view-note">Showing alert intake and classification outcomes</div>}
      <button className="icon-button" type="button" onClick={() => { incidents.refresh(); alerts.refresh(); }} title="Refresh queue" aria-label="Refresh queue"><RefreshCw size={17} /></button>
    </div>
    <div className="incident-presentation" role="group" aria-label={`${showAlerts ? "Alert" : "Incident"} presentation`}>
      <span>Display</span>
      <button type="button" className={presentation === "summary" ? "active" : ""} onClick={() => setPresentation("summary")}><List size={15} /><span><strong>Summary</strong><small>Compact table</small></span></button>
      <button type="button" className={presentation === "flow" ? "active" : ""} onClick={() => setPresentation("flow")}><Workflow size={15} /><span><strong>Flow</strong><small>{showAlerts ? "Processing path" : "Executed path"}</small></span></button>
      <button type="button" className={presentation === "details" ? "active" : ""} onClick={() => setPresentation("details")}><Rows3 size={15} /><span><strong>Details</strong><small>{showAlerts ? "Alert evidence" : "Stage evidence"}</small></span></button>
    </div>
    {incidents.error ? <p className="error">{incidents.error}</p> : null}
    <div className={`incident-summary-list view-${presentation}`} aria-busy={incidents.loading || alerts.loading}>
      {showAlerts && presentation === "summary" ? <div className="incident-table-wrap"><table className="incident-summary-table alert-summary-table"><thead><tr><th>Alert</th><th>Source</th><th>Severity</th><th>Classification</th><th>Linked record</th><th>Received</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{visibleAlerts.map((alert, index) => {
        const metadata = (alert as typeof alert & { metadata?: Record<string, unknown> }).metadata || {};
        const noiseMetadata = metadata.noise && typeof metadata.noise === "object" ? metadata.noise as Record<string, unknown> : {};
        const disposition = String(alert.incident_disposition || "").toLowerCase();
        const noise = ["noise", "suppressed", "ignored", "non_actionable"].includes(disposition) || noiseMetadata.classified === true;
        const duplicate = !noise && (disposition === "duplicate" || Number(alert.deduplicated_count || 1) > 1);
        const linkedIncident = String((alert as typeof alert & { incident_id?: string | number }).incident_id || "");
        return <tr key={String(alert.id || alert.file || index)}><td><button type="button" className="incident-table-title" onClick={() => alerts.open(alert, "overview")}>{alert.name || alert.alert_name || "Unnamed alert"}</button><code>{String(alert.id || alert.file || "No alert ID")}</code></td><td><strong>{alert.service || "Unknown service"}</strong><small>{alert.origin_system || alert.source || alert.source_channel || "Unknown source"}</small></td><td>{alert.severity || "Not set"}</td><td><span className={`alert-classification ${noise ? "is-noise" : duplicate ? "is-duplicate" : "is-unique"}`}>{noise ? "Noise" : duplicate ? "Duplicate" : "Unique"}</span></td><td>{linkedIncident || alert.ticket_id || alert.jira_key || (noise ? "No incident" : "Processing")}</td><td>{value(alert.received_at, alert.created_at, alert.first_seen)}</td><td><button type="button" className="button-secondary" onClick={() => { setPresentation("details"); }}>View details</button></td></tr>;
      })}</tbody></table></div> : null}
      {showAlerts && presentation !== "summary" ? visibleAlerts.map((alert, index) => {
        const metadata = (alert as typeof alert & { metadata?: Record<string, unknown> }).metadata || {};
        const noiseMetadata = metadata.noise && typeof metadata.noise === "object" ? metadata.noise as Record<string, unknown> : {};
        const disposition = String(alert.incident_disposition || "").toLowerCase();
        const noise = ["noise", "suppressed", "ignored", "non_actionable"].includes(disposition) || noiseMetadata.classified === true;
        const duplicate = !noise && (disposition === "duplicate" || Number(alert.deduplicated_count || 1) > 1);
        const noiseReason = String(noiseMetadata.reason || alert.suppression_reason || "Non-actionable monitoring noise");
        const linkedIncident = String((alert as typeof alert & { incident_id?: string | number }).incident_id || "");
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
        return <tr key={incidentId || index}><td><button type="button" className="incident-table-title" onClick={() => incidents.open(row, "overview")}>{incidentTitle(row)}</button><code>{incidentId}</code></td><td><strong>{row.service || "Unknown service"}</strong><small>{row.environment || "Environment not set"}</small></td><td><span className={`pill ${normalizedStatus(row) === "failed" ? "status-warning" : `status-${normalizedStatus(row)}`}`}>{incidentStatusLabel(row)}</span></td><td>{row.jira_url ? <a href={row.jira_url} target="_blank" rel="noreferrer">{jiraKey}<ExternalLink size={12} /></a> : jiraKey}</td><td><strong>{currentStage?.label || "Not started"}</strong><small>{currentStage?.caption || "No executed stage"}</small></td><td>{value(row.updated_at, row.created_at)}</td><td><button type="button" className="button-secondary" onClick={() => { setInspector(currentStage ? { incidentId, stage: currentStage.id } : null); setPresentation("details"); }}>View details</button></td></tr>;
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
          context: [["Status", context.label], ["Strategy", context.strategy], ["Source", context.source], ["Realtime collection", context.realtime ? "Performed" : "Not required"]],
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
          <div className="incident-flow-wrap">
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
          </div>
          {presentation === "details" && selectedStage ? <section className="incident-stage-inspector"><header><div><small>Stage details</small><h3>{stageOrder.find((stage) => stage.id === selectedStage)?.label}</h3></div>{selectedStage === "jira" && row.jira_url ? <a className="button-secondary" href={row.jira_url} target="_blank" rel="noreferrer">Open in Jira <ExternalLink size={14} /></a> : <button type="button" className="button-secondary" onClick={() => incidents.open(row, stageOrder.find((stage) => stage.id === selectedStage)?.cockpit || "overview")}>Open detailed view</button>}</header><dl>{(details[selectedStage] || []).map(([label, detail]) => <div key={label}><dt>{label}</dt><dd>{detail}</dd></div>)}</dl></section> : null}
        </article>;
      }) : null}
      {showAlerts && !alerts.rows.length && !alerts.loading && !showIncidents ? <p className="empty-state">No alerts match this view.</p> : null}
      {showIncidents && !rows.length && !incidents.loading && !showAlerts ? <p className="empty-state">No incidents match this view.</p> : null}
    </div>
    {showIncidents ? <footer className="table-pagination"><span>Showing {rows.length ? ((page - 1) * PAGE_SIZE) + 1 : 0}-{Math.min(page * PAGE_SIZE, incidents.rows.length)} of {incidents.rows.length}</span><div><button className="button-secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button><span>{page} / {pages}</span><button className="button-secondary" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>Next</button></div></footer> : null}
  </section>;
}
