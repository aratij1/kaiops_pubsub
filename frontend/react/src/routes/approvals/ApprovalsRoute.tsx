import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, FileSearch, RefreshCw, ShieldCheck } from "lucide-react";

import { useRouteRuntime } from "../../app/routeRuntime";
import { OperationsWorkflowNav } from "../../components/operations/OperationsWorkflowNav";
import { decisionReadiness } from "../../domain/incidentStatus";
import { approvalDecisionFields } from "../../domain/approvalDecisionPacket";
import "./ApprovalsRoute.css";

type Packet = Record<string, any>;
const objectValue = (...values: unknown[]): Packet => (values.find((value) => value && typeof value === "object") || {}) as Packet;
const textValue = (...values: unknown[]): string => {
  const value = values.find((item) => item !== undefined && item !== null && String(item).trim());
  return value === undefined ? "Not provided" : String(value);
};
const percentage = (value: unknown): string => {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number <= 1 ? number * 100 : number)}%` : "Not measured";
};

export default function ApprovalsRoute() {
  const { approvals, session } = useRouteRuntime();
  const [view, setView] = useState<"queue" | "review">("queue");
  const [evidenceRequest, setEvidenceRequest] = useState("");
  const [showEvidenceRequest, setShowEvidenceRequest] = useState(false);
  const [modifyPlan, setModifyPlan] = useState({ open: false, capability: "", target: "", reason: "" });
  const selected = approvals.rows.find((row) => approvals.incidentId(row) === approvals.selectedIncidentId);
  const packet = useMemo(() => {
    const row = (selected || {}) as Packet;
    const projection = objectValue(row.projection_payload);
    const event = objectValue(projection.event_payload);
    const recommendation = objectValue(projection.recommendation, event.recommendation, row.recommendation);
    const metadata = objectValue(recommendation.metadata);
    const plan = objectValue(metadata.execution_plan, projection.execution_plan, event.execution_plan);
    const quality = objectValue(metadata.evidence_quality, metadata.readiness, projection.evidence_quality);
    const policy = objectValue(plan.policy_decision, metadata.policy_decision);
    const readinessReceipt = objectValue(row.approval_readiness, metadata.approval_readiness, plan.approval_readiness, projection.approval_readiness);
    const backendEligibilityProven = Boolean(
      readinessReceipt.decision_id
      && readinessReceipt.signature
      && ["eligible", "execution_eligible"].includes(String(readinessReceipt.state || readinessReceipt.decision || "").toLowerCase())
    );
    const readiness = decisionReadiness({
      citationCoverage: quality.citation_coverage ?? recommendation.citation_coverage ?? 0,
      evidenceCoverage: quality.evidence_coverage ?? recommendation.evidence_coverage ?? 0,
      evidenceFresh: quality.evidence_fresh !== false,
      conflictCount: quality.conflict_count ?? quality.contradiction_count ?? 0,
      runbookAvailable: Boolean(plan.playbook_id || plan.runbook_id),
      preflightReady: Array.isArray(plan.preflight_commands || plan.preflight) && (plan.preflight_commands || plan.preflight).length > 0,
      rollbackAvailable: plan.rollback_mode === "not_applicable" || (Array.isArray(plan.rollback_commands || plan.rollback) && (plan.rollback_commands || plan.rollback).length > 0),
      dryRunComplete: Boolean(metadata.dry_run_complete),
      risk: plan.risk_tier || row.risk_tier,
    });
    return { row, recommendation, plan, quality, policy, readiness, readinessReceipt, backendEligibilityProven, decision: approvalDecisionFields(row) };
  }, [selected]);
  const approvalDisabled = !approvals.selectedRecommendationId || approvals.actionLoading || !packet.readiness.eligible || !packet.backendEligibilityProven;

  function review(row: any) {
    approvals.select(row);
    setView("review");
  }

  return <section className="grid single-col approval-workspace">
    <OperationsWorkflowNav active="approvals" />
    <article className="panel approval-hero"><div><span className="eyebrow">DECIDE</span><h2>Kai needs your decision</h2><p>Review evidence, risk, target, rollback, and immutable plan identity before authorizing change.</p></div><div className="approval-summary" aria-label="Approval queue summary"><div><strong>{approvals.rows.length}</strong><span>Awaiting review</span></div><div><strong>{session.username}</strong><span>Signed-in reviewer</span></div></div></article>

    {view === "queue" ? <article className="panel">
      <div className="panel-head"><div><h3>Assigned decision queue</h3><p>Choose one incident to open its complete decision packet.</p></div><button className="button-secondary" type="button" onClick={approvals.refresh}><RefreshCw size={16} aria-hidden="true" /> Refresh</button></div>
      <div className="filter-grid approval-compact-filter"><label>Queue filter<select value={approvals.filter} onChange={(event) => approvals.setFilter(event.target.value)}>{["all", "awaiting_approval", "critical", "high", "medium", "low"].map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label></div>
      <div className="approval-card-list">{approvals.rows.map((row, index) => { const incidentId = approvals.incidentId(row); return <button type="button" className="approval-ticket" key={incidentId || index} onClick={() => review(row)}><span><b>{row.service || "Service not recorded"}</b><small>{row.environment || "Environment not recorded"}</small></span><span className={`pill status-${String(row.status || "awaiting_approval").toLowerCase()}`}>{String(row.status || "Awaiting approval").replaceAll("_", " ")}</span><span><small>Risk</small><b>{row.risk_tier || row.severity || "Not assessed"}</b></span><span><small>Incident</small><b>{incidentId || "Identifier unavailable"}</b></span><strong>Review packet →</strong></button>; })}{!approvals.rows.length && !approvals.contextLoading ? <div className="empty-state"><CheckCircle2 aria-hidden="true" /><strong>No approvals need your decision</strong><p>Refresh the queue or return to Incident Queue.</p></div> : null}</div>
    </article> : <article className="panel approval-review">
      <div className="panel-head"><div><span className="eyebrow">IMMUTABLE DECISION PACKET</span><h3>{textValue(packet.row.title, packet.row.service, "Incident review")}</h3><p>{textValue(packet.row.service)} · {textValue(packet.row.environment)} · {textValue(packet.row.severity, packet.row.risk_tier)} risk</p></div><button className="button-secondary" type="button" onClick={() => setView("queue")}>Back to queue</button></div>
      <section className={`approval-readiness status-${packet.backendEligibilityProven ? packet.readiness.state : "blocked"}`} aria-live="polite">{packet.backendEligibilityProven ? <ShieldCheck aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}<div><strong>{packet.backendEligibilityProven ? packet.readiness.label : "Signed backend readiness required"}</strong>{packet.readiness.missing.length ? <p>Missing: {packet.readiness.missing.join(", ")}.</p> : packet.backendEligibilityProven ? <p>Backend decision {String(packet.readinessReceipt.decision_id)} proves the required controls are present.</p> : <p>Local UI fields are advisory and cannot authorize execution.</p>}</div></section>
      <div className="approval-review-summary"><div><small>Incident</small><strong>{approvals.selectedIncidentId || "Unavailable"}</strong></div><div><small>Recommendation</small><strong>{approvals.selectedRecommendationId || "Unavailable"}</strong></div><div><small>Reviewer</small><strong>{session.username}</strong></div><div><small>Plan</small><strong>{textValue(packet.plan.plan_id)}</strong></div><div><small>Plan expiry</small><strong>{textValue(packet.plan.expiry)}</strong></div><div><small>Fingerprint</small><strong>{textValue(packet.plan.plan_fingerprint)}</strong></div></div>
      <section className="approval-decision-story" aria-label="Approval decision context">
        <article><span>What happened</span><p>{packet.decision.whatHappened}</p></article>
        <article><span>Kai diagnosis</span><p>{packet.decision.diagnosis}</p><strong>{percentage(packet.decision.confidence)} confidence</strong></article>
        <article><span>Affected resource</span><p>{packet.decision.affectedResource}</p><strong>{packet.decision.blastRadius} blast radius</strong></article>
        <article><span>Proposed capability</span><p><code>{packet.decision.capability}</code></p><strong>Target: {packet.decision.exactTarget}</strong></article>
        <article><span>Expected effect</span><p>{packet.decision.expectedEffect}</p><strong>{packet.decision.risk} risk</strong></article>
        <article><span>Execution preview</span><p>{packet.decision.executionPreview}</p></article>
      </section>
      <section className="approval-safety-plan" aria-label="Execution safety plan">
        <article><h4>Preconditions</h4>{packet.decision.preconditions.length ? <ol>{packet.decision.preconditions.map((condition: unknown, index: number) => <li key={index}>{textValue(typeof condition === "object" ? JSON.stringify(condition) : condition)}</li>)}</ol> : <p>Not provided</p>}</article>
        <article><h4>Validation plan</h4><p>{packet.decision.validationPlan}</p></article>
        <article><h4>Rollback plan</h4><p>{packet.decision.rollbackPlan}</p></article>
      </section>
      <details className="approval-evidence"><summary>Evidence supporting Kai’s diagnosis ({packet.decision.evidence.length})</summary>{packet.decision.evidence.length ? <ul>{packet.decision.evidence.map((item: unknown, index: number) => <li key={index}>{textValue(typeof item === "object" ? JSON.stringify(item) : item)}</li>)}</ul> : <p>No evidence list was included in the decision packet.</p>}</details>
      <div className="approval-capacity-layout"><section><h4>Evidence and root cause</h4><dl className="decision-packet-list"><div><dt>Proposed cause</dt><dd>{textValue(packet.recommendation.root_cause, packet.recommendation.summary)}</dd></div><div><dt>RCA confidence</dt><dd>{percentage(packet.recommendation.confidence)}</dd></div><div><dt>Evidence coverage</dt><dd>{percentage(packet.quality.evidence_coverage)}</dd></div><div><dt>Citation grounding</dt><dd>{percentage(packet.quality.citation_coverage)}</dd></div><div><dt>Conflicting evidence</dt><dd>{textValue(packet.quality.conflict_count ?? packet.quality.contradiction_count ?? 0)}</dd></div></dl></section><section><h4>Action safety</h4><dl className="decision-packet-list"><div><dt>Catalog action</dt><dd>{textValue(packet.plan.playbook_id, packet.plan.runbook_id, packet.plan.connector_id)}</dd></div><div><dt>Target</dt><dd>{textValue(packet.plan.remediation_target, packet.plan.target_resource_id)}</dd></div><div><dt>Risk</dt><dd>{textValue(packet.plan.risk_tier, packet.row.risk_tier)}</dd></div><div><dt>Policy</dt><dd>{textValue(packet.policy.decision, "HITL required")}</dd></div><div><dt>Rollback</dt><dd>{packet.readiness.missing.includes("rollback readiness") ? "Not ready" : "Ready"}</dd></div></dl></section></div>
      <details><summary>Technical details</summary><pre>{JSON.stringify({ plan: packet.plan, policy: packet.policy }, null, 2)}</pre></details>
      <div className="approval-nav-actions"><button className="button-secondary" type="button" onClick={approvals.sync} disabled={approvals.contextLoading}><FileSearch size={16} aria-hidden="true" />{approvals.contextLoading ? "Refreshing evidence…" : "Refresh evidence"}</button><button className="button-secondary" type="button" onClick={() => selected && approvals.open(selected)}>Open incident workspace</button><button className="button-secondary" type="button" onClick={approvals.openAgentFlow}>Technical timeline</button></div>
      {approvals.contextError ? <p className="error" role="alert">{approvals.contextError}</p> : null}
      <div className="approval-decision-bar" aria-label="Reviewer actions">
        <button className="button-secondary" type="button" onClick={() => setShowEvidenceRequest((current) => !current)}><FileSearch size={16} aria-hidden="true" />Request more evidence</button>
        <button className="button-secondary" type="button" onClick={() => selected && approvals.approveDryRun(selected)} disabled={approvalDisabled}><ShieldCheck size={16} aria-hidden="true" />{approvals.actionLoading ? "Recording…" : "Approve dry run"}</button>
        <button className="button-primary" type="button" onClick={() => selected && approvals.approveExecution(selected)} disabled={approvalDisabled || packet.readiness.state !== "execution_eligible"}><ShieldCheck size={16} aria-hidden="true" />{approvals.actionLoading ? "Recording…" : "Approve"}</button>
        <button className="button-secondary" type="button" onClick={() => setModifyPlan((current) => ({ ...current, open: !current.open, capability: current.capability || packet.decision.capability, target: current.target || packet.decision.exactTarget }))}>Modify</button>
        <button className="button-secondary" type="button" onClick={() => approvals.toggleReject(approvals.selectedIncidentId)}>Reject</button>
      </div>
      {modifyPlan.open ? <div className="inline-decision approval-modify-plan"><p>Modification creates a new typed plan and checksum. The current plan remains unchanged and unapproved.</p><label>Capability<input value={modifyPlan.capability} onChange={(event) => setModifyPlan((current) => ({ ...current, capability: event.target.value }))} /></label><label>Exact target<input value={modifyPlan.target} onChange={(event) => setModifyPlan((current) => ({ ...current, target: event.target.value }))} /></label><label>Required change<textarea rows={3} value={modifyPlan.reason} onChange={(event) => setModifyPlan((current) => ({ ...current, reason: event.target.value }))} placeholder="Explain why Kai must compile a replacement plan." /></label><button className="button-primary" type="button" disabled={!modifyPlan.capability.trim() || !modifyPlan.target.trim() || !modifyPlan.reason.trim() || approvals.actionLoading} onClick={() => { if (selected) approvals.requestEvidence(selected, `Compile a replacement typed plan. Capability: ${modifyPlan.capability}. Target: ${modifyPlan.target}. Required change: ${modifyPlan.reason}`); setModifyPlan({ open: false, capability: "", target: "", reason: "" }); }}>Request modified plan</button></div> : null}
      {showEvidenceRequest ? <div className="inline-decision"><label>Evidence request<textarea required rows={3} value={evidenceRequest} onChange={(event) => setEvidenceRequest(event.target.value)} placeholder="Specify the missing logs, metrics, traces, topology, or change history." /></label><button className="button-primary" type="button" disabled={!evidenceRequest.trim() || approvals.actionLoading} onClick={() => { if (selected) approvals.requestEvidence(selected, evidenceRequest.trim()); }}>Send evidence request</button></div> : null}
      {!packet.readiness.eligible ? <p className="status-message">Approval is disabled until missing decision evidence or safety controls are supplied.</p> : null}
      {approvals.inlineReject.incidentId === approvals.selectedIncidentId ? <div className="inline-decision"><label>Reason<textarea required rows={3} value={approvals.inlineReject.comment} onChange={(event) => approvals.setRejectComment(approvals.selectedIncidentId, event.target.value)} placeholder="Explain what is incorrect, incomplete, or unsafe." /></label><button className="button-primary" type="button" onClick={() => selected && approvals.reject(selected)} disabled={!approvals.inlineReject.comment.trim() || approvals.actionLoading}>Confirm rejection</button></div> : null}
      {approvals.actionResult ? <section className="approval-receipt" aria-live="polite"><CheckCircle2 aria-hidden="true" /><div><strong>Immutable decision receipt recorded</strong><p>The durable response includes the reviewer, tenant-bound plan identity, authorization scope, and timestamp.</p><details><summary>View receipt details</summary><pre>{JSON.stringify(approvals.actionResult, null, 2)}</pre></details></div></section> : null}
      {approvals.actionError ? <p className="error" role="alert">{approvals.actionError}</p> : null}
    </article>}
  </section>;
}
