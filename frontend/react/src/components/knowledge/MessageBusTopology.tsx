import type { BusActivityRow, BusTopologyRow } from "../../app/routeRuntime";

type Props = {
  actual: { rows: BusActivityRow[]; published: string[]; consumed: string[] };
  configuredRows: BusTopologyRow[];
  routing: Record<string, unknown> | null;
  primaryTopic: string;
  compact?: boolean;
};

export function MessageBusTopology({ actual, configuredRows, routing, primaryTopic, compact = false }: Props) {
  const observedTopics = new Set([...(actual.published || []), ...(actual.consumed || [])].map(String).filter(Boolean));
  const provider = String(routing?.message_bus_provider || actual.rows.find((row) => row.provider)?.provider || "Not observed");
  const workflow = String(routing?.workflow || "Not observed");
  const execution = String(routing?.execution_mode || "Not observed");
  return <div className={`message-bus-topology ${compact ? "compact" : ""}`} aria-label="Message bus topology">
    <div className="bus-summary-strip"><div><span>Provider</span><strong>{provider}</strong></div><div><span>Workflow</span><strong>{workflow}</strong></div><div><span>Execution</span><strong>{execution}</strong></div><div><span>Primary topic</span><strong>{primaryTopic || "Not observed"}</strong></div></div>
    <div className="bus-path-stage-grid">
      {configuredRows.map((row, index) => { const published = String(row.publishes || ""); const observed = observedTopics.has(published); return <section className="bus-stage bus-stage-topic" key={`${row.service}-${index}`}><div className="bus-stage-head"><span className="bus-node-icon">{index + 1}</span><div><strong>{row.service || "Unnamed service"}</strong><span>{observed ? "Observed in current workflow" : "Configured route"}</span></div></div><div className="bus-endpoint-box"><span>Consumes</span><code>{row.consumes || "-"}</code></div><div className={`bus-topic-pill ${observed ? "active" : ""}`}>{published || "No published topic"}</div></section>; })}
    </div>
    <div className="bus-observed-rail"><strong>Observed topics</strong><div>{[...observedTopics].map((topic) => <span key={topic}>{topic}</span>)}{!observedTopics.size ? <span>No live topic activity yet</span> : null}</div></div>
  </div>;
}
