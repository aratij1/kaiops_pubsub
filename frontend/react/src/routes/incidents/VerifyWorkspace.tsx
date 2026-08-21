import "./VerifyWorkspace.css";

type UnknownRecord = Record<string, unknown>;

type TimelineRow = {
  stage?: string;
  agent?: string;
  timestamp?: string;
  detail?: string;
  backendEvents?: string[];
};

type VerifyWorkspaceProps = {
  incidentId?: string;
  incidentStatus?: string;
  workflow?: UnknownRecord;
  executionPlan?: UnknownRecord;
  remediationOutcome?: UnknownRecord | null;
  timelineRows?: TimelineRow[];
  documentCount?: number;
};

const TERMINAL_EXECUTION = new Set([
  "succeeded", "failed", "completed", "closed", "resolved", "policy_blocked",
  "dispatch_failed", "execution_failed", "validation_failed", "rolled_back",
  "rollback_failed", "timed_out", "cancelled", "manual_intervention_required",
]);

function record(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
}

function displayTime(value: string): string {
  if (!value) return "Time unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function findTimeline(rows: TimelineRow[], terms: string[]): TimelineRow | undefined {
  return [...rows].reverse().find((row) => {
    const haystack = `${row.stage || ""} ${(row.backendEvents || []).join(" ")} ${row.agent || ""}`.toLowerCase();
    return terms.some((term) => haystack.includes(term));
  });
}

export default function VerifyWorkspace({
  incidentId = "",
  incidentStatus = "",
  workflow = {},
  executionPlan = {},
  remediationOutcome = null,
  timelineRows = [],
  documentCount = 0,
}: VerifyWorkspaceProps) {
  const recommendation = record(workflow.recommendation);
  const approval = record(workflow.approval || executionPlan.approval);
  const action = record(executionPlan.remediationAction || workflow.remediation_action);
  const outcome = record(remediationOutcome);
  const context = record(workflow.context);
  const status = text(action.status || outcome.status).toLowerCase();
  const validation = record(action.validation || action.validation_result || record(action.parameters).validation);
  const rollback = record(action.rollback || record(action.parameters).rollback_result);
  const learning = record(workflow.learning || workflow.learning_record || workflow.outcome);
  const isTerminal = TERMINAL_EXECUTION.has(status);

  const definitions = [
    { label: "Detection", present: Boolean(workflow.alert || workflow.incident || incidentId), terms: ["alert", "detect", "incident created"], source: "Alert and incident record", value: text(record(workflow.alert).id || incidentId) },
    { label: "Evidence", present: Boolean(context.id || context.created_at || documentCount || timelineRows.length), terms: ["context", "evidence", "discovery"], source: `${documentCount} linked document${documentCount === 1 ? "" : "s"}`, value: text(context.id) },
    { label: "RCA", present: Boolean(recommendation.root_cause || recommendation.id), terms: ["root cause", "rca", "recommendation"], source: "Root-cause recommendation", value: text(recommendation.id || recommendation.recommendation_id) },
    { label: "Plan", present: Boolean(executionPlan.catalogPlan || executionPlan.action || action.action), terms: ["plan", "resolution"], source: "Governed execution catalog", value: text(record(executionPlan.catalogPlan).plan_id || record(executionPlan.catalogPlan).id) },
    { label: "Approval", present: Boolean(approval.status || approval.id), terms: ["approval", "human"], source: text(approval.status) || "Approval decision", value: text(approval.id || approval.approval_id) },
    { label: "Execution", present: Boolean(action.id || status), terms: ["remediation", "execution", "executor"], source: status || "Remediation action", value: text(action.id || action.action_id) },
    { label: "Validation", present: Boolean(Object.keys(validation).length || ["succeeded", "validation_failed", "rolled_back", "rollback_failed"].includes(status)), terms: ["validation", "verify", "health"], source: text(validation.status || validation.result) || (isTerminal ? "Terminal result recorded" : "Awaiting executor result"), value: text(validation.id) },
    { label: "Outcome", present: Boolean(isTerminal || incidentStatus === "closed" || incidentStatus === "resolved"), terms: ["outcome", "closed", "resolved", "rollback"], source: status || incidentStatus || "Incident outcome", value: text(outcome.id || action.id) },
    { label: "Learning", present: Boolean(Object.keys(learning).length), terms: ["learning", "runbook", "knowledge"], source: Object.keys(learning).length ? "Learning record linked" : "Created after outcome review", value: text(learning.id || learning.event_id) },
  ];

  const checkpoints = definitions.map((definition, index) => {
    const event = findTimeline(timelineRows, definition.terms);
    const previousComplete = definitions.slice(0, index).every((item) => item.present);
    return {
      ...definition,
      state: definition.present ? "recorded" : previousComplete ? "pending" : "missing",
      time: event?.timestamp || "",
      detail: event?.detail || definition.source,
    };
  });
  const recorded = checkpoints.filter((item) => item.state === "recorded").length;
  const hashes = timelineRows.flatMap((row) => {
    const candidate = record(row as unknown as UnknownRecord);
    return [text(candidate.payload_sha256 || candidate.sha256 || candidate.hash)].filter(Boolean);
  });
  const recoveryRequired = ["validation_failed", "failed", "execution_failed", "rollback_failed", "manual_intervention_required"].includes(status);

  return (
    <section className="verify-workspace" aria-labelledby="verify-workspace-title">
      <header className="verify-workspace__header">
        <div>
          <span className="discovery-eyebrow">Verify · closed-loop evidence</span>
          <h3 id="verify-workspace-title">Incident evidence receipt</h3>
          <p>Trace the operational decision from detection through learning. Missing evidence is shown explicitly.</p>
        </div>
        <div className="verify-workspace__score" aria-label={`${recorded} of ${checkpoints.length} checkpoints recorded`}>
          <strong>{recorded}/{checkpoints.length}</strong>
          <span>recorded</span>
        </div>
      </header>

      <ol className="verify-checkpoints" aria-label="Incident lifecycle checkpoints">
        {checkpoints.map((item, index) => (
          <li key={item.label} className={`verify-checkpoint is-${item.state}`}>
            <span className="verify-checkpoint__index" aria-hidden="true">{index + 1}</span>
            <div>
              <span className="verify-checkpoint__state">{item.state}</span>
              <strong>{item.label}</strong>
              <p>{item.detail}</p>
              <small>{displayTime(item.time)}{item.value ? ` · ${item.value}` : ""}</small>
            </div>
          </li>
        ))}
      </ol>

      <div className="verify-summary-grid">
        <article className={recoveryRequired ? "is-attention" : "is-stable"}>
          <span>Recovery posture</span>
          <strong>{status ? status.replaceAll("_", " ") : "No execution yet"}</strong>
          <p>{Object.keys(rollback).length ? `Rollback evidence: ${text(rollback.status || rollback.result) || "recorded"}.` : recoveryRequired ? "Recovery needs operator attention; no rollback receipt is linked." : "No recovery action is currently required."}</p>
        </article>
        <article>
          <span>Receipt integrity</span>
          <strong>{hashes.length ? `${hashes.length} verified hash${hashes.length === 1 ? "" : "es"}` : "Append-only trail"}</strong>
          <p>{hashes.length ? "Backend-provided SHA-256 evidence is attached to this view." : "The event trail is read-only here. A cryptographic claim is withheld until a backend hash is supplied."}</p>
        </article>
        <article>
          <span>Incident reference</span>
          <strong>{incidentId || "Unavailable"}</strong>
          <p>Current incident state: {incidentStatus || "unknown"}.</p>
        </article>
      </div>
    </section>
  );
}
