import { useEffect, useState } from "react";
import { Activity, BellRing, Braces, Database, FileCode2, GitMerge, RadioTower, Ticket } from "lucide-react";
import { compactText, fetchJson, formatIstTimestamp, sourceChannelLabel, statusPillClass } from "../../appHelpers.jsx";
import { useRouteRuntimeSlice, type AlertStreamFilters, type AlertStreamRow } from "../../app/routeRuntime";
import { OperationsWorkflowNav } from "../../components/operations/OperationsWorkflowNav";

const channels = [
  ["all", "ALL", "All arrivals"], ["prometheus", "PR", "Prometheus"],
  ["telemetry", "OT", "Telemetry"], ["email", "EM", "Email"],
  ["log", "LG", "Logs / OpenSearch"], ["ticket", "TK", "Tickets / Jira"],
  ["failed", "!", "Failed intake"],
] as const;

function alertRowKey(row: AlertStreamRow): string {
  const identity = (row as AlertStreamRow & { alert_id?: string; fingerprint?: string }).alert_id
    || (row as AlertStreamRow & { fingerprint?: string }).fingerprint;
  return String(identity || row.id || row.file || [row.source_channel, row.name || row.alert_name, row.service, row.received_at || row.created_at].join("::"));
}

function channelIcon(channel: string) {
  return ({ email: "EM", log: "LG", ticket: "TK", telemetry: "OT", prometheus: "PR" } as Record<string, string>)[channel] || "AL";
}

function richText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") {
    const text = value.trim();
    if ((text.startsWith("{") || text.startsWith("[")) && text.length > 2) {
      try { return richText(JSON.parse(text)); } catch { return text; }
    }
    return text;
  }
  if (Array.isArray(value)) return value.map(richText).filter(Boolean).join(" ");
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (record.type === "text") return String(record.text || "").trim();
    return richText(record.content || record.text || record.description || record.summary || "");
  }
  return String(value);
}

function normalizedChannel(row: AlertStreamRow): string {
  const raw = String(row.source_channel || row.origin_system || row.source || "prometheus").toLowerCase();
  if (raw.includes("jira") || raw.includes("ticket")) return "ticket";
  if (raw.includes("mail") || raw.includes("email")) return "email";
  if (raw.includes("log") || raw.includes("opensearch")) return "log";
  if (raw.includes("otel") || raw.includes("telemetry")) return "telemetry";
  return "prometheus";
}

function displayAlert(row: AlertStreamRow) {
  const channel = normalizedChannel(row);
  const metadata = row as AlertStreamRow & Record<string, unknown>;
  const annotations = row.annotations || {};
  const labels = row.labels || {};
  const rawSummary = row.description || annotations.description || metadata.summary || metadata.message || row.error;
  return {
    channel,
    title: compactText(richText(row.name || row.alert_name || metadata.title), 100) || "Unnamed alert",
    summary: compactText(richText(rawSummary), 240) || "Alert received and normalized by the landing pad.",
    status: String(row.status || metadata.alert_status || "processed").replaceAll("_", " ").toUpperCase(),
    service: String(row.service || metadata.component || "-"),
    project: String(row.application || row.project_name || row.project || labels.application || labels.project_name || labels.project || "-"),
    severity: String(row.severity || metadata.priority || "-").toUpperCase(),
    file: compactText(row.file, 44) || "-",
    firstSeen: formatIstTimestamp(row.first_seen || row.starts_at || row.created_at || row.received_at),
    lastSeen: formatIstTimestamp(row.last_seen || row.ends_at || row.updated_at || row.received_at || row.created_at),
    occurrences: Number(row.occurrence_count || row.occurrences?.length || 1),
    owner: String(row.assignee || row.owner || row.jira_assignee || "Unassigned"),
  };
}

const flowStages = [
  ["target", "Target", RadioTower], ["scrape", "Scrape /metrics", Activity], ["parse", "Parse metrics", Braces],
  ["store", "Store series", Database], ["rule", "Evaluate rule", FileCode2], ["alert", "Create alert", BellRing],
] as const;

function processedAlertId(row: AlertStreamRow | null): string {
  if (!row) return "";
  const record = row as AlertStreamRow & { alert_id?: string };
  const candidates = [record.alert_id, row.id].map((value) => String(value || "").trim());
  return candidates.find((value) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) || "";
}

