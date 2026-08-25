import { memo } from "react";
import { useNavigate } from "react-router-dom";

const steps = [
  { id: "alerts", path: "/alerts", number: "01", label: "Live Alerts", description: "Detect and triage" },
  { id: "incidents", path: "/incidents", number: "02", label: "Unified Inbox", description: "Triage signals and incidents" },
  { id: "approvals", path: "/approvals", number: "03", label: "Approvals", description: "Review and decide" },
] as const;

export const OperationsWorkflowNav = memo(function OperationsWorkflowNav({ active }: { active: "alerts" | "incidents" | "approvals" }) {
  const navigate = useNavigate();
  return <nav className="operations-workflow-nav" aria-label="Operations workflow">
    {steps.map((step) => <button type="button" key={step.id} className={active === step.id ? "active" : ""} aria-current={active === step.id ? "page" : undefined} onClick={() => active !== step.id && navigate(step.path)}><span>{step.number}</span><strong>{step.label}</strong><small>{step.description}</small></button>)}
  </nav>;
});
