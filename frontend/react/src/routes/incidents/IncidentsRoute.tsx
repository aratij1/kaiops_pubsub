import { useRouteRuntime, type IncidentFilters } from "../../app/routeRuntime";

export default function IncidentsRoute() {
  const { incidents } = useRouteRuntime();
  const select = (label: string, name: keyof IncidentFilters, options: string[]) => <label>{label}<select value={incidents.filters[name]} onChange={(event) => incidents.updateFilter(name, event.target.value)}>{options.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>;
  return <section className="grid single-col"><article className="panel">
    <div className="panel-head"><h2>Incident Metadata</h2><p>Incident metadata explorer with policy, transport, and status context.</p><button className="button-secondary" onClick={incidents.refresh}>Refresh</button></div>
    <div className="filter-grid sticky-controls">{select("Risk Tier", "risk_tier", ["all", "high", "medium", "low"])}{select("Execution Mode", "execution_mode", ["all", "human-approval", "guided-auto", "auto-execute"])}{select("Transport", "transport_provider", ["all", "kafka", "rabbitmq", "azure-service-bus"])}{select("Status", "status", ["all", "open", "investigating", "awaiting_approval", "remediating", "validating", "closed", "failed"])}</div>
    <label>Service contains<input value={incidents.filters.service} placeholder="payments" onChange={(event) => incidents.updateFilter("service", event.target.value)} /></label>{incidents.error ? <p className="error">{incidents.error}</p> : null}
    <div className="table-wrap"><table><thead><tr><th>Incident</th><th>Service</th><th>Risk</th><th>Execution Mode</th><th>Provider</th><th>Status</th><th>Action</th></tr></thead><tbody>{incidents.rows.map((row, index) => <tr key={row.incident_id || row.id || index}><td>{row.incident_id || row.id || "-"}</td><td>{row.service || "-"}</td><td>{row.risk_tier || "-"}</td><td>{row.execution_mode || "-"}</td><td>{row.transport_provider || "-"}</td><td><span className={`pill status-${String(row.status || "unknown").toLowerCase()}`}>{row.status || "-"}</span></td><td><button type="button" className="button-secondary" onClick={() => incidents.open(row)}>Open</button></td></tr>)}{!incidents.rows.length && !incidents.loading ? <tr><td colSpan={7}>No incidents available for {incidents.application}. Run one sample flow from Dashboard.</td></tr> : null}</tbody></table></div>
  </article></section>;
}
