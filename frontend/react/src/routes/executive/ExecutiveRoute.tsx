import { Activity, ArrowRight, Gauge, ShieldCheck, Sparkles } from "lucide-react";

import { HorizontalBarChart, SuccessFailureDonut } from "../../components/charts/ExecutiveCharts";
import { useRouteRuntime } from "../../app/routeRuntime";

const formatTime = (value?: string) => value
  ? `${new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST`
  : "-";

export default function ExecutiveRoute() {
  const { executive } = useRouteRuntime();
  const charts = [
    ["Request volume", "Observed API gateway events in the current window", executive.requestChart],
    ["Latency trend", executive.latencySubtitle, executive.latencyChart],
    ["AI operations cost", "Aggregated model usage and spend", executive.finopsChart],
    ["Closures by risk", "Recent closure distribution", executive.riskChart],
    ["Closures by execution mode", "How incidents were handled", executive.modeChart],
    ["Open incident trend", "Open incidents observed per day in the seven-day window", executive.weeklyOpenChart],
    ["Closed incident trend", "Verified closures per day in the seven-day window", executive.weeklyClosedChart],
  ] as const;

  return (
    <section className="grid single-col operational-route executive-workspace">
      <article className="executive-brief">
        <div><span className="discovery-eyebrow">Leadership reliability brief</span><h2>Reliability, risk, and automation outcomes</h2><p>Connect live operational health to response speed, governed automation, and business exposure.</p></div>
        <div className="executive-brief-badges"><span><ShieldCheck aria-hidden="true" /> Governed data</span><span><Activity aria-hidden="true" /> Live scope</span></div>
      </article>

      <section className="executive-kpi-grid" aria-label="Executive key performance indicators">
        {executive.statCards.map((card, index) => <article key={card.label}><span>{card.label}</span><strong>{card.value}</strong><small>{index === 0 ? "Current selected scope" : "Measured platform outcome"}</small></article>)}
      </section>

      <article className="panel executive-observability-panel">
        <div className="panel-head"><div><span className="discovery-eyebrow">Reliability signals</span><h3>Performance and operating trend</h3><p>Each chart is backed by the currently loaded gateway, incident, closure, and cost records.</p></div></div>
        <div className="executive-chart-grid"><HorizontalBarChart title={charts[0][0]} subtitle={charts[0][1]} items={charts[0][2]} /><SuccessFailureDonut success={executive.successRequests} failure={executive.failedRequests} />{charts.slice(1).map(([title, subtitle, items]) => <HorizontalBarChart key={title} title={title} subtitle={subtitle} items={items} />)}</div>
      </article>

      <article className="panel executive-flow-panel">
        <div className="panel-head"><div><span className="discovery-eyebrow">Automation accountability</span><h3>End-to-end processing and FinOps</h3><p>Follow ingestion, parallel analysis, remediation, validation, and cost across the service chain.</p></div><Sparkles aria-hidden="true" /></div>
        <div className="workflow-guide-grid executive-flow-grid">{executive.workflowStages.map((stage) => <div className="workflow-guide-card executive-flow-card" key={stage.id}><strong>{stage.label}</strong><span className={`workflow-pill workflow-pill-${stage.status}`}>{stage.status.toUpperCase()}</span><p>{stage.detail}</p></div>)}</div>
        <div className="executive-table-pair">
          <section><h4>Service handoffs</h4><div className="table-wrap table-wrap-scroll-x"><table><caption className="sr-only">Backend service handoff contracts</caption><thead><tr><th>Backend service</th><th>Consumes</th><th>Publishes</th><th>Processing agent</th></tr></thead><tbody>{executive.serviceFlow.map((row) => <tr key={row.service}><td><strong>{row.service}</strong></td><td>{row.consumes}</td><td>{row.publishes}</td><td>{row.agent}</td></tr>)}</tbody></table></div></section>
          <section><h4>Model consumption</h4><div className="table-wrap"><table><caption className="sr-only">AI provider token and cost usage</caption><thead><tr><th>Provider</th><th>Calls</th><th>Tokens</th><th>Cost USD</th></tr></thead><tbody>{executive.finopsRows.map((row, index) => <tr key={`${row.provider}-${index}`}><td><strong>{row.provider}</strong></td><td>{row.calls}</td><td>{row.total_tokens}</td><td>{Number(row.total_cost_usd || 0).toFixed(6)}</td></tr>)}{!executive.finopsRows.length ? <tr><td colSpan={4}>No model calls recorded in this scope.</td></tr> : null}</tbody></table></div></section>
        </div>
      </article>

      <section className="executive-outcome-grid">
        <article className="panel executive-outcome-card"><Gauge aria-hidden="true" /><span>SLA at risk</span><strong>{executive.slaAtRisk}</strong><p>Open high/critical or manual-mode incidents that may affect business objectives.</p></article>
        <article className="panel executive-outcome-card"><Activity aria-hidden="true" /><span>Average approval wait</span><strong>{executive.approvalWaitMinutes.toFixed(1)} min</strong><p>Mean governance queue time affecting response speed.</p></article>
        <article className="panel executive-outcome-card"><ShieldCheck aria-hidden="true" /><span>Auto-remediation rate</span><strong>{executive.automationRate.toFixed(1)}%</strong><p>Share of verified closures completed with automatic execution modes.</p></article>
      </section>

      <article className="panel route-data-panel">
        <div className="panel-head"><div><span className="discovery-eyebrow">Operational exposure</span><h3>Incidents requiring leadership visibility</h3><p>The first 20 records in the current application scope.</p></div></div>
        <div className="table-wrap"><table><caption className="sr-only">Executive incident risk report</caption><thead><tr><th>Incident</th><th>Service</th><th>Risk</th><th>Status</th><th>Execution mode</th><th>Action</th></tr></thead><tbody>{executive.incidents.slice(0, 20).map((row, index) => <tr key={row.incident_id || index}><td><code>{row.incident_id || "-"}</code></td><td><strong>{row.service || "-"}</strong></td><td>{row.risk_tier || "-"}</td><td><span className={`pill status-${String(row.status || "unknown").toLowerCase()}`}>{row.status || "-"}</span></td><td>{row.execution_mode || "-"}</td><td><button type="button" className="button-secondary" onClick={() => executive.openIncident(row)}>Open incident <ArrowRight size={14} aria-hidden="true" /></button></td></tr>)}{!executive.incidents.length ? <tr><td colSpan={6}><div className="table-empty-state"><ShieldCheck aria-hidden="true" /><strong>No executive-risk incidents</strong><span>No incident rows are available for {executive.application}.</span></div></td></tr> : null}</tbody></table></div>
      </article>

      <article className="panel route-data-panel">
        <div className="panel-head"><div><span className="discovery-eyebrow">Verified recovery</span><h3>Recently closed incidents</h3><p>Closure time, risk, and execution evidence for recently recovered services.</p></div></div>
        <div className="table-wrap"><table><caption className="sr-only">Recently closed incidents</caption><thead><tr><th>Incident</th><th>Service</th><th>Risk</th><th>Execution mode</th><th>Status</th><th>Closed at</th></tr></thead><tbody>{executive.recentlyClosed.map((row, index) => <tr key={row.incident_id || index}><td><code>{row.incident_id || "-"}</code></td><td><strong>{row.service || "-"}</strong></td><td>{row.risk_tier || row.risk || row.severity || "-"}</td><td>{row.execution_mode || "-"}</td><td><span className={`pill status-${String(row.status || "closed").toLowerCase()}`}>{row.status || "closed"}</span></td><td>{formatTime(row.closed_at || row.updated_at)}</td></tr>)}{!executive.recentlyClosed.length ? <tr><td colSpan={6}><div className="table-empty-state"><Activity aria-hidden="true" /><strong>No recent closures</strong><span>Verified closure records will appear here.</span></div></td></tr> : null}</tbody></table></div>
      </article>
    </section>
  );
}
