import {
  canonicalIncidentAnalysis,
  formatQualityPercent,
  formatUtcTimestamp,
  normalizeAlertChannel,
  qualityToneFromScore,
  sourceChannelLabel,
  IntelligenceConnectionView,
  DiscoveryFlowView,
  ContextRetrievalGraph,
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-ignore - appHelpers.jsx is untyped legacy JS, no .d.ts yet.
} from "../../appHelpers.jsx";
import EvidenceDraftReview from "./EvidenceDraftReview";
import "./RcaPanel.css";

type RcaDetailView = "summary" | "evidence" | "technical";

interface RcaPanelProps {
  rcaDetailView: RcaDetailView;
  onSetRcaDetailView: (view: RcaDetailView) => void;
  onSetHomeDetailTab: (tab: string) => void;
  selectedAlertTimelineRows: any[];
  selectedAlertRagDocuments: any[];
  selectedAlertEvaluation: any;
  selectedAlertRow: any;
  selectedRcaDecision: any;
  selectedAiTrust: any;
  selectedAlertWorkflow: any;
  selectedAlertRegeneration: any;
  selectedAlertRecommendationId: string | null | undefined;
  selectedAlertDocumentContract: any;
  selectedAlertId: string | null | undefined;
  aiFeedbackState: any;
  onDownloadRagDocument: (...args: any[]) => any;
  onLoadRagDocumentContent: (...args: any[]) => any;
  onSubmitAiRecommendationFeedback: (decision: string) => any;
}