function canonicalMatch(source: AlertStreamRow, candidates: any[]): any | null {
  const input = source as AlertStreamRow & Record<string, any>;
  const fingerprint = String(input.fingerprint || input.labels?.fingerprint || input.labels?.alert_fingerprint || "").trim();
  const name = String(source.name || source.alert_name || input.labels?.alertname || "").trim().toLowerCase();
  const service = String(source.service || input.labels?.service || input.labels?.job || "").trim().toLowerCase();
  const sourceTime = Date.parse(String(source.starts_at || source.created_at || source.received_at || ""));
  const uuidRows = candidates.filter((row) => processedAlertId(row));
  if (fingerprint) {
    const exact = uuidRows.find((row) => String(row.fingerprint || row.labels?.fingerprint || row.labels?.alert_fingerprint || "").trim() === fingerprint);
    if (exact) return exact;
  }
  return uuidRows
    .map((row) => {
      const rowName = String(row.name || row.alert_name || row.labels?.alertname || "").trim().toLowerCase();
      const rowService = String(row.service || row.labels?.service || row.labels?.job || "").trim().toLowerCase();
      const rowTime = Date.parse(String(row.starts_at || row.created_at || row.received_at || ""));
      const timeDelta = Number.isFinite(sourceTime) && Number.isFinite(rowTime) ? Math.abs(sourceTime - rowTime) : Number.MAX_SAFE_INTEGER;
      return { row, score: (name && rowName === name ? 4 : 0) + (service && rowService === service ? 2 : 0) + (timeDelta <= 300000 ? 2 : timeDelta <= 3600000 ? 1 : 0) };
    })
    .filter((item) => item.score >= 6)
    .sort((a, b) => b.score - a.score)[0]?.row || null;
}

function workflowFacts(payload: any) {
  const root = payload?.data && typeof payload.data === "object" ? payload.data : payload || {};
  const alert = root.alert || {};
  const incident = root.incident || root.projection || {};
  const context = root.context || {};
  const recommendation = root.recommendation || {};
  const metadata = context.metadata || recommendation.metadata || {};
  const report = metadata.discovery_report || {};
  const evidence = Array.isArray(report.evidence) ? report.evidence
    : Array.isArray(metadata.discovery_evidence) ? metadata.discovery_evidence
      : Object.values(metadata.discovery_evidence || {}).flat().filter((item) => item && typeof item === "object");
  const timeline = Array.isArray(root.timeline) ? root.timeline : [];
  const ticket = incident.ticket_id || incident.jira_key || root.ticket_id || alert.ticket_id;
  const duplicate = alert.deduplication_reason || incident.deduplication_reason || metadata.deduplication_reason;
  return { root, alert, incident, context, recommendation, metadata, report, evidence, timeline, ticket, duplicate };
}

function metricTrace(row: AlertStreamRow | null) {
  if (!row) return null;
  const metadata = row as AlertStreamRow & Record<string, any>;
  const labels = { ...(metadata.labels || {}), ...(metadata.metric_labels || {}) } as Record<string, any>;
  const annotations = { ...(metadata.annotations || {}) } as Record<string, any>;
  const alertName = String(row.name || row.alert_name || labels.alertname || "Prometheus alert");
  const target = String(labels.instance || metadata.target || metadata.endpoint || row.service || "Target not recorded");
  const metric = String(metadata.metric || labels.metric || (labels.job === "blackbox" ? "probe_success" : labels.__name__ || "Metric not recorded"));
  const value = metadata.metric_value ?? metadata.value ?? (alertName.toLowerCase().includes("unavailable") ? 0 : "See Prometheus");
  const expression = String(metadata.rule_expression || metadata.expr || annotations.expression || (metric === "probe_success" ? `${metric} == 0` : "Rule expression not included in alert payload"));
  return {
    alertName, target, metric, value, expression,
    status: String(row.status || metadata.alert_status || "firing").toLowerCase(),
    severity: String(row.severity || labels.severity || "not recorded"),
    job: String(labels.job || "not recorded"),
    started: formatIstTimestamp(row.starts_at || row.first_seen || row.created_at || row.received_at),
    description: richText(row.description || annotations.description || metadata.summary),
    labels,
  };
}

