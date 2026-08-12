import { useRouteRuntime } from "../../app/routeRuntime";
const formatTime = (value?: string) => value ? new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "-";

export default function ClosedIncidentsRoute() {
  const { closed } = useRouteRuntime();
  return <section className="grid single-col"><article className="panel">
    <div className="panel-head"><h2>Closed Tickets</h2><p>Closed tickets and current closure report summary.</p><button className="button-secondary" onClick={closed.refresh}>Refresh</button></div>
    <div className="filter-grid sticky-controls"><label>Filter by Risk Tier<select value={closed.risk} onChange={(event) => closed.setRisk(event.target.value)}><option value="all">all</option>{closed.riskOptions.map((option) => <option key={`risk-${option}`} value={option}>{option}</option>)}</select></label><label>Filter by Execution Mode<select value={closed.mode} onChange={(event) => closed.setMode(event.target.value)}><option value="all">all</option>{closed.modeOptions.map((option) => <option key={`mode-${option}`} value={option}>{option}</option>)}</select></label></div>
    <p className="subtitle">Showing {closed.rows.length} filtered records</p>{closed.error ? <p className="error">{closed.error}</p> : null}
    <div className="table-wrap"><table><thead><tr><th>Incident</th><th>Service</th><th>Severity</th><th>Status</th><th>Jira</th><th>Closed At</th></tr></thead><tbody>{closed.rows.map((row, index) => <tr key={row.incident_id || index}><td>{row.incident_id || "-"}</td><td>{row.service || "-"}</td><td>{row.severity || "-"}</td><td><span className={`pill status-${String(row.status || "closed").toLowerCase()}`}>{row.status || "closed"}</span></td><td><strong>{row.ticket_id || "-"}</strong></td><td>{formatTime(row.closed_at || row.updated_at)}</td></tr>)}{!closed.rows.length && !closed.loading ? <tr><td colSpan={6}>No closed incidents available.</td></tr> : null}</tbody></table></div>
  </article></section>;
}