export default function RcaPanel({
  rcaDetailView,
  onSetRcaDetailView,
  onSetHomeDetailTab,
  selectedAlertTimelineRows,
  selectedAlertRagDocuments,
  selectedAlertEvaluation,
  selectedAlertRow,
  selectedRcaDecision,
  selectedAiTrust,
  selectedAlertWorkflow,
  selectedAlertRegeneration,
  selectedAlertRecommendationId,
  selectedAlertDocumentContract,
  selectedAlertId,
  aiFeedbackState,
  onDownloadRagDocument,
  onLoadRagDocumentContent,
  onSubmitAiRecommendationFeedback,
}: RcaPanelProps) {
  return (
    <section className="combined-analysis-page">
      <header className="combined-analysis-hero">
        <div>
          <span className="discovery-eyebrow">Investigation overview</span>
          <h3>Discovery + Context</h3>
          <p>See what KaiMS found, what it means, and what to do next.</p>
        </div>
        <div className="combined-analysis-kpis">
          <span><strong>{selectedAlertTimelineRows.length}</strong> timeline stages</span>
          <span><strong>{selectedAlertRagDocuments.length}</strong> linked docs</span>
          <span><strong>{formatQualityPercent(selectedAlertEvaluation.overallScore)}</strong> quality</span>
          <span><strong>{Array.isArray(selectedAlertRow?.source_channels) ? selectedAlertRow.source_channels.map(sourceChannelLabel).join(" + ") : sourceChannelLabel(normalizeAlertChannel(selectedAlertRow))}</strong> sources</span>
        </div>
      </header>
      <nav className="rca-view-tabs" aria-label="RCA views">
        {[['summary', 'Summary'], ['evidence', `Evidence (${selectedAiTrust.evidence.length})`], ['technical', 'Technical analysis']].map(([id, label]) => <button key={id} type="button" className={rcaDetailView === id ? "active" : ""} aria-current={rcaDetailView === id ? "page" : undefined} onClick={() => onSetRcaDetailView(id as RcaDetailView)}>{label}</button>)}
      </nav>
      {rcaDetailView === "summary" ? <section className="rca-decision-brief" aria-labelledby="rca-decision-title">
        <header className="rca-decision-header">
          <div>
            <span className="discovery-eyebrow">Operator decision brief</span>
            <h3 id="rca-decision-title">What happened and who is affected</h3>
          </div>
          <div className={`rca-confidence is-${selectedRcaDecision.confidence >= 0.85 ? "high" : selectedRcaDecision.confidence >= 0.7 ? "medium" : "low"}`}>
            <strong>{formatQualityPercent(selectedRcaDecision.confidence)}</strong>
            <span>{selectedRcaDecision.confidenceLabel}</span>
          </div>
        </header>
        {selectedRcaDecision.reviewRequired ? <div className="rca-review-banner" role="status"><strong>Human review required</strong><span>{selectedAiTrust.missing.length ? `${selectedAiTrust.missing.length} evidence gap(s) remain.` : "Confidence or grounding is below the auto-action threshold."}</span></div> : <div className="rca-ready-banner" role="status"><strong>Evidence is sufficiently grounded</strong><span>Confirm the target and safeguards before execution.</span></div>}
        <div className="rca-decision-grid">
          <article className="rca-decision-card rca-cause-card"><span>Probable root cause</span><h4>{selectedRcaDecision.rootCause}</h4><p>{selectedRcaDecision.status === "hypothesis" ? "This is a hypothesis, not a confirmed cause." : selectedRcaDecision.status === "insufficient-evidence" ? "More evidence is required before assigning a cause." : "Supported by the currently linked evidence."}</p></article>
          <article className="rca-decision-card rca-impact-card"><span>Business and customer impact</span><h4>{selectedRcaDecision.customerImpact}</h4><dl><div><dt>Service</dt><dd>{selectedRcaDecision.serviceImpact}</dd></div><div><dt>Dependencies</dt><dd>{selectedRcaDecision.dependencyImpact}</dd></div><div><dt>Urgency</dt><dd>{selectedRcaDecision.urgency}</dd></div>{selectedRcaDecision.impactedServices.length ? <div><dt>Affected services</dt><dd>{selectedRcaDecision.impactedServices.join(", ")}</dd></div> : null}</dl></article>
          <article className="rca-decision-card rca-action-card"><span>Recommended response</span><h4>{selectedRcaDecision.action}</h4><div className="rca-decision-actions">{selectedAiTrust.missing.length ? <button type="button" className="button-primary" onClick={() => onSetRcaDetailView("evidence")}>Collect missing evidence</button> : <button type="button" className="button-primary" onClick={() => onSetHomeDetailTab("execution")}>{selectedRcaDecision.reviewRequired ? "Review plan and decide" : "Continue to remediation"}</button>}<button type="button" className="button-secondary" onClick={() => onSetRcaDetailView("evidence")}>Inspect evidence</button></div></article>
        </div>
        <div className="rca-quality-strip" aria-label="RCA quality indicators"><span><strong>{formatQualityPercent(selectedAlertEvaluation.groundingScore)}</strong> grounding</span><span><strong>{formatQualityPercent(selectedAlertEvaluation.citationCoverage)}</strong> citations</span><span><strong>{selectedAiTrust.evidence.length}</strong> evidence records</span><span><strong>{selectedAiTrust.missing.length}</strong> evidence gaps</span></div>
        <section className="rca-reasoning-chain" aria-label="RCA reasoning chain"><article><span>1 · Observed fact</span><p>{selectedAiTrust.evidence.length ? `${selectedAiTrust.evidence.length} linked record(s) were collected from the incident context.` : "No linked evidence records are available."}</p></article><i aria-hidden="true">→</i><article><span>2 · AI inference</span><p>{selectedRcaDecision.rootCause}</p></article><i aria-hidden="true">→</i><article><span>3 · Operator action</span><p>{selectedRcaDecision.action}</p></article></section>
        <footer className="rca-analysis-meta"><span>Analysis status: <strong>{selectedRcaDecision.status.replaceAll("-", " ")}</strong></span><span>Last evidence: <strong>{selectedAiTrust.evidence[0]?.timestamp ? formatUtcTimestamp(selectedAiTrust.evidence[0].timestamp) : "timestamp not supplied"}</strong></span><span>Version: <strong>current persisted analysis</strong></span></footer>
      </section> : null}
      {rcaDetailView === "technical" ? <div className="combined-analysis-source-rail">
        <strong>Connected evidence</strong>
        <span className="source-badge source-prometheus">Prometheus</span>
        <span className="source-badge">Jaeger traces</span>
        <span className="source-badge">OpenSearch logs</span>
        <span className="source-badge source-email">Email</span>
        <span className="source-badge source-ticket">Jira / tickets</span>
        <span className="source-badge">Source code</span>
      </div> : null}
      {rcaDetailView === "evidence" ? <section className="ai-trust-panel" aria-labelledby="ai-trust-title">
        <header>
          <div><span className="discovery-eyebrow">Evidence transparency</span><h4 id="ai-trust-title">Why KaiMS reached this recommendation</h4></div>
          <span className={`workflow-pill workflow-pill-${qualityToneFromScore(selectedAlertEvaluation.confidenceScore) === "success" ? "active" : "idle"}`}>{formatQualityPercent(selectedAlertEvaluation.confidenceScore)} confidence</span>
        </header>
        <div className="ai-trust-classification ai-trust-classification-compact" aria-label="AI trust classifications">
          <span><strong>Direct observation</strong>{selectedAiTrust.evidence.length} linked record(s)</span>
          <span><strong>AI inference</strong>{selectedAiTrust.analysis.root_cause || canonicalIncidentAnalysis(selectedAlertWorkflow, selectedAlertRow).rootCause}</span>
          <span><strong>Cached context</strong>{selectedAiTrust.evidence.filter((row: any) => row.cached).length} record(s)</span>
          <span><strong>Fresh discovery</strong>{selectedAiTrust.evidence.filter((row: any) => !row.cached).length} record(s)</span>
          <span><strong>Conflicting evidence</strong>{selectedAiTrust.conflicting.length ? selectedAiTrust.conflicting.join(", ") : "None declared by the analysis"}</span>
          <span><strong>Missing evidence</strong>{selectedAiTrust.missing.length ? selectedAiTrust.missing.join(", ") : "None declared by the analysis"}</span>
        </div>
        {selectedAiTrust.evidence.some((row: any) => row.cached && row.freshness === "Stale") ? <p className="ai-trust-warning" role="status">Cached context may predate the current deployment. Validate the target before acting.</p> : null}
        <div className="ai-trust-summary-grid ai-trust-summary-compact">
          <div><strong>Confidence reasons</strong><ul>{selectedAiTrust.confidenceReasons.map((reason: string) => <li key={reason}>{reason}</li>)}</ul></div>
          <div><strong>Model / provider</strong><p>{selectedAiTrust.providerRow ? `${selectedAiTrust.providerRow.model} / ${selectedAiTrust.providerRow.provider}` : "Not supplied by the workflow contract"}</p></div>
          <div><strong>Fallback model</strong><p>{selectedAiTrust.fallbackUsed ? "Used; review required" : "No fallback usage reported"}</p></div>
          <div><strong>Recommendation attempts</strong><p>{selectedAlertRegeneration.message || "One persisted attempt is available; comparison history was not supplied."}</p></div>
        </div>
        <details className="evidence-ledger">
          <summary><div><strong>Evidence ledger</strong><span>{selectedAiTrust.evidence.length} linked records · expand for citations and freshness</span></div><span>View records</span></summary>
          <div className="table-wrap ai-evidence-table contained-table">
            <table>
              <thead><tr><th>Source</th><th>Observed</th><th>Freshness</th><th>Citation</th><th>Context</th></tr></thead>
              <tbody>{selectedAiTrust.evidence.length ? selectedAiTrust.evidence.map((row: any) => (
                <tr key={row.id}><td><span className="source-badge">{row.source}</span></td><td>{row.timestamp ? formatUtcTimestamp(row.timestamp) : "Timestamp unavailable"}<small className="table-secondary">{row.age}</small></td><td>{row.freshness}</td><td className="evidence-citation"><code title={row.citation || "Not supplied"}>{row.citation || "Not supplied"}</code></td><td>{row.cached ? "Cached context" : "Fresh discovery"}</td></tr>
              )) : <tr><td colSpan={5}>No linked evidence records. Treat the recommendation as ungrounded and require human review.</td></tr>}</tbody>
            </table>
          </div>
        </details>
        <div className="ai-feedback-actions" aria-label="Recommendation feedback">
          <span>Was this RCA useful?</span>
          {["helpful", "incorrect", "incomplete"].map((decision) => <button key={decision} type="button" className={aiFeedbackState.decision === decision ? "button-primary" : "button-secondary"} disabled={aiFeedbackState.loading || !selectedAlertRecommendationId} onClick={() => onSubmitAiRecommendationFeedback(decision)}>{decision[0].toUpperCase() + decision.slice(1)}</button>)}
        </div>
        {aiFeedbackState.message ? <p className="success">{aiFeedbackState.message}</p> : null}
        {aiFeedbackState.error ? <p className="error">{aiFeedbackState.error}</p> : null}
      </section> : null}
      {rcaDetailView === "evidence" ? <><IntelligenceConnectionView
        workflow={selectedAlertWorkflow}
        documents={selectedAlertRagDocuments as any}
        onDownloadDocument={onDownloadRagDocument}
      />
      <EvidenceDraftReview alertId={selectedAlertId} />
      </> : null}
      {rcaDetailView === "technical" ? <details className="investigation-deep-dive" open>
        <summary>
          <span>
            <strong>Open technical retrieval trace</strong>
            <small>Inspect every discovery query, context lookup, document score, agent handoff, and raw evidence record</small>
          </span>
          <b>Expand</b>
        </summary>
        <div className="combined-analysis-grid">
          <article className="combined-analysis-card combined-analysis-discovery">
            <DiscoveryFlowView
              workflow={selectedAlertWorkflow}
              timelineRows={selectedAlertTimelineRows as any}
              selectedAlert={selectedAlertRow}
              compact
            />
          </article>
          <article className="combined-analysis-card combined-analysis-context">
            <ContextRetrievalGraph
              workflow={selectedAlertWorkflow}
              timelineRows={selectedAlertTimelineRows}
              documents={selectedAlertRagDocuments}
              evaluation={selectedAlertEvaluation}
              documentContract={selectedAlertDocumentContract}
              onLoadDocumentContent={onLoadRagDocumentContent}
              onDownloadDocument={onDownloadRagDocument}
              compact
            />
          </article>
        </div>
      </details> : null}
    </section>
  );
}
