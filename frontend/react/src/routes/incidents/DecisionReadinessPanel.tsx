import { CheckCircle2, CircleAlert, CircleDashed, ShieldCheck } from "lucide-react";

export interface ReadinessCheck {
  id: string;
  label: string;
  detail: string;
  passed: boolean;
  action?: string;
}

interface DecisionReadinessPanelProps {
  title?: string;
  checks: ReadinessCheck[];
  eligibleLabel?: string;
  onReviewEvidence?: () => void;
}

export default function DecisionReadinessPanel({
  title = "Decision readiness",
  checks,
  eligibleLabel = "Ready for guarded operator review",
  onReviewEvidence,
}: DecisionReadinessPanelProps) {
  const missing = checks.filter((check) => !check.passed);
  const ready = checks.length > 0 && missing.length === 0;

  return (
    <section className={`readiness-gate ${ready ? "is-ready" : "is-blocked"}`} aria-labelledby="readiness-gate-title">
      <header>
        <div>
          <span className="discovery-eyebrow">Evidence and safety gate</span>
          <h4 id="readiness-gate-title">{title}</h4>
        </div>
        <span className="readiness-gate-status" role="status">
          {ready ? <ShieldCheck size={18} /> : <CircleAlert size={18} />}
          {ready ? eligibleLabel : `Not ready · ${missing.length} requirement${missing.length === 1 ? "" : "s"}`}
        </span>
      </header>
      <ul className="readiness-checks">
        {checks.map((check) => (
          <li key={check.id} className={check.passed ? "is-passed" : "is-missing"}>
            {check.passed ? <CheckCircle2 size={17} /> : <CircleDashed size={17} />}
            <div><strong>{check.label}</strong><span>{check.detail}</span></div>
          </li>
        ))}
      </ul>
      {!ready ? <footer>
        <p><strong>Next:</strong> {missing.map((check) => check.action || check.label).join("; ")}.</p>
        {onReviewEvidence ? <button type="button" className="button-secondary" onClick={onReviewEvidence}>Review missing evidence</button> : null}
      </footer> : null}
    </section>
  );
}
