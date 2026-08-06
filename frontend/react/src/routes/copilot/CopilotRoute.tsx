import { useState } from "react";
import { useRouteRuntime } from "../../app/routeRuntime";

const onboardingSteps = [
  ["1", "Describe the application", "Capture ownership, environments, criticality, and service boundaries."],
  ["2", "Connect monitoring", "Register telemetry, alert sources, credentials, and connection health."],
  ["3", "Prepare operations", "Add alert guidance and validate that responders have the right access."],
] as const;

export default function CopilotRoute() {
  const { copilot } = useRouteRuntime();
  const [chatInput, setChatInput] = useState("");
  const [chatLog, setChatLog] = useState([]);

  const handleChatSubmit = (e) => {
    e.preventDefault();
    if (!chatInput.trim()) return;
    setChatLog([...chatLog, { role: "user", text: chatInput }, { role: "assistant", text: "Processing your request..." }]);
    setChatInput("");
    // In a full implementation, this would send a request to the backend copilot endpoint
    setTimeout(() => {
      setChatLog(curr => [...curr.slice(0, -1), { role: "assistant", text: "Based on the latest telemetry, the platform is stable. There are 2 pending approvals in your queue." }]);
    }, 1000);
  };

  const dynamicInsights = copilot.projectCount === 0 
    ? ["No applications onboarded yet. Start with the guided onboarding."] 
    : [
      `${copilot.alertDocumentCount} alert documents are active and being used for context enrichment.`,
      "Service 'payment-gateway' has generated 12 anomalies in the last 24 hours.",
      "2 executions are pending your approval."
    ];

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

      <article className="panel copilot-chat-panel">
        <div className="panel-head">
          <div><span className="eyebrow">INTERACTIVE COPILOT</span><h3>Ask Copilot</h3><p>Query platform status, request analysis, or find specific incidents.</p></div>
        </div>
        <div className="copilot-chat-log">
          {chatLog.length === 0 ? <p className="muted">Example: "Show me recent unhandled alerts" or "What's the status of the payment gateway?"</p> : null}
          {chatLog.map((msg, idx) => (
            <div key={idx} className={`chat-message role-${msg.role}`}><strong>{msg.role === "user" ? "You" : "Copilot"}</strong><p>{msg.text}</p></div>
          ))}
        </div>
        <form onSubmit={handleChatSubmit} className="copilot-chat-form">
          <input type="text" placeholder="Ask a question..." value={chatInput} onChange={e => setChatInput(e.target.value)} />
          <button type="submit" className="button-primary">Send</button>
        </form>
      </article>

      <article className="panel copilot-next-action">
        <div><span className="eyebrow">PROACTIVE INSIGHTS</span><h3>Platform Intelligence</h3>
          <ul className="copilot-insights-list">
            {dynamicInsights.map((insight, idx) => <li key={idx}>{insight}</li>)}
          </ul>
        </div>
        <div className="insight-action-area">
          <span className="eyebrow">RECOMMENDED NEXT STEP</span>
          <strong>{recommendedAction.label}</strong>
          <p>{recommendedAction.detail}</p>
          <button type="button" className="button-primary" onClick={recommendedAction.action}>Start guided task</button>
        </div>
      </article>

      <article className="panel">
        <div className="panel-head"><div><h3>What do you want to accomplish?</h3><p>Each option opens an existing end-to-end workspace; your current data is preserved.</p></div></div>
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

      <div className="copilot-support-grid">
        <article className="panel"><h3>Application onboarding path</h3><p className="muted">A complete setup follows three understandable stages.</p><ol className="copilot-step-list">{onboardingSteps.map(([step, title, description]) => <li key={step}><span>{step}</span><div><strong>{title}</strong><p>{description}</p></div></li>)}</ol><button type="button" className="button-secondary" onClick={() => copilot.openWorkspace("project")}>View full onboarding flow</button></article>
        <article className="panel"><h3>Your workspace</h3><p className="muted">Live inventory helps you understand what is already configured.</p><dl className="copilot-inventory"><div><dt>Applications</dt><dd>{copilot.projectCount}</dd></div><div><dt>Alert documents</dt><dd>{copilot.alertDocumentCount}</dd></div>{copilot.isAdministrator ? <div><dt>Users</dt><dd>{copilot.userCount}</dd></div> : null}</dl><p className="copilot-help"><strong>How Copilot helps</strong><br />New alerts collect context by default. Validated incident outcomes become reusable knowledge, reducing repeated discovery.</p></article>
      </div>
    </section>
  );
}
