type AnyRecord = Record<string, any>;
const record = (value: unknown): AnyRecord => value && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};
const list = (value: unknown): AnyRecord[] => Array.isArray(value) ? value.map(record) : [];
const text = (value: unknown, fallback = "Not recorded") => String(value ?? "").trim() || fallback;

export function DiscoveryFlowView({ workflow, timelineRows = [], selectedAlert = null, compact = false }: { workflow: unknown; timelineRows?: unknown[]; selectedAlert?: unknown; compact?: boolean }) {
  const root = record(workflow);
  const alert = record(selectedAlert || root.alert);
  const context = record(root.context);
  const metadata = record(context.metadata);
  const discovery = record(metadata.discovery_report);
  const evidence = list(discovery.evidence || metadata.context_evidence);
  const events = list(timelineRows);
  const stages = [
    { label: "Observed signal", value: text(alert.name || alert.alert_name || record(alert.labels).alertname), detail: text(alert.source || alert.provider, "Source unavailable") },
    { label: "Workflow trace", value: `${events.length} recorded event(s)`, detail: text(events.at(-1)?.event_type || events.at(-1)?.action, "No lifecycle event") },
    { label: "Context collection", value: `${evidence.length} evidence record(s)`, detail: text(context.snapshot_id || context.id, "Snapshot unavailable") },
  ];
  return <div className={`processing-flow-map ${compact ? "compact" : ""}`} aria-label="Discovery and context collection trace"><div className="processing-flow-status-strip"><span>Recorded workflow</span><strong>{events.length ? "Observed" : "Waiting"}</strong></div><div className="processing-flow-spine">{stages.map((stage, index) => <div className="processing-flow-step" key={stage.label}><article className="processing-flow-node status-observed"><div className="processing-node-head"><strong>{stage.label}</strong><em>{index + 1}</em></div><span>{stage.value}</span><small>{stage.detail}</small></article>{index < stages.length - 1 ? <span className="processing-flow-arrow" aria-hidden="true">→</span> : null}</div>)}</div></div>;
}

export function ContextRetrievalGraph({ workflow, timelineRows = [], documents = [], evaluation, documentContract, onLoadDocumentContent, onDownloadDocument, compact = false }: { workflow: unknown; timelineRows?: unknown[]; documents?: unknown[]; evaluation?: unknown; documentContract?: unknown; onLoadDocumentContent?: (document: unknown) => void; onDownloadDocument?: (document: unknown) => void; compact?: boolean }) {
  const root = record(workflow);
  const context = record(root.context);
  const metadata = record(context.metadata);
  const matches = list(metadata.rag_matches);
  const evidence = list(record(metadata.discovery_report).evidence || metadata.context_evidence);
  const docs = list(documents);
  const score = Number(record(evaluation).grounding_score ?? record(documentContract).quality_score);
  return <div className={`processing-flow-map ${compact ? "compact" : ""}`} aria-label="Context retrieval and provenance graph"><div className="processing-flow-status-strip"><span>Grounded retrieval</span><strong>{Number.isFinite(score) ? `${Math.round(score * 100)}%` : "Not scored"}</strong></div><div className="processing-flow-detail-grid"><article className="processing-flow-detail-card"><h4>Accepted context</h4><div className="processing-flow-match-list"><div className="processing-flow-match"><strong>{evidence.length}</strong><span>evidence records</span><small>Snapshot {text(context.snapshot_id || context.id, "not recorded")}</small></div><div className="processing-flow-match"><strong>{matches.length}</strong><span>retrieval matches</span><small>{timelineRows.length} lifecycle events</small></div></div></article><article className="processing-flow-detail-card"><h4>Source documents</h4><div className="processing-flow-match-list">{docs.slice(0, 6).map((document, index) => <div className="processing-flow-match" key={text(document.id || document.path, String(index))}><strong>{text(document.title || document.name || document.path, `Document ${index + 1}`)}</strong><span>{text(document.kind || document.document_kind, "evidence")}</span><small>{text(document.source_uri || document.path, "Source URI unavailable")}</small>{onLoadDocumentContent ? <button type="button" className="button-secondary" onClick={() => onLoadDocumentContent(document)}>Inspect</button> : null}{onDownloadDocument ? <button type="button" className="button-secondary" onClick={() => onDownloadDocument(document)}>Download</button> : null}</div>)}{!docs.length ? <div className="processing-flow-match"><strong>No documents</strong><span>No retrieval document was bound.</span></div> : null}</div></article></div></div>;
}
