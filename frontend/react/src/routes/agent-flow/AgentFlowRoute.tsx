import { Activity, Bot, Network, ShieldCheck } from "lucide-react";

import { useRouteRuntime } from "../../app/routeRuntime";

const formatTime = (value?: string) => value
  ? `${new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST`
  : "-";

export default function AgentFlowRoute() {
  const { agentFlow } = useRouteRuntime();
  const workflowCount = agentFlow.workflowRows.length;
  const gatewayCount = agentFlow.gatewayRows.length;
  const blockedCount = agentFlow.gatewayRows.filter((row) =>
    ["block", "blocked", "deny", "denied"].includes(String(row.safety?.decision || "").toLowerCase()),
  ).length;

  return (
    <section className="grid single-col operational-route agent-flow-workspace">
      <section className="route-insight-strip" aria-label="Automation activity summary">
        <article><Bot aria-hidden="true" /><span><small>Agent steps</small><strong>{workflowCount}</strong></span></article>
        <article><Network aria-hidden="true" /><span><small>Gateway events</small><strong>{gatewayCount}</strong></span></article>
        <article><ShieldCheck aria-hidden="true" /><span><small>Policy blocks</small><strong>{blockedCount}</strong></span></article>
      </section>

      <article className="panel route-data-panel">
        <div className="panel-head">
          <div><span className="discovery-eyebrow">Decision trace</span><h2>Agent workflow timeline</h2><p>Follow each automated decision from input through output and service handoff.</p></div>
          <span className="workflow-pill workflow-pill-active"><Activity size={14} aria-hidden="true" /> {workflowCount ? "Trace available" : "Awaiting run"}</span>
        </div>
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Agent workflow steps in execution order</caption>
            <thead><tr><th>Step</th><th>Agent</th><th>Action</th><th>Decision</th><th>Output</th><th>Handoff</th></tr></thead>
            <tbody>
              {agentFlow.workflowRows.map((row, index) => <tr key={`${row.sequence}-${index}`}><td><strong>{row.sequence}</strong></td><td>{row.agent}</td><td>{row.action}</td><td>{row.decision}</td><td>{row.output}</td><td>{row.communicates_to}</td></tr>)}
              {!workflowCount ? <tr><td colSpan={6}><div className="table-empty-state"><Bot aria-hidden="true" /><strong>No workflow trace yet</strong><span>Run an incident workflow to populate the agent decision timeline.</span></div></td></tr> : null}
            </tbody>
          </table>
        </div>
      </article>

      <article className="panel route-data-panel">
        <div className="panel-head"><div><span className="discovery-eyebrow">Execution boundary</span><h3>Gateway audit events</h3><p>Correlate policy decisions, HTTP outcomes, latency, and trace identifiers.</p></div></div>
        {agentFlow.gatewayError ? <p className="error" role="alert">{agentFlow.gatewayError}</p> : null}
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Recent API gateway audit events</caption>
            <thead><tr><th>Time</th><th>Path</th><th>HTTP status</th><th>Safety decision</th><th>Trace ID</th></tr></thead>
            <tbody>
              {agentFlow.gatewayRows.slice(0, 30).map((row, index) => <tr key={row.id || index}><td>{formatTime(row.created_at)}</td><td><code>{row.path || "-"}</code></td><td>{row.status_code || "-"}</td><td><span className={`pill status-${String(row.safety?.decision || "unknown").toLowerCase()}`}>{row.safety?.decision || "-"}</span></td><td><code>{row.trace_id || "-"}</code></td></tr>)}
              {!gatewayCount && !agentFlow.gatewayLoading ? <tr><td colSpan={5}><div className="table-empty-state"><ShieldCheck aria-hidden="true" /><strong>No gateway events in scope</strong><span>Events appear after an API request crosses the governed gateway.</span></div></td></tr> : null}
            </tbody>
          </table>
        </div>
        {agentFlow.workflowResult ? <details className="route-technical-result"><summary>Latest raw workflow result</summary><pre className="result">{JSON.stringify(agentFlow.workflowResult, null, 2)}</pre></details> : null}
      </article>
    </section>
  );
}
