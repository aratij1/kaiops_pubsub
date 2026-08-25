import { HorizontalBarChart, SuccessFailureDonut } from "../../appHelpers.jsx";
import { useRouteRuntime } from "../../app/routeRuntime";
const formatTime = (value?: string) => value ? `${new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST` : "-";

export default function ExecutiveRoute() {
  const { executive } = useRouteRuntime();
  const charts = [
    ["Request Volume", "Observed API gateway events in current window", executive.requestChart],
    ["Latency Trend", executive.latencySubtitle, executive.latencyChart],
    ["FinOps Overview", "Aggregated LLM usage and spend", executive.finopsChart],
    ["Closed Tickets by Risk", "Recent closure distribution", executive.riskChart],
    ["Closed Tickets by Execution Mode", "How incidents were handled", executive.modeChart],
    ["Weekly Open Incident Trend", "Open incidents observed per day (7-day window)", executive.weeklyOpenChart],
    ["Weekly Closed Incident Trend", "Closed incidents per day (7-day window)", executive.weeklyClosedChart],
  ] as const;
  return <section className="grid single-col"><article className="panel">
    <div className="panel-head"><h2>Reliability and risk overview</h2><p>Leadership-level snapshot of reliability, risk, and closure trend.</p></div>
    <div className="stat-grid">{executive.statCards.map((card) => <div className="stat-card" key={card.label}><strong>{card.label}</strong><span>{card.value}</span></div>)}</div>
    <div className="executive-chart-grid"><HorizontalBarChart title={charts[0][0]} subtitle={charts[0][1]} items={charts[0][2]} /><SuccessFailureDonut success={executive.successRequests} failure={executive.failedRequests} />{charts.slice(1).map(([title, subtitle, items]) => <HorizontalBarChart key={title} title={title} subtitle={subtitle} items={items} />)}</div>
    <article className="panel executive-flow-panel"><div className="panel-head"><h3>End-to-End Processing + FinOps</h3><p>Landing pad ingestion, parallel worker processing, remediation execution, and cost visibility in one leadership view.</p></div><div className="workflow-guide-grid executive-flow-grid">{executive.workflowStages.map((stage) => <div className="workflow-guide-card executive-flow-card" key={stage.id}><strong>{stage.label}</strong><span className={`workflow-pill workflow-pill-${stage.status}`}>{stage.status.toUpperCase()}</span><p>{stage.detail}</p></div>)}</div>
      <div className="table-wrap table-wrap-scroll-x"><table><thead><tr><th>Backend Service</th><th>Consumes</th><th>Publishes</th><th>Processing Agent</th></tr></thead><tbody>{executive.serviceFlow.map((row) => <tr key={row.service}><td>{row.service}</td><td>{row.consumes}</td><td>{row.publishes}</td><td>{row.agent}</td></tr>)}</tbody></table></div>
      <div className="table-wrap"><table><thead><tr><th>Provider</th><th>Calls</th><th>Tokens</th><th>Cost USD</th></tr></thead><tbody>{executive.finopsRows.map((row, index) => <tr key={`${row.provider}-${index}`}><td>{row.provider}</td><td>{row.calls}</td><td>{row.total_tokens}</td><td>{Number(row.total_cost_usd || 0).toFixed(6)}</td></tr>)}{!executive.finopsRows.length ? <tr><td colSpan={4}>No model calls recorded yet.</td></tr> : null}</tbody></table></div>
    </article>
    <h3>Executive Risk & Operations Report</h3><div className="table-wrap"><table><thead><tr><th>Metric</th><th>Value</th><th>Interpretation</th></tr></thead><tbody><tr><td>SLA At Risk</td><td>{executive.slaAtRisk}</td><td>Open high/critical or manual-mode incidents that may affect business SLO/SLA outcomes.</td></tr><tr><td>Average Approval Wait</td><td>{executive.approvalWaitMinutes.toFixed(1)} min</td><td>Mean time pending in approval queue; useful for governance and response speed tracking.</td></tr><tr><td>Auto Remediation Rate</td><td>{executive.automationRate.toFixed(1)}%</td><td>Share of closed incidents resolved using automatic execution modes.</td></tr></tbody></table></div>
    <div className="table-wrap"><table><thead><tr><th>Incident</th><th>Service</th><th>Risk</th><th>Status</th><th>Execution Mode</th><th>Action</th></tr></thead><tbody>{executive.incidents.slice(0, 20).map((row, index) => <tr key={row.incident_id || index}><td>{row.incident_id || "-"}</td><td>{row.service || "-"}</td><td>{row.risk_tier || "-"}</td><td><span className={`pill status-${String(row.status || "unknown").toLowerCase()}`}>{row.status || "-"}</span></td><td>{row.execution_mode || "-"}</td><td><button type="button" className="button-secondary" onClick={() => executive.openIncident(row)}>Open</button></td></tr>)}{!executive.incidents.length ? <tr><td colSpan={6}>No executive rows available for {executive.application}.</td></tr> : null}</tbody></table></div>
    <h3>Recently Closed Tickets</h3><div className="table-wrap"><table><thead><tr><th>Incident</th><th>Service</th><th>Risk</th><th>Execution Mode</th><th>Status</th><th>Closed At</th></tr></thead><tbody>{executive.recentlyClosed.map((row, index) => <tr key={row.incident_id || index}><td>{row.incident_id || "-"}</td><td>{row.service || "-"}</td><td>{row.risk_tier || row.risk || row.severity || "-"}</td><td>{row.execution_mode || "-"}</td><td><span className={`pill status-${String(row.status || "closed").toLowerCase()}`}>{row.status || "closed"}</span></td><td>{formatTime(row.closed_at || row.updated_at)}</td></tr>)}{!executive.recentlyClosed.length ? <tr><td colSpan={6}>No closed tickets are available yet.</td></tr> : null}</tbody></table></div>
  </article></section>;
}
