import { useMemo, useState } from "react";
import { Activity, BrainCircuit, GitBranch, ShieldCheck, Wrench } from "lucide-react";

import type { IncidentRow } from "../../app/routeRuntime";
import { formatIstTimestamp } from "../../appHelpers.jsx";
import "./IncidentDecisionWorkspace.css";

type EvidenceKind = "observed_fact" | "verified_topology" | "strong_correlation" | "ai_inferred" | "hypothesis" | "contradiction";
type EvidenceNode = { id: string; label: string; kind: EvidenceKind; source?: string; detail?: string };
type EvidenceEdge = { source: string; target: string; kind: EvidenceKind; label?: string };

const kinds: Record<EvidenceKind, string> = {
  observed_fact: "Observed fact",
  verified_topology: "Verified topology",
  strong_correlation: "Strong correlation",
  ai_inferred: "AI-inferred relationship",
  hypothesis: "Unverified hypothesis",
  contradiction: "Contradicting evidence",
};

const record = (value: unknown): Record<string, any> => value && typeof value === "object" ? value as Record<string, any> : {};
const text = (...values: unknown[]) => String(values.find((value) => value !== undefined && value !== null && String(value).trim()) ?? "Unavailable");
const normalizeKind = (value: unknown): EvidenceKind => {
  const kind = String(value || "").toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
  if (kind.includes("contradict")) return "contradiction";
  if (kind.includes("hypothesis") || kind.includes("unverified")) return "hypothesis";
  if (kind.includes("infer")) return "ai_inferred";
  if (kind.includes("correlat")) return "strong_correlation";
  if (kind.includes("topolog") || kind.includes("verified")) return "verified_topology";
  return "observed_fact";
};

export function evidenceGraphFromIncident(row: IncidentRow): { nodes: EvidenceNode[]; edges: EvidenceEdge[] } {
  const projection = record(row.projection_payload);
  const event = record(projection.event_payload);
  const graph = [projection.evidence_graph, projection.causal_graph, event.evidence_graph, event.causal_graph].map(record).find((candidate) => Array.isArray(candidate.nodes)) || {};
  const nodes = (Array.isArray(graph.nodes) ? graph.nodes : []).map((candidate: unknown, index: number) => {
    const node = record(candidate);
    return { id: text(node.id, node.evidence_id, `evidence-${index + 1}`), label: text(node.label, node.title, node.name, node.observation), kind: normalizeKind(node.kind || node.relationship_source || node.type), source: text(node.source, node.source_uri), detail: text(node.detail, node.description, node.evidence) };
  });
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = (Array.isArray(graph.edges) ? graph.edges : []).map((candidate: unknown) => {
    const edge = record(candidate);
    return { source: text(edge.source, edge.from, edge.source_id), target: text(edge.target, edge.to, edge.target_id), kind: normalizeKind(edge.kind || edge.relationship_source || edge.type), label: text(edge.label, edge.relationship) };
  }).filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  return { nodes, edges };
}

