import { useEffect, useMemo, useState } from "react";
import { Activity, BookOpen, CheckCircle2, Clock3, Code2, Database, FileSearch, GitCommit, Network, RotateCw, Search, ShieldAlert, Sparkles } from "lucide-react";
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
  fetchJson,
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-ignore - appHelpers.jsx is untyped legacy JS, no .d.ts yet.
} from "../../appHelpers.jsx";
import EvidenceDraftReview from "./EvidenceDraftReview";
import "./RcaPanel.css";
import "./RcaReuseBanner.css";
import "./EvidenceReview.css";

type RcaDetailView = "simple" | "detailed" | "evidence" | "technical";

const EVIDENCE_SOURCE_DEFINITIONS = [
  { id: "metrics", label: "Metrics", icon: Activity, match: /prometheus|metric/i },
  { id: "logs", label: "Logs", icon: FileSearch, match: /log|opensearch|elastic/i },
  { id: "traces", label: "Traces", icon: Network, match: /trace|jaeger|span/i },
  { id: "changes", label: "Changes", icon: GitCommit, match: /deploy|change|commit|git/i },
  { id: "code", label: "Source code", icon: Code2, match: /code|source/i },
  { id: "knowledge", label: "Knowledge", icon: BookOpen, match: /rag|runbook|ticket|jira|document/i },
] as const;

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
  rcaAnalysisMode: "smart" | "fresh" | "cache";
  onSetRcaAnalysisMode: (mode: "smart" | "fresh" | "cache") => void;
  onRerunRca: () => any;
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
  rcaAnalysisMode,
  onSetRcaAnalysisMode,
  onRerunRca,
  onDownloadRagDocument,
  onLoadRagDocumentContent,
  onSubmitAiRecommendationFeedback,
}: RcaPanelProps) {
  const [resolutionOptions, setResolutionOptions] = useState<any[]>([]);
  const [selectedResolution, setSelectedResolution] = useState<any>(null);
  const [resolutionStatus, setResolutionStatus] = useState("");
  const recommendationMetadata = selectedAlertWorkflow?.recommendation?.metadata || {};
  const analysisReused = Boolean(recommendationMetadata.analysis_reused);
  const analysisReuseScore = Number(recommendationMetadata.analysis_reuse_score || 0);
  const discoveryAnalysis = recommendationMetadata?.discovery_report?.report
    || selectedAlertWorkflow?.context?.metadata?.discovery_report?.report
    || {};
  const proposedCodeChanges = Array.isArray(recommendationMetadata?.proposed_code_changes)
    ? recommendationMetadata.proposed_code_changes
    : Array.isArray(discoveryAnalysis?.proposed_code_changes)
      ? discoveryAnalysis.proposed_code_changes
      : [];
  const resolutionService = selectedAlertRow?.service || selectedAlertRow?.application || "unknown";
  const hasEvidence = Boolean(selectedAiTrust.hasEvidence && selectedAiTrust.evidence?.length);
  const qualityDisplay = hasEvidence ? formatQualityPercent(selectedAlertEvaluation.overallScore) : "Unavailable";
  const confidenceDisplay = hasEvidence && selectedRcaDecision.confidenceAvailable ? formatQualityPercent(selectedRcaDecision.confidence) : "Unavailable";
  const evidenceSources = useMemo(() => EVIDENCE_SOURCE_DEFINITIONS.map((source) => {
    let count = 0; let fresh = 0;
    for (const row of selectedAiTrust.evidence || []) {
      if (!source.match.test(`${row.source || ""} ${row.citation || ""}`)) continue;
      count += 1;
      if (!row.cached) fresh += 1;
    }
    return { ...source, count, fresh };
  }), [selectedAiTrust.evidence]);
  useEffect(() => {
    let active = true;
    setSelectedResolution(null);
    setResolutionStatus("");
    if (!hasEvidence) {
      setResolutionOptions([]);
      setResolutionStatus("Resolution planning is blocked until diagnostic evidence is linked.");
      return () => { active = false; };
    }
    fetchJson("/resolution-agent/resolution-catalog/relevant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ issue: selectedRcaDecision.rootCause, service: resolutionService, recommended_action: selectedRcaDecision.action }),
      timeoutMs: 10000,
    }).then((result: any) => { if (active) setResolutionOptions(Array.isArray(result?.rows) ? result.rows : []); })
      .catch(() => { if (active) setResolutionStatus("Resolution options are temporarily unavailable."); });
    return () => { active = false; };
  }, [selectedAlertId, selectedRcaDecision.rootCause, selectedRcaDecision.action, resolutionService, hasEvidence]);

  async function chooseResolution(option: any) {
    setResolutionStatus("Preparing the selected resolution...");
    try {
      const result: any = await fetchJson("/resolution-agent/resolution-catalog/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ option_id: option.id, issue: selectedRcaDecision.rootCause, service: resolutionService, incident_id: selectedAlertId || "" }),
        timeoutMs: 10000,
      });
      setSelectedResolution(result?.selected || option);
      setResolutionStatus("Resolution plan prepared by the remediation agent for operator review.");
    } catch (error: any) {
      setResolutionStatus(error?.message || "The resolution plan could not be prepared.");
    }
  }
  return (
    <section className="combined-analysis-page">
      <header className="combined-analysis-hero understand-workspace-hero">
        <div>
          <span className="discovery-eyebrow">Incident intelligence</span>
          <h3>Evidence & Understanding</h3>
          <p>Evidence, causal analysis, impact, and the safest next action in one operational view.</p>
        </div>
        <div className="rca-hero-controls">
          <div className="combined-analysis-kpis">
            <span><strong>{selectedAlertTimelineRows.length}</strong> timeline stages</span>
            <span><strong>{selectedAlertRagDocuments.length}</strong> linked docs</span>
            <span><strong>{qualityDisplay}</strong> quality</span>
            <span><strong>{Array.isArray(selectedAlertRow?.source_channels) ? selectedAlertRow.source_channels.map(sourceChannelLabel).join(" + ") : sourceChannelLabel(normalizeAlertChannel(selectedAlertRow))}</strong> alert source</span>
          </div>
          <div className="rca-rerun-control">
            <label htmlFor="rca-analysis-mode">Analysis mode</label>
            <select id="rca-analysis-mode" value={rcaAnalysisMode} onChange={(event) => onSetRcaAnalysisMode(event.target.value as "smart" | "fresh" | "cache")} disabled={selectedAlertRegeneration.loading}>
              <option value="smart">Smart reuse</option><option value="fresh">Fresh context</option><option value="cache">Verified cache only</option>
            </select>
            <button type="button" className="button-primary" onClick={onRerunRca} disabled={selectedAlertRegeneration.loading}>
              <RotateCw size={15} aria-hidden="true" className={selectedAlertRegeneration.loading ? "is-spinning" : ""}/>{selectedAlertRegeneration.loading ? "Running RCA…" : "Rerun RCA"}
            </button>
          </div>
        </div>
      </header>
      {analysisReused ? <aside className="rca-reuse-banner" role="status">
        <CheckCircle2 size={18} />
        <div><strong>Using verified prior analysis</strong><span>This context and RCA scored {formatQualityPercent(analysisReuseScore)} and were reused for this matching incident. Use <b>Run Full Analysis With Fresh Context</b> above whenever current evidence may have changed.</span></div>
      </aside> : null}
      <section className="understand-source-matrix" aria-label="External knowledge and evidence coverage">
        <header><div><Search size={17} /><span><strong>Evidence coverage</strong><small>Live operational data and external knowledge used for this analysis</small></span></div><div className="evidence-coverage-actions"><b>{evidenceSources.filter((source) => source.count).length}/{evidenceSources.length} source categories represented</b>{!hasEvidence || selectedAiTrust.missing.length ? <button type="button" className="button-primary" onClick={() => onSetRcaDetailView("evidence")}>Collect evidence</button> : null}<button type="button" className="button-secondary" onClick={() => onSetRcaDetailView("evidence")}>Inspect evidence</button></div></header>
        <div>{evidenceSources.map(({ id, label, icon: Icon, count, fresh }) => <button type="button" key={id} className={count ? "has-evidence" : "is-missing"} onClick={() => onSetRcaDetailView(count ? "evidence" : "technical")}><i><Icon size={17} /></i><span><strong>{label}</strong><small>{count ? `${count} record${count === 1 ? "" : "s"} · ${fresh} fresh` : "No evidence returned"}</small></span>{count ? <CheckCircle2 size={15} /> : <ShieldAlert size={15} />}</button>)}</div>
      </section>
      <nav className="rca-view-tabs" aria-label="RCA views">
        {[['simple', 'Simple'], ['detailed', 'Detailed'], ['evidence', `Evidence (${selectedAiTrust.evidence.length})`], ['technical', 'Technical trace']].map(([id, label]) => <button key={id} type="button" className={rcaDetailView === id ? "active" : ""} aria-current={rcaDetailView === id ? "page" : undefined} onClick={() => onSetRcaDetailView(id as RcaDetailView)}>{label}</button>)}
      </nav>
      {rcaDetailView === "simple" ? <section className="understand-simple" aria-labelledby="understand-simple-title">
        <header>
          <div><span className="discovery-eyebrow">Plain-language explanation</span><h3 id="understand-simple-title">What you need to know</h3><p>A concise, evidence-aware explanation for making the next operational decision.</p></div>
          <div className={`rca-confidence is-${selectedRcaDecision.confidence >= 0.85 ? "high" : selectedRcaDecision.confidence >= 0.7 ? "medium" : "low"}`}><strong>{confidenceDisplay}</strong><span>{hasEvidence ? "confidence" : "ungrounded"}</span></div>
        </header>
        <div className="understand-simple-grid">
          <article><span>1 · What happened</span><h4>{selectedRcaDecision.rootCause}</h4><p>{!hasEvidence ? "No linked diagnostic evidence is available to support a causal explanation." : selectedRcaDecision.status === "hypothesis" ? "This is the leading explanation, not yet a confirmed cause." : selectedRcaDecision.status === "insufficient-evidence" ? "There is not enough evidence to confirm a cause yet." : "The available evidence supports this explanation."}</p></article>
          <article><span>2 · Why it matters</span><h4>{selectedRcaDecision.customerImpact}</h4><p>{selectedRcaDecision.serviceImpact}</p></article>
          <article><span>3 · What to do next</span><h4>{selectedRcaDecision.action}</h4><p>{!hasEvidence ? "Collect and review diagnostic evidence before creating or approving an execution plan." : selectedRcaDecision.reviewRequired ? "Review the evidence gaps before any change is made." : "Review the target and safeguards, then continue to the governed execution plan."}</p></article>
        </div>
        <div className={selectedRcaDecision.reviewRequired ? "understand-simple-callout needs-review" : "understand-simple-callout is-ready"}><ShieldAlert size={18} /><div><strong>{!hasEvidence ? "Evidence collection required" : selectedRcaDecision.reviewRequired ? "Human review required" : "Ready for operator review"}</strong><span>{!hasEvidence ? "0 linked diagnostic records. The analysis is ungrounded and execution is blocked." : selectedAiTrust.missing.length ? `${selectedAiTrust.missing.length} evidence gap(s) remain. Open Evidence before approving a change.` : `${selectedAiTrust.evidence.length} evidence record(s) support this explanation.`}</span></div></div>
        <footer><button type="button" className="button-secondary" onClick={() => onSetRcaDetailView("detailed")}>See detailed explanation</button><button type="button" className="button-secondary" onClick={() => onSetRcaDetailView("evidence")}>Inspect evidence</button><button type="button" className="button-primary" disabled={!hasEvidence} title={!hasEvidence ? "Collect diagnostic evidence before reviewing an action plan." : undefined} onClick={() => onSetHomeDetailTab("execution")}>{hasEvidence ? "Review action plan" : "Evidence required"}</button></footer>
      </section> : null}
      {rcaDetailView === "detailed" ? <section className="rca-decision-brief" aria-labelledby="rca-decision-title">
        <header className="rca-decision-header">
          <div>
            <span className="discovery-eyebrow">Operator decision brief</span>
            <h3 id="rca-decision-title">What happened and who is affected</h3>
          </div>
          <div className={`rca-confidence is-${selectedRcaDecision.confidence >= 0.85 ? "high" : selectedRcaDecision.confidence >= 0.7 ? "medium" : "low"}`}>
            <strong>{confidenceDisplay}</strong>
            <span>{selectedRcaDecision.confidenceLabel}</span>
          </div>
        </header>
        {selectedRcaDecision.reviewRequired ? <div className="rca-review-banner" role="status"><strong>Human review required</strong><span>{selectedAiTrust.missing.length ? `${selectedAiTrust.missing.length} evidence gap(s) remain.` : "Confidence or grounding is below the auto-action threshold."}</span></div> : <div className="rca-ready-banner" role="status"><strong>Evidence is sufficiently grounded</strong><span>Confirm the target and safeguards before execution.</span></div>}
        <div className="understand-decision-layout"><div className="rca-decision-grid">
          <article className="rca-decision-card rca-cause-card"><span>Evidence-backed root cause</span><h4>{selectedRcaDecision.rootCause}</h4><dl><div><dt>Causal mechanism</dt><dd>{selectedRcaDecision.causalDetails}</dd></div><div><dt>Assessment</dt><dd>{selectedRcaDecision.status === "hypothesis" ? "Hypothesis—not yet confirmed." : selectedRcaDecision.status === "insufficient-evidence" ? "Insufficient evidence to assign a cause." : "Grounded in the currently linked evidence."}</dd></div><div><dt>Evidence basis</dt><dd>{selectedRcaDecision.rca?.evidence_used?.length ? selectedRcaDecision.rca.evidence_used.join(", ") : "No RCA evidence identifiers were supplied; human validation is required."}</dd></div></dl></article>
          <article className="rca-decision-card rca-impact-card"><span>Observed impact and business risk</span><h4>{selectedRcaDecision.customerImpact}</h4><dl><div><dt>Observed service impact</dt><dd>{selectedRcaDecision.serviceImpact}</dd></div><div><dt>Dependency impact</dt><dd>{selectedRcaDecision.dependencyImpact}</dd></div><div><dt>Operational priority</dt><dd>{selectedRcaDecision.urgency}</dd></div>{selectedRcaDecision.impactedServices.length ? <div><dt>Affected services</dt><dd>{selectedRcaDecision.impactedServices.join(", ")}</dd></div> : null}<div><dt>Impact evidence</dt><dd>{selectedRcaDecision.impactEvidence.length ? selectedRcaDecision.impactEvidence.join(", ") : "No impact evidence identifiers were supplied; customer impact must not be assumed."}</dd></div></dl></article>
        </div><aside className="understand-action-rail">
          <div className="understand-confidence-ring" style={{ "--confidence": `${Math.round(selectedRcaDecision.confidence * 100)}%` } as React.CSSProperties}><span><strong>{confidenceDisplay}</strong><small>{hasEvidence ? "confidence" : "ungrounded"}</small></span></div>
          <div><span className="discovery-eyebrow">Recommended response</span><h4>{selectedRcaDecision.action}</h4><p>{selectedRcaDecision.reviewRequired ? "Operator confirmation is required before execution." : "Evidence meets the current action threshold."}</p></div>
          <dl><div><dt>Grounding</dt><dd>{hasEvidence ? formatQualityPercent(selectedAlertEvaluation.groundingScore) : "Unavailable"}</dd></div><div><dt>Citations</dt><dd>{hasEvidence ? formatQualityPercent(selectedAlertEvaluation.citationCoverage) : "Unavailable"}</dd></div><div><dt>Evidence gaps</dt><dd>{selectedAiTrust.missing.length}</dd></div></dl>
          <div className="rca-decision-actions"><button type="button" className="button-primary" disabled={!hasEvidence} title={!hasEvidence ? "Collect diagnostic evidence before reviewing a plan." : undefined} onClick={() => onSetHomeDetailTab("execution")}>{!hasEvidence ? "Evidence required" : selectedRcaDecision.reviewRequired ? "Review plan" : "Continue"}</button></div>
        </aside></div>
        <section className="resolution-catalog" aria-labelledby="resolution-catalog-title">
          <header><div><span className="discovery-eyebrow">Resolution dictionary</span><h4 id="resolution-catalog-title">Choose the most relevant response</h4></div><span>{resolutionOptions.length} matched options</span></header>
          <div className="resolution-option-grid">{resolutionOptions.map((option) => <button key={option.id} type="button" className={selectedResolution?.id === option.id ? "selected" : ""} onClick={() => chooseResolution(option)}><span><strong>{option.title}</strong><small>{option.risk} risk</small></span><p>{option.applicability}</p>{option.match_reasons?.length ? <em>Matched: {option.match_reasons.join(", ")}</em> : <em>Diagnostic fallback</em>}</button>)}</div>
          {resolutionStatus ? <p className="resolution-status" role="status">{resolutionStatus}</p> : null}
          {selectedResolution ? <div className="resolution-plan"><div><strong>Prerequisites</strong><ol>{selectedResolution.prerequisites.map((step: string) => <li key={step}>{step}</li>)}</ol></div><div><strong>Agent-prepared steps</strong><ol>{selectedResolution.plan.map((step: any) => <li key={`${step.phase}-${step.instruction}`}><span>{step.phase}</span>{step.instruction}</li>)}</ol></div><div><strong>Rollback</strong><ol>{selectedResolution.rollback.map((step: string) => <li key={step}>{step}</li>)}</ol></div><button type="button" className="button-primary" disabled={!hasEvidence} onClick={() => onSetHomeDetailTab("execution")}>Review safeguards and execute</button></div> : null}
        </section>
        <div className="rca-quality-strip" aria-label="RCA quality indicators"><span><strong>{hasEvidence ? formatQualityPercent(selectedAlertEvaluation.groundingScore) : "Unavailable"}</strong> grounding</span><span><strong>{hasEvidence ? formatQualityPercent(selectedAlertEvaluation.citationCoverage) : "Unavailable"}</strong> citations</span><span><strong>{selectedAiTrust.evidence.length}</strong> evidence records</span><span><strong>{selectedAiTrust.missing.length}</strong> evidence gaps</span></div>
        <section className="rca-reasoning-chain" aria-label="RCA reasoning chain"><article><span>1 · Observed fact</span><p>{selectedAiTrust.evidence.length ? `${selectedAiTrust.evidence.length} linked record(s) were collected from the incident context.` : "No linked evidence records are available."}</p></article><i aria-hidden="true">→</i><article><span>2 · AI inference</span><p>{selectedRcaDecision.rootCause}</p></article><i aria-hidden="true">→</i><article><span>3 · Operator action</span><p>{selectedRcaDecision.action}</p></article></section>
        {proposedCodeChanges.length ? <section className="rca-code-changes" aria-labelledby="rca-code-changes-title"><header><span className="discovery-eyebrow">Code context</span><h4 id="rca-code-changes-title">Proposed source changes</h4></header>{proposedCodeChanges.map((change: any, index: number) => <article key={`${change.evidence_id || "change"}-${index}`}><div><strong>{change.title || "Proposed change"}</strong><code>{change.source_uri || "Source path unavailable"}</code></div><p>{change.explanation || change.limitations || "Review the cited source evidence before applying this change."}</p>{change.patch ? <pre className="result">{change.patch}</pre> : <p className="status-message">Patch withheld: {change.limitations || "more surrounding source context is required."}</p>}</article>)}</section> : null}
        <footer className="rca-analysis-meta"><span>Analysis status: <strong>{selectedRcaDecision.status.replaceAll("-", " ")}</strong></span><span>Last evidence: <strong>{selectedAiTrust.evidence[0]?.timestamp ? formatUtcTimestamp(selectedAiTrust.evidence[0].timestamp) : "timestamp not supplied"}</strong></span><span>Version: <strong>current persisted analysis</strong></span></footer>
      </section> : null}
      {rcaDetailView === "technical" ? <div className="combined-analysis-source-rail">
        <strong>Represented evidence categories</strong>
        {evidenceSources.filter((source) => source.count > 0).map((source) => <span className="source-badge" key={source.key}>{source.label} ({source.count})</span>)}
        {!hasEvidence ? <span>No diagnostic evidence categories represented.</span> : null}
      </div> : null}
      {rcaDetailView === "evidence" ? <section className="ai-trust-panel evidence-review" aria-labelledby="ai-trust-title">
        <header className="evidence-review-header">
          <div><span className="discovery-eyebrow">Evidence review</span><h4 id="ai-trust-title">Why KaiMS reached this recommendation</h4><p>Separate direct observations from inferred conclusions before approving remediation.</p></div>
          <div className={`evidence-confidence is-${qualityToneFromScore(hasEvidence ? selectedAlertEvaluation.confidenceScore : 0)}`}><Sparkles size={17} /><span><strong>{hasEvidence ? formatQualityPercent(selectedAlertEvaluation.confidenceScore) : "Unavailable"}</strong><small>{hasEvidence ? "analysis confidence" : "ungrounded analysis"}</small></span></div>
        </header>
        <div className="evidence-health-strip" aria-label="Evidence health"><span><i><Database size={16} /></i><strong>{selectedAiTrust.evidence.length}</strong><small>linked records</small></span><span><i><Activity size={16} /></i><strong>{selectedAiTrust.evidence.filter((row: any) => !row.cached).length}</strong><small>fresh observations</small></span><span><i><Clock3 size={16} /></i><strong>{selectedAiTrust.evidence.filter((row: any) => row.cached).length}</strong><small>cached context</small></span><span className={selectedAiTrust.conflicting.length ? "has-risk" : "is-clear"}><i><ShieldAlert size={16} /></i><strong>{selectedAiTrust.conflicting.length}</strong><small>conflicts</small></span><span className={selectedAiTrust.missing.length ? "has-risk" : "is-clear"}><i><Search size={16} /></i><strong>{selectedAiTrust.missing.length}</strong><small>evidence gaps</small></span></div>
        <section className="evidence-inference-brief"><div><span>AI inference</span><strong>{selectedAiTrust.analysis.root_cause || canonicalIncidentAnalysis(selectedAlertWorkflow, selectedAlertRow).rootCause}</strong></div><button type="button" className="button-secondary" onClick={() => onSetRcaDetailView("detailed")}>Compare decision</button></section>
        {selectedAiTrust.evidence.some((row: any) => row.cached && row.freshness === "Stale") ? <p className="ai-trust-warning" role="status">Cached context may predate the current deployment. Validate the target before acting.</p> : null}
        <details className="evidence-model-details"><summary>Analysis diagnostics and model details</summary><div className="ai-trust-summary-grid ai-trust-summary-compact">
          <div><strong>Confidence reasons</strong><ul>{selectedAiTrust.confidenceReasons.map((reason: string) => <li key={reason}>{reason}</li>)}</ul></div>
          <div><strong>Model / provider</strong><p>{selectedAiTrust.providerRow ? `${selectedAiTrust.providerRow.model} / ${selectedAiTrust.providerRow.provider}` : "Not supplied by the workflow contract"}</p></div>
          <div><strong>Fallback model</strong><p>{selectedAiTrust.fallbackUsed ? "Used; review required" : "No fallback usage reported"}</p></div>
          <div><strong>Recommendation attempts</strong><p>{selectedAlertRegeneration.message || "One persisted attempt is available; comparison history was not supplied."}</p></div>
        </div></details>
        <details className="evidence-ledger evidence-ledger-modern" open>
          <summary><div><strong>Evidence ledger</strong><span>{selectedAiTrust.evidence.length} linked records · expand for citations and freshness</span></div><span>View records</span></summary>
          <div className="table-wrap ai-evidence-table contained-table">
            <table>
              <thead><tr><th>Source</th><th>Observed</th><th>Freshness</th><th>Citation</th><th>Context</th></tr></thead>
              <tbody>{selectedAiTrust.evidence.length ? selectedAiTrust.evidence.map((row: any) => (
                <tr key={row.id}><td><span className="source-badge">{row.source}</span></td><td>{row.timestamp ? formatUtcTimestamp(row.timestamp) : "Timestamp unavailable"}<small className="table-secondary">{row.age}</small></td><td><span className={`evidence-freshness ${row.cached ? "is-cached" : "is-fresh"}`}>{row.cached ? "Cached" : "Fresh"}</span><small className="table-secondary">{row.freshness}</small></td><td className="evidence-citation"><code title={row.citation || "Not supplied"}>{row.citation || "Not supplied"}</code></td><td>{row.cached ? "Historical context" : "Live discovery"}</td></tr>
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