export default function AlertsRoute() {
  const alerts = useRouteRuntimeSlice("alerts");
  const [dedupWindow, setDedupWindow] = useState(60);
  const [dedupSaving, setDedupSaving] = useState(false);
  const [dedupMessage, setDedupMessage] = useState("");
  const prometheusRows = alerts.rows.filter((row) => normalizedChannel(row) === "prometheus");
  const [traceAlert, setTraceAlert] = useState<AlertStreamRow | null>(null);
  const [traceStage, setTraceStage] = useState("alert");
  const [traceWorkflow, setTraceWorkflow] = useState<{ loading: boolean; data: any; error: string; alertId: string; state: "idle" | "loading" | "ready" | "pending" | "error" }>({ loading: false, data: null, error: "", alertId: "", state: "idle" });
  const activeTraceAlert = traceAlert && alerts.rows.some((row) => alertRowKey(row) === alertRowKey(traceAlert)) ? traceAlert : prometheusRows[0] || null;
  const trace = metricTrace(activeTraceAlert);
  const traceSource = (activeTraceAlert || {}) as AlertStreamRow & Record<string, any>;
  const traceFileName = String(traceSource.file || traceSource.filename || "").trim();
  const traceObjectId = String(traceSource.object_id || "").trim();
  const traceFileUrl = traceObjectId ? `/api-gateway/landing-pad/objects/${encodeURIComponent(traceObjectId)}/download` : "";
  const traceExtract = {
    alert_name: traceSource.name || traceSource.alert_name || traceSource.labels?.alertname || null,
    service: traceSource.service || traceSource.labels?.service || null,
    application: traceSource.application || traceSource.project_name || traceSource.labels?.application || null,
    severity: traceSource.severity || traceSource.labels?.severity || null,
    status: traceSource.status || traceSource.alert_status || null,
    source: traceSource.source || traceSource.source_channel || null,
    starts_at: traceSource.starts_at || traceSource.first_seen || traceSource.received_at || null,
    labels: traceSource.labels || {},
    annotations: traceSource.annotations || {},
  };
  const facts = workflowFacts(traceWorkflow.data);
  useEffect(() => {
    let active = true;
    const load = async () => {
      let alertId = processedAlertId(activeTraceAlert);
      setTraceWorkflow({ loading: true, data: null, error: "", alertId, state: "loading" });
      try {
        if (!alertId && activeTraceAlert) {
          const response = await fetchJson("/api-gateway/alerts/all?limit=500&tenant_id=default&compact=false", { timeoutMs: 12000, maxAttempts: 1 }) as any;
          const rows = response?.data?.rows || response?.rows || response?.data || [];
          const match = canonicalMatch(activeTraceAlert, Array.isArray(rows) ? rows : []);
          alertId = processedAlertId(match);
        }
        if (!alertId) throw new Error("Canonical alert is still being persisted; processed context is not available yet.");
        const data = await fetchJson(`/api-gateway/alerts/${encodeURIComponent(alertId)}/processed-result`, { timeoutMs: 12000, maxAttempts: 1 });
        if (active) setTraceWorkflow({ loading: false, data, error: "", alertId, state: "ready" });
      } catch (error) {
        const message = error instanceof Error ? error.message : "Processed result unavailable";
        const notProcessed = message.includes("HTTP 404") || message.includes("No processed result found");
        if (active) setTraceWorkflow({ loading: false, data: null, error: notProcessed ? "" : message, alertId, state: notProcessed ? "pending" : "error" });
      }
    };
    load();
    return () => { active = false; };
  }, [activeTraceAlert && alertRowKey(activeTraceAlert)]);
  useEffect(() => {
    let active = true;
    fetchJson("/alert-intelligence/deduplication/config", { timeoutMs: 8000 })
      .then((value: unknown) => { const payload = value as { window_minutes?: number }; if (active) setDedupWindow(Number(payload.window_minutes || 60)); })
      .catch(() => { if (active) setDedupMessage("Using the configured 60-minute default"); });
    return () => { active = false; };
  }, []);
  const saveDedupWindow = async () => {
    setDedupSaving(true);
    setDedupMessage("");
    try {
      const payload = await fetchJson("/alert-intelligence/deduplication/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ window_minutes: dedupWindow }),
        timeoutMs: 8000,
      }) as { window_minutes?: number };
      setDedupWindow(Number(payload.window_minutes || dedupWindow));
      setDedupMessage("Applied to new alerts");
    } catch (error) {
      setDedupMessage(error instanceof Error ? error.message : "Could not update duplicate window");
    } finally {
      setDedupSaving(false);
    }
  };
  const updateFilter = (name: keyof AlertStreamFilters, value: string) => {
    alerts.setView("");
    alerts.updateFilter(name, value);
  };

  return <section className="grid single-col ingestion-stream-page operations-page">
    <OperationsWorkflowNav active="alerts" />
    <article className="operations-page-hero ingestion-stream-hero">
      <div><span className="discovery-eyebrow">Signal operations</span><h2>Live Alerts</h2><p>Monitor normalized arrivals across every connected application and source.</p></div>
      <div className="ingestion-live-state"><span className={`ingestion-live-dot ${alerts.loading ? "is-loading" : ""} ${alerts.paused ? "is-paused" : ""}`} aria-hidden="true" /><div><strong>{alerts.paused ? "Updates paused" : alerts.liveState === "connected" ? "Live connection healthy" : alerts.loading ? "Synchronizing" : "Polling fallback active"}</strong><small>{alerts.rows.length} of {alerts.totalRows} arrivals shown</small><small>{alerts.updatedAt ? `Updated ${new Date(alerts.updatedAt).toLocaleString()}` : "Waiting for first sync"}</small></div><button type="button" className="button-secondary" onClick={alerts.refresh} disabled={alerts.loading}>{alerts.loading ? "Refreshing…" : "Refresh"}</button><button type="button" className="button-secondary" aria-pressed={alerts.paused} onClick={alerts.togglePaused}>{alerts.paused ? "Resume" : "Pause"}</button></div>
    </article>

    <article className="panel ingestion-control-panel">
      <div className="ingestion-section-tabs" role="tablist" aria-label="Alert lifecycle sections">{["active", "resolved", "failed", "historical"].map((section) => <button type="button" role="tab" aria-selected={alerts.section === section} className={`detail-tab ${alerts.section === section ? "active" : ""}`} key={section} onClick={() => { alerts.setSection(section); alerts.setView(""); }}>{section === "failed" ? "Failed Intake" : section.charAt(0).toUpperCase() + section.slice(1)}</button>)}</div>
      <div className="ingestion-filter-grid">
        <label>Saved view<select value={alerts.view} onChange={(event) => event.target.value ? alerts.applyView(event.target.value) : alerts.setView("")}><option value="">Custom / all active</option>{alerts.savedViews.map((view) => <option key={view.id} value={view.id}>{view.label}</option>)}</select></label>
        <label>Time range<select value={alerts.filters.timeRange} onChange={(event) => updateFilter("timeRange", event.target.value)}><option value="1h">Last hour</option><option value="24h">Last 24 hours</option><option value="7d">Last 7 days</option><option value="all">All loaded</option></select></label>
        <label>Severity<select value={alerts.filters.severity} onChange={(event) => updateFilter("severity", event.target.value)}><option value="all">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="warning">Warning</option><option value="info">Info</option></select></label>
        <label>Environment<select value={alerts.filters.environment} onChange={(event) => updateFilter("environment", event.target.value)}><option value="all">All environments</option>{alerts.filterOptions.environments.map((environment) => <option key={environment} value={environment}>{environment}</option>)}</select></label>
        <label className="ingestion-density-toggle"><input type="checkbox" checked={alerts.density === "compact"} onChange={(event) => alerts.setDensity(event.target.checked ? "compact" : "comfortable")} />Compact rows</label>
        <label>Duplicate window<select value={dedupWindow} disabled={dedupSaving} onChange={(event) => { setDedupWindow(Number(event.target.value)); setDedupMessage(""); }}><option value={15}>15 minutes</option><option value={30}>30 minutes</option><option value={60}>1 hour</option><option value={120}>2 hours</option><option value={240}>4 hours</option><option value={1440}>24 hours</option></select></label>
        <button type="button" className="button-secondary" disabled={dedupSaving} onClick={saveDedupWindow}>{dedupSaving ? "Saving..." : "Apply window"}</button>
        {dedupMessage ? <small className="dedup-config-status" role="status">{dedupMessage}</small> : null}
      </div>
    </article>

    <div className="ingestion-channel-grid" aria-label="Alert source counts">{channels.map(([channel, icon, label]) => <button type="button" key={channel} className={`ingestion-channel-card channel-${channel} ${alerts.channel === channel ? "is-active" : ""}`} onClick={() => alerts.setChannel(channel)} aria-pressed={alerts.channel === channel}><span>{icon}</span><div><strong>{alerts.counts[channel] || 0}</strong><small>{label}</small></div></button>)}</div>

    {trace ? <article className="panel metric-alert-trace">
      <div className="panel-head"><div><span className="discovery-eyebrow">Prometheus execution</span><h3>Metric-to-Alert Trace</h3><p>{trace.alertName} · {trace.target}</p></div><span className={`pill ${statusPillClass(trace.status)}`}>{trace.status.toUpperCase()}</span></div>
      <div className="metric-trace-flow" aria-label="Prometheus metric to alert flow">{flowStages.map(([id, label, Icon], index) => <button key={id} type="button" className={`${traceStage === id ? "is-selected" : ""} ${id === "alert" ? "is-alert" : ""}`} onClick={() => setTraceStage(id)} aria-pressed={traceStage === id}><span className="metric-trace-sequence">{String(index + 1).padStart(2, "0")}</span><i><Icon size={19} /></i><strong>{label}</strong><small>{id === "target" ? trace.job : id === "scrape" ? "/metrics polled" : id === "parse" ? `${trace.metric} = ${trace.value}` : id === "store" ? "Time series" : id === "rule" ? "Condition matched" : trace.alertName}</small></button>)}</div>
      <div className="metric-trace-details">
        <strong>{flowStages.find(([id]) => id === traceStage)?.[1]}</strong>
        {traceStage === "target" ? <dl><div><dt>Endpoint</dt><dd>{trace.target}</dd></div><div><dt>Prometheus job</dt><dd>{trace.job}</dd></div></dl> : null}
        {traceStage === "scrape" ? <><dl><div><dt>Request</dt><dd>Prometheus periodically requests the target metrics endpoint.</dd></div><div><dt>Result</dt><dd>Metric payload parsed successfully; otherwise target health becomes down.</dd></div><div><dt>Landing file</dt><dd>{traceFileName || "Filename not recorded"}</dd></div><div><dt>File URL</dt><dd>{traceFileUrl ? <a href={traceFileUrl} target="_blank" rel="noreferrer">Open original alert file</a> : traceSource.object_uri ? <code>{String(traceSource.object_uri)}</code> : "Live-buffer file; durable download URL is not available yet."}</dd></div></dl><pre className="metric-parsed-extract">{JSON.stringify(traceExtract, null, 2)}</pre></> : null}
        {traceStage === "parse" ? <><dl><div><dt>Metric</dt><dd><code>{trace.metric}</code></dd></div><div><dt>Observed value</dt><dd>{String(trace.value)}</dd></div><div><dt>Parsed from</dt><dd>{traceFileName || "Canonical alert payload"}</dd></div><div><dt>Fields extracted</dt><dd>alert name, service, application, severity, status, source, timestamps, labels, and annotations</dd></div></dl><pre className="metric-parsed-extract">{JSON.stringify(traceExtract, null, 2)}</pre></> : null}
        {traceStage === "store" ? <dl><div><dt>Series identity</dt><dd><code>{trace.metric}{`{job="${trace.job}"}`}</code></dd></div><div><dt>Labels retained</dt><dd>{Object.keys(trace.labels).join(", ") || "Not recorded"}</dd></div></dl> : null}
        {traceStage === "rule" ? <dl><div><dt>Expression</dt><dd><code>{trace.expression}</code></dd></div><div><dt>Decision</dt><dd>The observed series satisfied the configured alert condition.</dd></div></dl> : null}
        {traceStage === "alert" ? <dl><div><dt>Alert</dt><dd>{trace.alertName}</dd></div><div><dt>Severity / state</dt><dd>{trace.severity} / {trace.status}</dd></div><div><dt>First observed</dt><dd>{trace.started}</dd></div><div><dt>Description</dt><dd>{trace.description || "No description received"}</dd></div></dl> : null}
      </div>
      <div className="metric-handoff">
        <div className="metric-handoff-title"><div><span className="discovery-eyebrow">Downstream handoff</span><strong>{traceWorkflow.state === "ready" ? "Alert entered incident processing" : traceWorkflow.state === "pending" ? "Alert only · incident decision pending" : "Checking incident processing"}</strong></div>{traceWorkflow.loading ? <small>Loading status...</small> : traceWorkflow.error ? <small>Processing status could not be loaded. Retry with Refresh.</small> : traceWorkflow.state === "pending" ? <small>No incident projection has been created for this alert.</small> : null}</div>
        {traceWorkflow.data ? <div className="metric-handoff-row">
          <div><i><GitMerge size={17} /></i><span><small>Disposition</small><strong>{facts.incident.incident_disposition || facts.alert.incident_disposition || (facts.duplicate ? "Duplicate" : "Incident")}</strong></span></div>
          <div><i><BellRing size={17} /></i><span><small>Incident</small><strong>{facts.incident.id || facts.incident.incident_id || "Not created"}</strong></span></div>
          <div><i><Ticket size={17} /></i><span><small>Jira</small><strong>{facts.ticket || "Not created"}</strong></span></div>
          <div><i><FileCode2 size={17} /></i><span><small>Context</small><strong>{facts.evidence.length ? `${facts.evidence.length} evidence item(s)` : "Not collected"}</strong></span></div>
          <button type="button" className="button-primary" onClick={() => activeTraceAlert && alerts.open(activeTraceAlert)}>Open incident details</button>
        </div> : traceWorkflow.state === "pending" ? <div className="metric-handoff-pending"><i><BellRing size={17} /></i><div><strong>No incident created yet</strong><small>The alert is visible in Live Stream while normalization, deduplication, or the incident decision catches up.</small></div></div> : traceWorkflow.state === "error" ? <p className="subtitle">The downstream status is temporarily unavailable. The verified Prometheus trace remains visible above.</p> : null}
      </div>
    </article> : null}

    <article className="panel ingestion-stream-panel">
      <div className="ingestion-stream-toolbar"><div><span className="discovery-eyebrow">Landing-pad events</span><h3>{alerts.channel === "all" ? "All source activity" : alerts.channel === "failed" ? "Failed ingestion activity" : `${sourceChannelLabel(alerts.channel)} activity`}</h3></div><label><span>Search alerts</span><input value={alerts.query} onChange={(event) => alerts.setQuery(event.target.value)} placeholder="Alert, service, project, or source" /></label></div>
      {alerts.error ? <p className="error">Live data could not be refreshed. Existing results are preserved. {alerts.error}</p> : null}
      <div className="ingestion-stream-list" aria-live="off">{alerts.rows.map((row) => {
        const display = displayAlert(row);
        const channel = display.channel;
        const failed = String(row.status || "").toLowerCase() === "failed" || Boolean(row.error);
        return <article className={`ingestion-event channel-${channel} ${failed ? "is-failed" : ""}`} key={alertRowKey(row)}><div className="ingestion-event-marker"><span>{channelIcon(channel)}</span><i aria-hidden="true" /></div><div className="ingestion-event-main"><header><div><strong>{display.title}</strong><span className={`source-badge source-${channel}`}>{sourceChannelLabel(channel)}</span><span className={`pill ${failed ? "status-failed" : statusPillClass(row.status || "processed")}`}>{display.status}</span></div><time>{display.lastSeen}</time></header><p>{display.summary}</p><footer><span><b>Service</b>{display.service}</span><span><b>Project</b>{display.project}</span><span><b>Severity</b>{display.severity}</span><span title={row.file}><b>File</b>{display.file}</span><span><b>First seen</b>{display.firstSeen}</span><span><b>Last seen</b>{display.lastSeen}</span><span><b>Occurrences</b>{display.occurrences}</span><span><b>Owner</b>{display.owner}</span></footer>{channel === "prometheus" ? <button type="button" className="button-secondary ingestion-open-action" onClick={() => { setTraceAlert(row); setTraceStage("target"); document.querySelector(".metric-alert-trace")?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>Trace metric flow</button> : null}{!failed ? <button type="button" className="button-secondary ingestion-open-action" onClick={() => alerts.open(row)}>Open incident cockpit</button> : null}{row.error ? <small className="ingestion-event-error">{compactText(richText(row.error), 240)}</small> : null}</div></article>;
      })}{!alerts.rows.length && !alerts.loading ? <div className="ingestion-stream-empty"><strong>No alerts match this view</strong><p>Change the filters or verify the selected connector is delivering events.</p></div> : null}</div>
    </article>
  </section>;
}
