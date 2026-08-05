import { MessageBusTopology } from "../../appHelpers.jsx";
import { useRouteRuntime } from "../../app/routeRuntime";

export default function KnowledgeRoute() {
  const { knowledge } = useRouteRuntime();
  return <section className="grid single-col"><article className="panel">
    <div className="panel-head"><h2>Message Bus</h2><button className="button-secondary" onClick={knowledge.refresh}>Refresh Activity</button></div>
    <MessageBusTopology actual={knowledge.actual} configuredRows={knowledge.configuredRows} routing={knowledge.routing} primaryTopic={knowledge.primaryTopic} />
    <h3>Latest Workflow Topic Activity</h3><div className="table-wrap"><table><thead><tr><th>Service</th><th>Consumed</th><th>Published</th><th>Provider</th><th>Status</th></tr></thead><tbody>{knowledge.actual.rows.map((row, index) => <tr key={`${row.service}-${index}`}><td>{row.service}</td><td>{row.consumed}</td><td>{row.published}</td><td>{row.provider}</td><td>{row.status}</td></tr>)}</tbody></table></div>
    <div className="dual-col"><article className="panel"><h3>Actual Topics Published</h3><ul className="flow-list">{knowledge.actual.published.map((topic) => <li key={`pub-${topic}`}>{topic}</li>)}{!knowledge.actual.published.length ? <li>No published topics observed yet.</li> : null}</ul></article><article className="panel"><h3>Actual Topics Consumed</h3><ul className="flow-list">{knowledge.actual.consumed.map((topic) => <li key={`con-${topic}`}>{topic}</li>)}{!knowledge.actual.consumed.length ? <li>No consumed topics observed yet.</li> : null}</ul></article></div>
    <h3>Configured Topic Topology</h3><div className="table-wrap"><table><thead><tr><th>Service</th><th>Consumes</th><th>Publishes</th></tr></thead><tbody>{knowledge.configuredRows.map((row, index) => <tr key={`${row.service}-${index}`}><td>{row.service}</td><td>{row.consumes}</td><td>{row.publishes}</td></tr>)}</tbody></table></div>
    <h3>Routing Rule</h3><p className="subtitle">When dynamic routing is enabled: if stream_count exceeds threshold, provider is kafka; otherwise rabbitmq.</p><p className="subtitle">Observed workflow: {knowledge.routing?.workflow || "N/A"} | next action: {knowledge.routing?.next_action || "N/A"}</p>
  </article></section>;
}
