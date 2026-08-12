import { useEffect, useState } from "react";
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

export default function AlertsRoute() {
  const alerts = useRouteRuntimeSlice("alerts");
  const [dedupWindow, setDedupWindow] = useState(60);
  const [dedupSaving, setDedupSaving] = useState(false);
  const [dedupMessage, setDedupMessage] = useState("");
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

    <article className="panel ingestion-stream-panel">
      <div className="ingestion-stream-toolbar"><div><span className="discovery-eyebrow">Landing-pad events</span><h3>{alerts.channel === "all" ? "All source activity" : alerts.channel === "failed" ? "Failed ingestion activity" : `${sourceChannelLabel(alerts.channel)} activity`}</h3></div><label><span>Search alerts</span><input value={alerts.query} onChange={(event) => alerts.setQuery(event.target.value)} placeholder="Alert, service, project, or source" /></label></div>
      {alerts.error ? <p className="error">Live data could not be refreshed. Existing results are preserved. {alerts.error}</p> : null}
      <div className="ingestion-stream-list" aria-live="off">{alerts.rows.map((row) => {
        const display = displayAlert(row);
        const channel = display.channel;
        const failed = String(row.status || "").toLowerCase() === "failed" || Boolean(row.error);
        return <article className={`ingestion-event channel-${channel} ${failed ? "is-failed" : ""}`} key={alertRowKey(row)}><div className="ingestion-event-marker"><span>{channelIcon(channel)}</span><i aria-hidden="true" /></div><div className="ingestion-event-main"><header><div><strong>{display.title}</strong><span className={`source-badge source-${channel}`}>{sourceChannelLabel(channel)}</span><span className={`pill ${failed ? "status-failed" : statusPillClass(row.status || "processed")}`}>{display.status}</span></div><time>{display.lastSeen}</time></header><p>{display.summary}</p><footer><span><b>Service</b>{display.service}</span><span><b>Project</b>{display.project}</span><span><b>Severity</b>{display.severity}</span><span title={row.file}><b>File</b>{display.file}</span><span><b>First seen</b>{display.firstSeen}</span><span><b>Last seen</b>{display.lastSeen}</span><span><b>Occurrences</b>{display.occurrences}</span><span><b>Owner</b>{display.owner}</span></footer>{!failed ? <button type="button" className="button-secondary ingestion-open-action" onClick={() => alerts.open(row)}>Open incident cockpit</button> : null}{row.error ? <small className="ingestion-event-error">{compactText(richText(row.error), 240)}</small> : null}</div></article>;
      })}{!alerts.rows.length && !alerts.loading ? <div className="ingestion-stream-empty"><strong>No alerts match this view</strong><p>Change the filters or verify the selected connector is delivering events.</p></div> : null}</div>
    </article>
  </section>;
}
