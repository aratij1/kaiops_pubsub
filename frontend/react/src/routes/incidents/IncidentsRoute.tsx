import { useEffect, useMemo, useState } from "react";
import { Bell, BrainCircuit, Check, CircleSlash2, ClipboardCheck, Copy, ExternalLink, FileCheck2, Filter, GitMerge, RefreshCw, ScanSearch, ShieldCheck, TicketCheck, Wrench } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useRouteRuntimeSlice, type IncidentFilters, type IncidentRow } from "../../app/routeRuntime";
import "./IncidentsRoute.css";

const PAGE_SIZE = 10;

const stageOrder = [
  { id: "ingest", cockpit: "overview", label: "Ingest", detail: "Source received" },
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

const stageIcons = {
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
  const stages: LifecycleStage[] = [
    complete("ingest", value(row.source, row.origin_system, "Received")),
    complete("normalize", value(row.service, "Canonical alert")),
    complete("deduplicate", duplicate ? "Duplicate linked" : Number(row.deduplicated_count || 1) > 1 ? `${row.deduplicated_count} occurrences merged` : "Unique signal"),
    { ...stageOrder[3], state: jiraReady ? "complete" : "current", caption: jiraReady ? String(row.ticket_id || row.jira_key) : "Creating ticket" },
  ];
  if (noise) {
    stages.push({ ...stageOrder[4], state: "stopped", caption: "Noise / no action" });
    return stages;
  }
  if (duplicate) {
    stages.push({ ...stageOrder[4], state: "stopped", caption: "Linked to canonical incident" });
    return stages;
  }
  stages.push(complete("decision", "Incident created"));
  if (contextStarted) {
    stages.push({
      ...stageOrder[5],
      state: contextReady ? (contextState.source.includes("cache") || contextState.source === "ticket_payload" ? "reused" : "complete") : "current",
      caption: contextReady ? contextState.label : "Collecting evidence",
    });
  }
  if (contextReady || understood) {
    stages.push({ ...stageOrder[6], state: understood ? "complete" : "current", caption: understood ? "RCA generated" : "Generating RCA" });
  }
  if (approvalStarted) {
    stages.push({ ...stageOrder[7], state: approvalComplete ? "complete" : "current", caption: approvalComplete ? "Decision recorded" : "Awaiting decision" });
  }
  if (resolved || status === "failed") {
    stages.push({ ...stageOrder[8], state: status === "failed" ? "failed" : "complete", caption: status === "failed" ? "Action required" : "Remediation started" });
  }
  if (["validating", "resolved", "closed"].includes(status)) {
    stages.push({ ...stageOrder[9], state: validated ? "complete" : "current", caption: validated ? "Verified and closed" : "Verifying recovery" });
  }
  return stages;
}

function projectionEvent(row: IncidentRow) {
  const projection = row.projection_payload && typeof row.projection_payload === "object" ? row.projection_payload : {};
  const event = projection.event_payload && typeof projection.event_payload === "object" ? projection.event_payload as Record<string, unknown> : {};
  return event;
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
  const [page, setPage] = useState(1);
  const [inspector, setInspector] = useState<{ incidentId: string; stage: string } | null>(null);
  const pages = Math.max(1, Math.ceil(incidents.rows.length / PAGE_SIZE));
  useEffect(() => setPage((current) => Math.min(current, pages)), [pages]);
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
    {incidents.error ? <p className="error">{incidents.error}</p> : null}
    <div className="incident-summary-list" aria-busy={incidents.loading || alerts.loading}>
      {showAlerts ? visibleAlerts.map((alert, index) => {
        const metadata = (alert as typeof alert & { metadata?: Record<string, unknown> }).metadata || {};
        const noiseMetadata = metadata.noise && typeof metadata.noise === "object" ? metadata.noise as Record<string, unknown> : {};
        const disposition = String(alert.incident_disposition || "").toLowerCase();
        const noise = ["noise", "suppressed", "ignored", "non_actionable"].includes(disposition) || noiseMetadata.classified === true;
        const duplicate = !noise && (disposition === "duplicate" || Number(alert.deduplicated_count || 1) > 1);
        const noiseReason = String(noiseMetadata.reason || alert.suppression_reason || "Non-actionable monitoring noise");
        const linkedIncident = String((alert as typeof alert & { incident_id?: string | number }).incident_id || "");
        return <article className="unified-alert-row" key={String(alert.id || alert.file || index)}>
          <span className={`unified-record-icon ${noise ? "is-noise" : duplicate ? "is-duplicate" : ""}`}>{noise ? <CircleSlash2 size={16} /> : duplicate ? <Copy size={16} /> : <Bell size={16} />}</span>
          <div><small>Alert</small><strong>{alert.name || alert.alert_name || "Unnamed alert"}</strong><p>{alert.service || "Unknown service"} · {alert.origin_system || alert.source || alert.source_channel || "Unknown source"}</p></div>
          <span className="unified-alert-outcome">{duplicate ? "Duplicate · linked to incident" : "New incident signal"}</span>
          <ol className="alert-processing-story"><li>Ingested</li><li>Normalized</li><li>{duplicate ? "Duplicate matched" : "Unique after dedup"}</li><li>{noise ? "Noise / stopped" : linkedIncident ? "Incident created" : "Decision pending"}</li></ol>
          <span className={`unified-alert-result ${noise ? "is-noise" : ""}`} title={noise ? noiseReason : undefined}>{noise ? "Noise / no action" : duplicate ? "Linked to existing incident" : linkedIncident ? "Incident created" : "Processing"}</span>
          <button type="button" className="button-secondary" onClick={() => alerts.open(alert, "overview")}>{noise ? "View alert" : "Open summary"}</button>
        </article>;
      }) : null}
      {showIncidents ? rows.map((row, index) => {
        const incidentId = String(row.incident_id || row.id || "-");
        const jiraKey = String(row.ticket_id || row.jira_key || "Pending");
        const lifecycle = lifecycleFor(row);
        const selectedStage = inspector?.incidentId === incidentId ? inspector.stage : "";
        const event = projectionEvent(row);
        const context = contextPresentation(row);
        const disposition = incidentNoise(row);
        const details: Record<string, Array<[string, string]>> = {
          ingest: [["Source", value(row.source, row.origin_system, event.source)], ["Channel", value(row.ingestion_channel, event.ingestion_channel)], ["Received", value(row.created_at, event.created_at)], ["Alert ID", value(row.alert_id)]],
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
            <div className="incident-flow-caption"><span>Executed path</span><strong>{lifecycle.length} stages</strong></div>
          <div className="incident-lifecycle" style={{ gridTemplateColumns: `repeat(${lifecycle.length}, minmax(112px, 1fr))` }} aria-label={`Lifecycle for ${incidentTitle(row)}`}>
            {lifecycle.map((stage, stageIndex) => {
              const selectable = !["pending", "stopped"].includes(stage.state);
              const StageIcon = stageIcons[stage.id as keyof typeof stageIcons] || FileCheck2;
              return <button key={stage.id} type="button" className={`is-${stage.state} ${selectedStage === stage.id ? "is-selected" : ""}`} disabled={!selectable} title={stage.state === "stopped" ? disposition.reason : stage.caption} onClick={() => selectable && setInspector((current) => current?.incidentId === incidentId && current.stage === stage.id ? null : { incidentId, stage: stage.id })} aria-expanded={selectedStage === stage.id} aria-label={`${stage.label}: ${stage.caption}`}>
                <span className="incident-stage-node"><StageIcon size={17} strokeWidth={2} />{["complete", "reused"].includes(stage.state) ? <i><Check size={9} strokeWidth={3} /></i> : null}</span><span className="incident-stage-copy"><strong>{stage.label}</strong><small>{stage.caption}</small></span><b className="incident-stage-sequence">{String(stageIndex + 1).padStart(2, "0")}</b>
              </button>;
            })}
          </div>
          </div>
          {selectedStage ? <section className="incident-stage-inspector"><header><div><small>Stage details</small><h3>{stageOrder.find((stage) => stage.id === selectedStage)?.label}</h3></div>{selectedStage === "jira" && row.jira_url ? <a className="button-secondary" href={row.jira_url} target="_blank" rel="noreferrer">Open in Jira <ExternalLink size={14} /></a> : <button type="button" className="button-secondary" onClick={() => incidents.open(row, stageOrder.find((stage) => stage.id === selectedStage)?.cockpit || "overview")}>Open detailed view</button>}</header><dl>{(details[selectedStage] || []).map(([label, detail]) => <div key={label}><dt>{label}</dt><dd>{detail}</dd></div>)}</dl></section> : null}
        </article>;
      }) : null}
      {showAlerts && !alerts.rows.length && !alerts.loading && !showIncidents ? <p className="empty-state">No alerts match this view.</p> : null}
      {showIncidents && !rows.length && !incidents.loading && !showAlerts ? <p className="empty-state">No incidents match this view.</p> : null}
    </div>
    {showIncidents ? <footer className="table-pagination"><span>Showing {rows.length ? ((page - 1) * PAGE_SIZE) + 1 : 0}-{Math.min(page * PAGE_SIZE, incidents.rows.length)} of {incidents.rows.length}</span><div><button className="button-secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button><span>{page} / {pages}</span><button className="button-secondary" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>Next</button></div></footer> : null}
  </section>;
}
