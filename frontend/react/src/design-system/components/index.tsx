import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { Search as SearchIcon } from "lucide-react";

export * from "../../components/design-system";

export function Button({ className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`k-button is-primary ${className}`.trim()} {...props} />;
}

export function IconButton({ label, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode }) {
  return <button className="kai-icon-button" aria-label={label} {...props}>{children}</button>;
}

export function Badge({ children, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return <span className="kai-badge" {...props}>{children}</span>;
}

export function Card({ children, className = "", ...props }: HTMLAttributes<HTMLElement>) {
  return <article className={`kai-card ${className}`.trim()} {...props}>{children}</article>;
}

export function Panel({ children, className = "", ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={`kai-panel ${className}`.trim()} {...props}>{children}</section>;
}

export function Metric({ label, value }: { label: string; value: ReactNode }) {
  return <div className="kai-metric"><span>{label}</span><strong>{value}</strong></div>;
}

export function RiskBadge({ risk }: { risk: "low" | "medium" | "high" | "critical" }) {
  return <Badge data-risk={risk}>{risk} risk</Badge>;
}

export function ConfidenceMeter({ value }: { value: number }) {
  const score = Math.max(0, Math.min(100, Math.round(value <= 1 ? value * 100 : value)));
  return <div className="kai-confidence" aria-label={`Kai Confidence ${score} percent`}><progress max="100" value={score} /><span>{score}%</span></div>;
}

export function Search({ label = "Search", ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  return <label className="kai-search"><SearchIcon aria-hidden="true" size={16} /><span className="sr-only">{label}</span><input type="search" aria-label={label} {...props} /></label>;
}

export function Skeleton({ label = "Loading content" }: { label?: string }) {
  return <span className="kai-skeleton" role="status" aria-label={label} />;
}

export function ReadinessScore({ value }: { value: number }) {
  return <div className="kai-readiness"><ConfidenceMeter value={value} /><strong>Readiness score</strong></div>;
}

export function Breadcrumb({ items }: { items: readonly string[] }) { return <nav aria-label="Breadcrumb"><ol className="kai-breadcrumb">{items.map((item) => <li key={item}>{item}</li>)}</ol></nav>; }
export function CommandBar({ children }: { children: ReactNode }) { return <div className="kai-command-bar" role="toolbar">{children}</div>; }
export function Drawer({ title, children }: { title: string; children: ReactNode }) { return <aside className="kai-drawer" aria-label={title}><h2>{title}</h2>{children}</aside>; }
export function Toast({ children }: { children: ReactNode }) { return <div className="kai-toast" role="status" aria-live="polite">{children}</div>; }
export function Tooltip({ text, children }: { text: string; children: ReactNode }) { return <span className="kai-tooltip" title={text}>{children}</span>; }
export function Timeline({ children }: { children: ReactNode }) { return <ol className="kai-timeline">{children}</ol>; }
export function EntityCard({ title, children }: { title: string; children?: ReactNode }) { return <Card><h3>{title}</h3>{children}</Card>; }
export function InsightCard({ title, children }: { title: string; children?: ReactNode }) { return <Card className="kai-insight"><span>Kai Insight</span><h3>{title}</h3>{children}</Card>; }
export function ApprovalCard({ title, children }: { title: string; children?: ReactNode }) { return <Card><span>Approval decision</span><h3>{title}</h3>{children}</Card>; }
