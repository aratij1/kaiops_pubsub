import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useRouteRuntime } from "../../app/routeRuntime";
import { askCopilot } from "../../services/copilot";
import type { CopilotAnswer } from "../../schemas/copilot";

const onboardingSteps = [
  ["1", "Describe the application", "Capture ownership, environments, criticality, and service boundaries."],
  ["2", "Connect monitoring", "Register telemetry, alert sources, credentials, and connection health."],
  ["3", "Prepare operations", "Add alert guidance and validate that responders have the right access."],
] as const;

export default function CopilotRoute() {
  const { copilot, session } = useRouteRuntime();
  const navigate = useNavigate();
  const [question, setQuestion] = useState("");
  const askMutation = useMutation({
    mutationFn: (query: string) => askCopilot(session.accessToken, query),
  });

  const handleAsk = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;
    askMutation.mutate(trimmed);
  };

  const recommendedAction = copilot.projectCount === 0
    ? { label: "Onboard your first application", detail: "Start with ownership and monitoring details so incoming alerts have reliable context.", action: () => copilot.openWorkspace("project") }
    : copilot.alertDocumentCount === 0
      ? { label: "Add operational knowledge", detail: "Create alert guidance so new incidents can reuse validated context and resolution history.", action: () => copilot.openWorkspace("alerts") }
      : { label: "Investigate an incident", detail: "Open the incident cockpit to review context, RCA, impact, approval, and execution in one flow.", action: copilot.openIncidentMetadata };

  return (
    <section className="grid single-col copilot-workspace">
      <article className="panel copilot-hero">
        <div>
          <span className="eyebrow">GUIDED OPERATIONS</span>
          <h2>Copilot Studio</h2>
          <p>Choose an outcome or ask a question. KaiOps will guide you to the right workflow.</p>
        </div>
        <div className="copilot-health" data-ready={copilot.platformReady}>
          <span aria-hidden="true" />
          <div><strong>{copilot.platformReady ? "Platform ready" : "Platform needs attention"}</strong><small>{copilot.platformReady ? "Core services are available" : "Check platform health before setup"}</small></div>
          <button className="button-secondary" type="button" onClick={copilot.refresh}>Refresh status</button>
        </div>
      </article>

      <article className="panel copilot-ask">
        <div className="panel-head"><div><h3>Ask Copilot</h3><p>Ask about capacity, why a ticket wasn't assigned, or what's pending in onboarding.</p></div></div>
        <form onSubmit={handleAsk} className="copilot-ask-form">
          <input
            type="text"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="e.g. Who has capacity this week?"
            aria-label="Ask Copilot"
          />
          <button type="submit" className="button-primary" disabled={askMutation.isPending || !question.trim()}>
            {askMutation.isPending ? "Asking..." : "Ask"}
          </button>
        </form>
        {askMutation.isError ? <p className="error">Copilot couldn't answer that right now. Please try again.</p> : null}
        {askMutation.data ? <CopilotAnswerCard answer={askMutation.data} onNavigate={navigate} /> : null}

        <div className="panel-head copilot-ask-accomplish-head"><div><h3>What do you want to accomplish?</h3><p>Each option opens an existing end-to-end workspace; your current data is preserved.</p></div></div>
        <div className="copilot-journey-grid">
          <button type="button" className="copilot-journey-card copilot-tone-ops" onClick={copilot.openIncidentMetadata}>
            <span className="copilot-card-kicker">RESPOND</span><strong>Investigate an incident</strong><span>Review evidence, RCA, impact, approval, execution, and validation.</span><b>Open incident cockpit →</b>
          </button>
          <button type="button" className="copilot-journey-card copilot-tone-bus" onClick={() => copilot.openWorkspace("project")}>
            <span className="copilot-card-kicker">SET UP</span><strong>Onboard an application</strong><span>Capture project ownership, environments, monitoring sources, and connections.</span><b>Open guided onboarding →</b>
          </button>
          <button type="button" className="copilot-journey-card copilot-tone-meta" onClick={() => copilot.openWorkspace("alerts")}>
            <span className="copilot-card-kicker">TEACH</span><strong>Add operational knowledge</strong><span>Create alert documents and reusable context for continuous mode.</span><b>Manage alert knowledge →</b>
          </button>
          <button type="button" className="copilot-journey-card" onClick={() => copilot.openWorkspace("users")} disabled={!copilot.isAdministrator}>
            <span className="copilot-card-kicker">ADMINISTER</span><strong>Manage responder access</strong><span>{copilot.isAdministrator ? "Create users, update roles, and maintain operational access." : "Administrator access is required for user and role management."}</span><b>{copilot.isAdministrator ? "Open user management →" : "Administrator only"}</b>
          </button>
        </div>
      </article>

      <article className="panel copilot-next-action">
        <div><span className="eyebrow">RECOMMENDED NEXT STEP</span><h3>{recommendedAction.label}</h3><p>{recommendedAction.detail}</p></div>
        <button type="button" className="button-primary" onClick={recommendedAction.action}>Start guided task</button>
      </article>

      <div className="copilot-support-grid">
        <article className="panel"><h3>Application onboarding path</h3><p className="muted">A complete setup follows three understandable stages.</p><ol className="copilot-step-list">{onboardingSteps.map(([step, title, description]) => <li key={step}><span>{step}</span><div><strong>{title}</strong><p>{description}</p></div></li>)}</ol><button type="button" className="button-secondary" onClick={() => copilot.openWorkspace("project")}>View full onboarding flow</button></article>
        <article className="panel"><h3>Your workspace</h3><p className="muted">Live inventory helps you understand what is already configured.</p><dl className="copilot-inventory"><div><dt>Applications</dt><dd>{copilot.projectCount}</dd></div><div><dt>Alert documents</dt><dd>{copilot.alertDocumentCount}</dd></div>{copilot.isAdministrator ? <div><dt>Users</dt><dd>{copilot.userCount}</dd></div> : null}</dl><p className="copilot-help"><strong>How Copilot helps</strong><br />New alerts collect context by default. Validated incident outcomes become reusable knowledge, reducing repeated discovery.</p></article>
      </div>
    </section>
  );
}

function CopilotAnswerCard({ answer, onNavigate }: { answer: CopilotAnswer; onNavigate: (path: string) => void }) {
  return (
    <div className="copilot-answer" role="status">
      <p>{answer.answer}</p>
      {answer.links?.length ? (
        <div className="copilot-answer-links">
          {answer.links.map((link) => (
            <button key={link.path} type="button" className="button-secondary" onClick={() => onNavigate(link.path)}>
              {link.label} →
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
