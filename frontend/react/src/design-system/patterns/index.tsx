import type { ReactNode } from "react";
import { Card, ConfidenceMeter, RiskBadge, StatusBadge } from "../components";

export function IncidentHeader({ id, title, severity, children }: { id: string; title: string; severity: "low" | "medium" | "high" | "critical"; children?: ReactNode }) {
  return <header className="kai-incident-header"><div><code>{id}</code><h1>{title}</h1></div><RiskBadge risk={severity} />{children}</header>;
}

export function KaiInsight({ title, confidence, children }: { title: string; confidence: number; children: ReactNode }) {
  return <Card className="kai-insight"><span>Kai Insight</span><h3>{title}</h3>{children}<ConfidenceMeter value={confidence} /></Card>;
}

export function EvidenceCard({ source, children }: { source: string; children: ReactNode }) {
  return <Card><StatusBadge tone="info">Kai Evidence</StatusBadge><h3>{source}</h3>{children}</Card>;
}

export function ApprovalDecision({ state, children }: { state: "pending" | "approved" | "rejected"; children: ReactNode }) {
  const tone = state === "approved" ? "success" : state === "rejected" ? "critical" : "warning";
  return <Card><StatusBadge tone={tone}>{state}</StatusBadge>{children}</Card>;
}

export function ExecutionTimelinePattern({ children }: { children: ReactNode }) { return <ol className="kai-timeline">{children}</ol>; }
export function InvestigationStory({ children }: { children: ReactNode }) { return <section className="kai-investigation-story">{children}</section>; }
export function EvidenceGraph({ children }: { children: ReactNode }) { return <section className="kai-evidence-graph" aria-label="Evidence graph">{children}</section>; }
export function ResourceExplorer({ children }: { children: ReactNode }) { return <section className="kai-resource-explorer">{children}</section>; }
