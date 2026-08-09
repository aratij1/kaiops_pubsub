import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Bot, Sparkles } from "lucide-react";
import { useRouteRuntimeSlice } from "../../app/routeRuntime";
import { askCopilot } from "../../services/copilot";
import type { CopilotAnswer } from "../../schemas/copilot";
import "./CopilotRoute.css";

const prompts = ["Summarize what needs attention", "Explain the lowest-confidence RCA", "Show work waiting for approval", "Which application needs setup?"];
interface Turn { id: number; question: string; answer?: CopilotAnswer; error?: string; }

function KAIAvatar() {
  return <span className="kai-avatar" aria-hidden="true"><Bot size={22} strokeWidth={1.9} /><i><Sparkles size={10} /></i></span>;
}

export default function CopilotRoute() {
  const copilot = useRouteRuntimeSlice("copilot");
  const session = useRouteRuntimeSlice("session");
  const navigate = useNavigate();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const askMutation = useMutation({ mutationFn: (query: string) => askCopilot(session.accessToken, query), onSuccess: (answer, query) => setTurns((current) => [...current, { id: Date.now(), question: query, answer }]), onError: (_error, query) => setTurns((current) => [...current, { id: Date.now(), question: query, error: "KaiMS could not complete this request. Check platform health or try a narrower question." }]) });
  const submit = (event: React.FormEvent) => { event.preventDefault(); const value = question.trim(); if (!value || askMutation.isPending) return; setQuestion(""); askMutation.mutate(value); };
  const recommended = copilot.projectCount === 0 ? ["Onboard an application", "Connect ownership and monitoring before alerts arrive.", () => copilot.openWorkspace("project")] as const : copilot.alertDocumentCount === 0 ? ["Review generated knowledge", "Approve evidence drafts so future RCA can reuse verified context.", () => copilot.openWorkspace("alerts")] as const : ["Review active incidents", "Continue evidence, RCA, approval, and safe resolution.", copilot.openIncidentMetadata] as const;

  return <section className="copilot-workspace">
    <header className="copilot-header"><div className="kai-assistant-title"><KAIAvatar /><div><span className="discovery-eyebrow">KaiMS AI operations assistant</span><h2>Ask KAI</h2><p>Understand incidents, find evidence gaps, and continue governed work.</p></div></div><button type="button" className={`copilot-connection ${copilot.platformReady ? "is-ready" : "is-warning"}`} onClick={copilot.refresh}><i/><span><strong>{copilot.platformReady ? "Operational context connected" : "Context needs attention"}</strong><small>Refresh platform status</small></span></button></header>
    <div className="copilot-layout"><main className="panel copilot-thread">
      <div className="copilot-thread-scroll" aria-live="polite">{!turns.length && !askMutation.isPending ? <section className="copilot-intro"><div className="copilot-mark">K</div><h3>What would you like to understand?</h3><p>I use the KaiMS records your role can access. Recommendations remain subject to normal evidence and approval controls.</p><div>{prompts.map((prompt) => <button type="button" key={prompt} onClick={() => setQuestion(prompt)}>{prompt}<span>→</span></button>)}</div></section> : turns.map((turn) => <section className="copilot-turn" key={turn.id}><div className="copilot-user-message"><small>You</small><p>{turn.question}</p></div><div className="copilot-assistant-message"><div className="copilot-mark">K</div><div><small>KaiMS</small>{turn.error ? <p className="error">{turn.error}</p> : <p>{turn.answer?.answer}</p>}{turn.answer?.links?.length ? <nav>{turn.answer.links.map((link) => <button type="button" key={link.path} onClick={() => navigate(link.path)}>{link.label} →</button>)}</nav> : null}</div></div></section>)}{askMutation.isPending ? <div className="copilot-thinking"><span/><span/><span/> Reviewing operational context…</div> : null}</div>
      <form className="copilot-composer" onSubmit={submit}><label htmlFor="copilot-question">Ask a follow-up</label><div><textarea id="copilot-question" rows={2} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about an alert, cause, evidence gap, approval, or resolution…"/><button type="submit" className="button-primary" disabled={!question.trim() || askMutation.isPending}>{askMutation.isPending ? "Working…" : "Send"}</button></div><small>AI output can be incomplete. Verify evidence before approval or execution.</small></form>
    </main><aside className="copilot-side"><article className="copilot-next"><span className="discovery-eyebrow">Recommended next</span><h3>{recommended[0]}</h3><p>{recommended[1]}</p><button type="button" className="button-primary" onClick={recommended[2]}>Continue workflow</button></article><article className="panel copilot-scope"><header><h3>Available context</h3><span className={copilot.platformReady ? "is-ready" : ""}>{copilot.platformReady ? "Live" : "Partial"}</span></header><dl><div><dt>Applications</dt><dd>{copilot.projectCount}</dd></div><div><dt>Alert documents</dt><dd>{copilot.alertDocumentCount}</dd></div>{copilot.isAdministrator ? <div><dt>Users</dt><dd>{copilot.userCount}</dd></div> : null}</dl><p>Copilot only searches records permitted for your signed-in role.</p></article><nav className="panel copilot-shortcuts"><h3>Open workspace</h3><button type="button" onClick={copilot.openIncidentMetadata}>Incident response <span>→</span></button><button type="button" onClick={() => copilot.openWorkspace("project")}>Application setup <span>→</span></button><button type="button" onClick={() => copilot.openWorkspace("alerts")}>Evidence knowledge <span>→</span></button>{copilot.isAdministrator ? <button type="button" onClick={() => copilot.openWorkspace("users")}>Access management <span>→</span></button> : null}</nav></aside></div>
  </section>;
}
