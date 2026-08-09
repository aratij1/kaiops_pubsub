import { compactText, formatIstTimestamp, sourceChannelLabel, statusPillClass } from "../../appHelpers.jsx";
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

export default function AlertsRoute() {
  const alerts = useRouteRuntimeSlice("alerts");
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
      </div>
    </article>

    <div className="ingestion-channel-grid" aria-label="Alert source counts">{channels.map(([channel, icon, label]) => <button type="button" key={channel} className={`ingestion-channel-card channel-${channel} ${alerts.channel === channel ? "is-active" : ""}`} onClick={() => alerts.setChannel(channel)} aria-pressed={alerts.channel === channel}><span>{icon}</span><div><strong>{alerts.counts[channel] || 0}</strong><small>{label}</small></div></button>)}</div>

    <article className="panel ingestion-stream-panel">
      <div className="ingestion-stream-toolbar"><div><span className="discovery-eyebrow">Landing-pad events</span><h3>{alerts.channel === "all" ? "All source activity" : alerts.channel === "failed" ? "Failed ingestion activity" : `${sourceChannelLabel(alerts.channel)} activity`}</h3></div><label><span>Search alerts</span><input value={alerts.query} onChange={(event) => alerts.setQuery(event.target.value)} placeholder="Alert, service, project, or source" /></label></div>
      {alerts.error ? <p className="error">Live data could not be refreshed. Existing results are preserved. {alerts.error}</p> : null}
      <div className="ingestion-stream-list" aria-live="off">{alerts.rows.map((row) => {
        const channel = row.source_channel || "prometheus";
        const failed = String(row.status || "").toLowerCase() === "failed" || Boolean(row.error);
        return <article className={`ingestion-event channel-${channel} ${failed ? "is-failed" : ""}`} key={alertRowKey(row)}><div className="ingestion-event-marker"><span>{channelIcon(channel)}</span><i aria-hidden="true" /></div><div className="ingestion-event-main"><header><div><strong>{row.name || row.alert_name || "Unnamed alert"}</strong><span className={`source-badge source-${channel}`}>{sourceChannelLabel(channel)}</span><span className={`pill ${failed ? "status-failed" : statusPillClass(row.status || "processed")}`}>{row.status || "processed"}</span></div><time>{formatIstTimestamp(row.received_at || row.created_at || row.modified_at)}</time></header><p>{row.description || row.annotations?.description || row.error || "Alert received and normalized by the landing pad."}</p><footer><span><b>Service</b>{row.service || "-"}</span><span><b>Project</b>{row.application || row.project_name || row.project || row.labels?.application || row.labels?.project_name || row.labels?.project || "-"}</span><span><b>Severity</b>{String(row.severity || "-").toUpperCase()}</span><span title={row.file}><b>File</b>{compactText(row.file, 44)}</span><span><b>First seen</b>{formatIstTimestamp(row.first_seen || row.starts_at || row.created_at)}</span><span><b>Last seen</b>{formatIstTimestamp(row.last_seen || row.ends_at || row.updated_at || row.received_at)}</span><span><b>Occurrences</b>{row.occurrence_count || row.occurrences?.length || 1}</span><span><b>Owner</b>{row.assignee || row.owner || row.jira_assignee || "Unassigned"}</span></footer>{!failed ? <button type="button" className="button-secondary ingestion-open-action" onClick={() => alerts.open(row)}>Open incident cockpit</button> : null}{row.error ? <small className="ingestion-event-error">{row.error}</small> : null}</div></article>;
      })}{!alerts.rows.length && !alerts.loading ? <div className="ingestion-stream-empty"><strong>No alerts match this view</strong><p>Change the filters or verify the selected connector is delivering events.</p></div> : null}</div>
    </article>
  </section>;
}
