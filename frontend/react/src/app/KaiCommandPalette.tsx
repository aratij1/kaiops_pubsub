import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Command, CornerDownLeft, Search, ShieldCheck } from "lucide-react";

import { navigationForRole, searchNavigation } from "./navigation";
import "./KaiCommandPalette.css";

export type CommandResult = { id: string; label: string; detail: string; path: string; kind: "navigate" | "ask" };

const QUICK_ACTIONS = [
  { id: "find-application", label: "Find application", detail: "Open the application portfolio", path: "/applications", roles: ["admin", "administrator"] },
  { id: "find-incident", label: "Find incident", detail: "Open active incident investigation", path: "/incidents", roles: ["admin", "administrator", "hitl_reviewer", "hitl_approver"] },
  { id: "find-service", label: "Find service or resource", detail: "Search the Operational Digital Twin", path: "/cloud-ops/resources", roles: ["admin", "administrator"] },
  { id: "open-approvals", label: "Open approvals", detail: "Review governed decision packets", path: "/approvals", roles: ["admin", "administrator", "hitl_reviewer", "hitl_approver"] },
  { id: "open-integrations", label: "Go to integrations", detail: "Manage provider connections", path: "/cloud-ops/connections", roles: ["admin", "administrator"] },
  { id: "open-settings", label: "Open settings", detail: "Manage identity, policy, and platform controls", path: "/admin", roles: ["admin", "administrator"] },
] as const;

function normalizedRole(role: string) { return role.trim().toLowerCase().replaceAll(" ", "_"); }

export function buildCommandResults(query: string, role: string): CommandResult[] {
  const needle = query.trim().toLowerCase();
  const roleName = normalizedRole(role);
  const quick = QUICK_ACTIONS.filter((item) => item.roles.includes(roleName as never)).filter((item) => !needle || `${item.label} ${item.detail}`.toLowerCase().includes(needle)).map((item) => ({ ...item, kind: "navigate" as const }));
  const navigation = (needle ? searchNavigation(needle, role) : navigationForRole(role)).map((item) => ({ id: `navigate-${item.id}`, label: item.pageTitle, detail: item.description, path: item.path, kind: "navigate" as const }));
  const unique: CommandResult[] = [...quick, ...navigation].filter((item, index, rows) => rows.findIndex((candidate) => candidate.path === item.path) === index).slice(0, 8);
  if (needle) unique.push({ id: "ask-kai", label: `Ask Kai: “${query.trim()}”`, detail: "Use role-authorized operational context. No action will execute from chat.", path: `/copilot?query=${encodeURIComponent(query.trim())}`, kind: "ask" });
  return unique;
}

export default function KaiCommandPalette({ role, onNavigate }: { role: string; onNavigate: (path: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const results = useMemo(() => buildCommandResults(query, role), [query, role]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setOpen((current) => !current); }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);
  useEffect(() => { if (open) { setActiveIndex(0); window.setTimeout(() => inputRef.current?.focus(), 0); } else setQuery(""); }, [open]);
  useEffect(() => { setActiveIndex(0); }, [query]);

  function choose(result: CommandResult) { setOpen(false); onNavigate(result.path); }

  return <>
    <button type="button" className="command-palette-trigger button-secondary" onClick={() => setOpen(true)} aria-haspopup="dialog"><Search size={15} /><span>Find or ask Kai</span><kbd>Ctrl K</kbd></button>
    {open ? <div className="command-palette-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <section className="command-palette" role="dialog" aria-modal="true" aria-labelledby="command-palette-title">
        <header><Command size={19} /><div><h2 id="command-palette-title">Kai Command</h2><p>Navigate, find operational context, or ask a governed question.</p></div><kbd>Esc</kbd></header>
        <label className="command-palette-search"><Search size={19} /><span className="sr-only">Search commands</span><input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find an application, incident, service, or ask Kai…" onKeyDown={(event) => { if (event.key === "ArrowDown") { event.preventDefault(); setActiveIndex((value) => Math.min(value + 1, results.length - 1)); } if (event.key === "ArrowUp") { event.preventDefault(); setActiveIndex((value) => Math.max(value - 1, 0)); } if (event.key === "Enter" && results[activeIndex]) { event.preventDefault(); choose(results[activeIndex]); } }} /></label>
        <div className="command-palette-results" role="listbox" aria-label="Commands">{results.map((result, index) => <button type="button" role="option" aria-selected={index === activeIndex} className={index === activeIndex ? "active" : ""} key={result.id} onMouseEnter={() => setActiveIndex(index)} onClick={() => choose(result)}><span className={`command-result-icon ${result.kind}`} aria-hidden="true">{result.kind === "ask" ? <Bot size={18} /> : <CornerDownLeft size={18} />}</span><span><strong>{result.label}</strong><small>{result.detail}</small></span><kbd>↵</kbd></button>)}{!results.length ? <div className="command-palette-empty">No permitted destination matches. Ask Kai by entering a question.</div> : null}</div>
        <footer><span><ShieldCheck size={14} /> Results follow your signed-in role</span><span>↑↓ select · Enter open</span></footer>
      </section>
    </div> : null}
  </>;
}
