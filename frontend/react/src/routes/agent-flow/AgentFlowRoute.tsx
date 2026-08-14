import { useRouteRuntime } from "../../app/routeRuntime";
const formatTime = (value?: string) => value ? `${new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST` : "-";

export default function AgentFlowRoute() {
  const { agentFlow } = useRouteRuntime();
  return <section className="grid single-col"><article className="panel">
    <div className="panel-head"><h2>Agent Flow</h2><p>Agent flow with decisions, outputs, and communication handoffs.</p></div>
    <h3>Workflow Event Timeline</h3><div className="table-wrap"><table><thead><tr><th>Step</th><th>Agent</th><th>Action</th><th>Decision</th><th>Output</th><th>Handoff</th></tr></thead><tbody>{agentFlow.workflowRows.map((row, index) => <tr key={`${row.sequence}-${index}`}><td>{row.sequence}</td><td>{row.agent}</td><td>{row.action}</td><td>{row.decision}</td><td>{row.output}</td><td>{row.communicates_to}</td></tr>)}{!agentFlow.workflowRows.length ? <tr><td colSpan={6}>Run a workflow to populate detailed agent timeline.</td></tr> : null}</tbody></table></div>
    <h3>Gateway Audit Events</h3>{agentFlow.gatewayError ? <p className="error">{agentFlow.gatewayError}</p> : null}<div className="table-wrap"><table><thead><tr><th>Time</th><th>Path</th><th>Status</th><th>Decision</th><th>Trace ID</th></tr></thead><tbody>{agentFlow.gatewayRows.slice(0, 30).map((row, index) => <tr key={row.id || index}><td>{formatTime(row.created_at)}</td><td>{row.path || "-"}</td><td>{row.status_code || "-"}</td><td>{row.safety?.decision || "-"}</td><td>{row.trace_id || "-"}</td></tr>)}{!agentFlow.gatewayRows.length && !agentFlow.gatewayLoading ? <tr><td colSpan={5}>No recent gateway trace entries.</td></tr> : null}</tbody></table></div>
    {agentFlow.workflowResult ? <pre className="result">{JSON.stringify(agentFlow.workflowResult, null, 2)}</pre> : null}
  </article></section>;
}