function duration(row: IncidentRow) {
  const payload = row as unknown as Record<string, unknown>;
  const start = Date.parse(String(row.created_at || ""));
  const end = Date.parse(String(payload.closed_at || row.updated_at || ""));
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "Unavailable";
  const minutes = Math.round((end - start) / 60000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`;
}

export default function IncidentDecisionWorkspace({ row }: { row: IncidentRow }) {
  const [selectedNode, setSelectedNode] = useState<EvidenceNode | null>(null);
  const projection = record(row.projection_payload);
  const incident = row as unknown as Record<string, unknown>;
  const event = record(projection.event_payload);
  const recommendation = record(event.recommendation || projection.recommendation);
  const analysis = record(event.analysis || projection.analysis || recommendation.analysis);
  const impact = record(event.impact || projection.impact || analysis.impact);
  const remediation = record(event.remediation_plan || projection.remediation_plan || recommendation.plan);
  const validation = record(event.validation || projection.validation || projection.closure_report);
  const learning = record(event.learning || projection.learning || projection.learning_record);
  const graph = useMemo(() => evidenceGraphFromIncident(row), [row]);
  const alternatives = Array.isArray(analysis.alternative_hypotheses) ? analysis.alternative_hypotheses : Array.isArray(analysis.hypotheses) ? analysis.hypotheses.slice(1) : [];
  const status = text(row.status, projection.status);
  const owner = text(incident.assigned_to, row.jira_assignee, event.owner, projection.owner);
  const autonomy = text(row.execution_mode, event.execution_mode, projection.execution_mode, "Human approval");

  return <section className="incident-decision-workspace" aria-label="Unified incident decision workspace">
    <header className="incident-command-header">
      <div><span>Incident workspace</span><h2>{text(row.title, row.summary, `${row.service || "Service"} incident`)}</h2><code>{text(row.incident_id, row.id)}</code></div>
      <dl><div><dt>Severity</dt><dd>{text(row.severity, row.risk_tier)}</dd></div><div><dt>State</dt><dd>{status.replaceAll("_", " ")}</dd></div><div><dt>Application</dt><dd>{text(row.service, event.application)}</dd></div><div><dt>Environment</dt><dd>{text(row.environment, event.environment)}</dd></div><div><dt>Duration</dt><dd>{duration(row)}</dd></div><div><dt>Owner</dt><dd>{owner}</dd></div><div><dt>Autonomy</dt><dd>{autonomy}</dd></div></dl>
    </header>

    <nav className="incident-visible-lifecycle" aria-label="Incident lifecycle">{["Observe", "Understand", "Reason", "Govern", "Act", "Verify", "Learn"].map((stage, index) => <span key={stage} className={index <= (["open", "investigating", "awaiting_approval", "approved", "remediating", "validating", "resolved", "closed"].indexOf(status.toLowerCase())) ? "is-reached" : ""}><b>{index + 1}</b>{stage}</span>)}</nav>

    <div className="incident-question-grid">
      <article><Activity /><span>What happened?</span><p>{text(row.summary, row.title, event.description, event.message)}</p></article>
      <article><GitBranch /><span>What changed?</span><p>{text(analysis.correlated_change, event.change_summary, projection.change_summary)}</p></article>
      <article><BrainCircuit /><span>Kai diagnosis</span><p>{text(analysis.root_cause, recommendation.root_cause, projection.root_cause)}</p><small>Confidence: {text(analysis.confidence, recommendation.confidence)}</small></article>
      <article><ShieldCheck /><span>Impact and decision</span><p>{text(impact.summary, impact.blast_radius, incident.impact_summary)}</p><small>{row.requires_approval === false ? "Policy permits autonomous execution" : "Human decision required"}</small></article>
      <article><Wrench /><span>What happens next?</span><p>{text(remediation.summary, remediation.intent, recommendation.action, recommendation.summary)}</p><small>Target: {text(remediation.target, event.target, row.service)}</small></article>
      <article><ShieldCheck /><span>Did it work?</span><p>{text(validation.summary, validation.status, validation.outcome)}</p><small>Learning: {text(learning.summary, learning.status)}</small></article>
    </div>

    <section className="causal-evidence-workspace" aria-labelledby="causal-graph-title">
      <header><div><span>Kai Evidence</span><h3 id="causal-graph-title">Causal evidence graph</h3><p>Observed and verified evidence is visually separated from inference and hypotheses.</p></div><strong>{graph.nodes.length} nodes · {graph.edges.length} relationships</strong></header>
      {graph.nodes.length ? <><div className="causal-legend">{Object.entries(kinds).map(([kind, label]) => <span key={kind} className={`is-${kind}`}><i />{label}</span>)}</div><div className="causal-graph" role="list">{graph.nodes.map((node, index) => <div className="causal-step" key={node.id}>{index ? <span className={`causal-edge is-${graph.edges.find((edge) => edge.target === node.id)?.kind || "ai_inferred"}`}>{graph.edges.find((edge) => edge.target === node.id)?.label || "related to"} →</span> : null}<button type="button" role="listitem" className={`is-${node.kind}`} onClick={() => setSelectedNode(node)}><small>{kinds[node.kind]}</small><strong>{node.label}</strong><span>{node.source}</span></button></div>)}</div></> : <div className="causal-empty"><strong>No persisted causal graph is available</strong><p>KaiMS will not construct a confirmed causal path from display labels alone. Review the evidence ledger while graph collection completes.</p></div>}
      {selectedNode ? <aside className="causal-source-detail"><button type="button" onClick={() => setSelectedNode(null)} aria-label="Close evidence details">×</button><span>{kinds[selectedNode.kind]}</span><h4>{selectedNode.label}</h4><p>{selectedNode.detail}</p><code>{selectedNode.source}</code></aside> : null}
    </section>

    <details className="incident-alternatives"><summary>Alternative hypotheses ({alternatives.length})</summary>{alternatives.length ? <ul>{alternatives.map((candidate: unknown, index: number) => { const hypothesis = record(candidate); return <li key={text(hypothesis.id, index)}><strong>Unverified hypothesis</strong><span>{text(hypothesis.summary, hypothesis.cause, candidate)}</span></li>; })}</ul> : <p>No alternative hypotheses were persisted.</p>}</details>
    <footer>Last incident update: {formatIstTimestamp(row.updated_at || row.created_at)}</footer>
  </section>;
}
