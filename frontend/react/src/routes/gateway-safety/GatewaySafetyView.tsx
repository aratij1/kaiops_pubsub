import { useRouteRuntime } from "../../app/routeRuntime";
const formatTime = (value?: string) => value ? `${new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST` : "-";

export function GatewaySafetyView() {
  const { safety } = useRouteRuntime();
  return <section className="grid single-col"><article className="panel">
    <div className="panel-head"><h2>Gateway Safety</h2><p>Review gateway decision, policy reasons, and safety metrics before closure.</p><button className="button-secondary" onClick={safety.refresh}>Refresh</button></div>
    {safety.summaryError ? <p className="error">{safety.summaryError}</p> : null}
    <div className="stat-grid"><div className="stat-card"><strong>Total</strong><span>{safety.summary.total_events || 0}</span></div><div className="stat-card"><strong>Allowed</strong><span>{safety.summary.allowed || 0}</span></div><div className="stat-card"><strong>Review</strong><span>{safety.summary.review || 0}</span></div><div className="stat-card"><strong>Blocked</strong><span>{safety.summary.blocked || 0}</span></div></div>
    <p className="subtitle">Latest trace: {safety.summary.latest_trace_id || "-"}</p><h3>Recent Gateway Events</h3>
    <div className="table-wrap"><table><thead><tr><th>Path</th><th>Status</th><th>Decision</th><th>Score</th><th>Latency ms</th><th>Reasons</th></tr></thead><tbody>{safety.events.map((row, index) => <tr key={`${row.trace_id || "gw"}-${index}`}><td>{row.path || "-"}</td><td>{row.status_code || "-"}</td><td>{row.safety?.decision || "-"}</td><td>{row.safety?.score ?? "-"}</td><td>{row.latency_ms || "-"}</td><td>{Array.isArray(row.safety?.reasons) ? row.safety.reasons.join("; ") : "-"}</td></tr>)}{!safety.events.length ? <tr><td colSpan={6}>No gateway events yet.</td></tr> : null}</tbody></table></div>
    <h3>Landing Pad Realtime Ingestion</h3>{safety.landingError ? <p className="error">{safety.landingError}</p> : null}
    <div className="table-wrap"><table><thead><tr><th>Received At (IST)</th><th>Alert</th><th>Service</th><th>Severity</th><th>Status</th><th>File</th></tr></thead><tbody>{safety.landingRows.map((row, index) => <tr key={`${row.file || "landing-pad"}-${index}`}><td>{formatTime(row.received_at || row.modified_at)}</td><td>{row.name || row.alertname || "-"}</td><td>{row.service || "-"}</td><td>{String(row.severity || "-").toUpperCase()}</td><td>{row.alert_status || "-"}</td><td>{row.file || "-"}</td></tr>)}{!safety.landingRows.length ? <tr><td colSpan={6}>No realtime landing-pad ingestion records yet.</td></tr> : null}</tbody></table></div>
  </article></section>;
}
