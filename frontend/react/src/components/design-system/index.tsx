import {
  Button,
  Dialog,
  DialogTrigger,
  Heading,
  Modal,
  ModalOverlay,
  Tab,
  TabList,
  TabPanel,
  Tabs,
} from "react-aria-components";
import { useVirtualizer } from "@tanstack/react-virtual";
import { AlertTriangle, CheckCircle2, Clock3, Info, XCircle } from "lucide-react";
import {
  type ReactNode,
  useRef,
} from "react";

import "./design-system.css";

export type StatusTone = "critical" | "warning" | "success" | "info" | "inactive";

const STATUS_ICONS = {
  critical: XCircle,
  warning: AlertTriangle,
  success: CheckCircle2,
  info: Info,
  inactive: Clock3,
} as const;

export function StatusBadge({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  const Icon = STATUS_ICONS[tone];
  return <span className={`k-status-badge is-${tone}`}><Icon size={14} aria-hidden="true" />{children}</span>;
}

export function EnvironmentBadge({ environment }: { environment: string }) {
  const normalized = environment.trim().toLowerCase() || "unknown";
  const tone: StatusTone = normalized === "prod" || normalized === "production" ? "critical" : normalized === "unknown" ? "inactive" : "info";
  return <StatusBadge tone={tone}>{environment || "Unknown environment"}</StatusBadge>;
}

export interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  metadata?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, actions, metadata }: PageHeaderProps) {
  return (
    <header className="k-page-header">
      <div>
        {eyebrow ? <p className="k-page-eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {description ? <p className="k-page-description">{description}</p> : null}
        {metadata ? <div className="k-page-metadata">{metadata}</div> : null}
      </div>
      {actions ? <div className="k-page-actions">{actions}</div> : null}
    </header>
  );
}

export function StickyActionHeader({ children, actions }: { children: ReactNode; actions: ReactNode }) {
  return <div className="k-sticky-action-header"><div>{children}</div><div className="k-page-actions">{actions}</div></div>;
}

export interface SectionItem {
  id: string;
  label: string;
  content: ReactNode;
  badge?: ReactNode;
}

export function SectionNavigation({ items, selectedKey, onSelectionChange, label = "Page sections" }: {
  items: readonly SectionItem[];
  selectedKey?: string | number;
  onSelectionChange?: (key: string | number) => void;
  label?: string;
}) {
  return (
    <Tabs className="k-section-tabs" selectedKey={selectedKey} onSelectionChange={onSelectionChange}>
      <TabList aria-label={label} className="k-section-tab-list">
        {items.map((item) => <Tab id={item.id} key={item.id} className="k-section-tab">{item.label}{item.badge}</Tab>)}
      </TabList>
      {items.map((item) => <TabPanel id={item.id} key={item.id} className="k-section-panel">{item.content}</TabPanel>)}
    </Tabs>
  );
}

export function FilterBar({ label = "Filters", children, actions }: { label?: string; children: ReactNode; actions?: ReactNode }) {
  return <section className="k-filter-bar" aria-label={label}><div className="k-filter-fields">{children}</div>{actions ? <div className="k-filter-actions">{actions}</div> : null}</section>;
}

export function MasterDetailLayout({ master, detail, detailLabel = "Selected record details" }: { master: ReactNode; detail: ReactNode; detailLabel?: string }) {
  return <div className="k-master-detail"><section className="k-master-pane">{master}</section><aside className="k-detail-pane" aria-label={detailLabel}>{detail}</aside></div>;
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <div className="k-state k-empty-state"><Info aria-hidden="true" /><strong>{title}</strong>{description ? <p>{description}</p> : null}{action}</div>;
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return <div className="k-state k-loading-state" role="status" aria-live="polite"><span className="k-spinner" aria-hidden="true" /><span>{label}</span></div>;
}

export function ErrorState({ title = "Unable to load data", description, retry }: { title?: string; description?: string; retry?: () => void }) {
  return <div className="k-state k-error-state" role="alert"><AlertTriangle aria-hidden="true" /><strong>{title}</strong>{description ? <p>{description}</p> : null}{retry ? <Button className="k-button is-secondary" onPress={retry}>Retry</Button> : null}</div>;
}

export function StaleDataNotice({ updatedAt, refresh }: { updatedAt: Date | string; refresh?: () => void }) {
  const timestamp = updatedAt instanceof Date ? updatedAt : new Date(updatedAt);
  const display = `${timestamp.toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST`;
  return <div className="k-stale-notice" role="status"><Clock3 size={16} aria-hidden="true" /><span>Showing cached data from <time dateTime={timestamp.toISOString()}>{display}</time>.</span>{refresh ? <Button className="k-button is-link" onPress={refresh}>Refresh</Button> : null}</div>;
}

export function TechnicalDetails({ summary = "Technical details", children }: { summary?: string; children: ReactNode }) {
  return <details className="k-technical-details"><summary>{summary}</summary><div>{children}</div></details>;
}

export function EvidenceSource({ source, timestamp, freshness, children }: { source: string; timestamp?: string; freshness?: "cached" | "fresh" | "stale"; children?: ReactNode }) {
  const display = timestamp ? `${new Date(timestamp).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST` : "";
  return <article className="k-evidence-source"><div><strong>{source}</strong>{freshness ? <StatusBadge tone={freshness === "fresh" ? "success" : freshness === "cached" ? "info" : "warning"}>{freshness}</StatusBadge> : null}</div>{timestamp ? <time dateTime={timestamp}>{display}</time> : null}{children}</article>;
}

export function ConfidenceExplanation({ score, reasons = [] }: { score: number; reasons?: readonly string[] }) {
  const safeScore = Math.max(0, Math.min(score, 1));
  const tone: StatusTone = safeScore >= 0.8 ? "success" : safeScore >= 0.6 ? "warning" : "critical";
  return <section className="k-confidence" aria-label={`Confidence ${Math.round(safeScore * 100)} percent`}><StatusBadge tone={tone}>{Math.round(safeScore * 100)}% confidence</StatusBadge>{reasons.length ? <ul>{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p>No confidence reasons were provided.</p>}</section>;
}

export function PermissionGuard({ allowed, children, fallback = null }: { allowed: boolean; children: ReactNode; fallback?: ReactNode }) {
  return allowed ? children : fallback;
}

export function ConfirmationDialog({ trigger, title, description, confirmLabel = "Confirm", cancelLabel = "Cancel", destructive = false, onConfirm }: {
  trigger: ReactNode;
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
}) {
  return (
    <DialogTrigger>
      {trigger}
      <ModalOverlay className="k-modal-overlay" isDismissable>
        <Modal className="k-modal">
          <Dialog className="k-dialog" role="alertdialog">
            {({ close }) => <><Heading slot="title">{title}</Heading><div className="k-dialog-description">{description}</div><div className="k-dialog-actions"><Button className="k-button is-secondary" onPress={close}>{cancelLabel}</Button><Button className={`k-button ${destructive ? "is-danger" : "is-primary"}`} onPress={() => { onConfirm(); close(); }}>{confirmLabel}</Button></div></>}
          </Dialog>
        </Modal>
      </ModalOverlay>
    </DialogTrigger>
  );
}

export interface DataTableColumn<Row> {
  id: string;
  header: string;
  cell: (row: Row) => ReactNode;
}

export function DataTable<Row>({ rows, columns, rowKey, caption }: { rows: readonly Row[]; columns: readonly DataTableColumn<Row>[]; rowKey: (row: Row) => string; caption: string }) {
  return <div className="k-table-wrap"><table className="k-data-table"><caption>{caption}</caption><thead><tr>{columns.map((column) => <th key={column.id} scope="col">{column.header}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={rowKey(row)}>{columns.map((column) => <td key={column.id}>{column.cell(row)}</td>)}</tr>)}</tbody></table></div>;
}

export function VirtualizedList<Row>({ rows, rowKey, renderRow, height = 360, estimateSize = 44, label }: { rows: readonly Row[]; rowKey: (row: Row) => string; renderRow: (row: Row) => ReactNode; height?: number; estimateSize?: number; label: string }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({ count: rows.length, getScrollElement: () => parentRef.current, estimateSize: () => estimateSize, getItemKey: (index) => rowKey(rows[index]) });
  return <div ref={parentRef} className="k-virtual-list" style={{ height }} role="list" aria-label={label}><div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>{virtualizer.getVirtualItems().map((item) => <div role="listitem" key={item.key} style={{ position: "absolute", insetInline: 0, transform: `translateY(${item.start}px)`, height: item.size }}>{renderRow(rows[item.index])}</div>)}</div></div>;
}

export type SemanticState = "critical" | "warning" | "success" | "info" | "inactive";

export function KaiState({ state, detail }: { state: string; detail?: string }) {
  return <span className="k-semantic-state k-kai-state"><span className="k-live-dot" aria-hidden="true" /><span><small>Kai</small><strong>{state}</strong>{detail ? <em>{detail}</em> : null}</span></span>;
}

export function IncidentState({ state, tone = "info" }: { state: string; tone?: SemanticState }) {
  return <StatusBadge tone={tone}>{state.replaceAll("_", " ")}</StatusBadge>;
}

export function AutonomyBadge({ mode }: { mode: string }) {
  const normalized = mode.toLowerCase();
  const tone: StatusTone = normalized.includes("emergency") ? "critical" : normalized.includes("autonomous") ? "success" : normalized.includes("guided") ? "info" : "inactive";
  return <StatusBadge tone={tone}>Autonomy: {mode || "Unavailable"}</StatusBadge>;
}

export function TrustIndicator({ label, status, detail }: { label: string; status: string; detail?: string }) {
  return <span className="k-trust-indicator"><CheckCircle2 aria-hidden="true" /><span><small>{label}</small><strong>{status}</strong>{detail ? <em>{detail}</em> : null}</span></span>;
}

export function ConfidenceIndicator({ score, reasons = [] }: { score?: number | null; reasons?: readonly string[] }) {
  if (score === null || score === undefined) return <StatusBadge tone="inactive">Confidence unavailable</StatusBadge>;
  const normalized = Math.max(0, Math.min(100, score <= 1 ? score * 100 : score));
  return <div className="k-confidence-indicator"><span><small>{normalized >= 80 ? "High" : normalized >= 60 ? "Medium" : "Low"} confidence</small><strong>{Math.round(normalized)}%</strong></span><meter min="0" max="100" value={normalized}>{normalized}%</meter>{reasons.length ? <details><summary>Why this confidence?</summary><ul>{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></details> : null}</div>;
}

export function RiskIndicator({ risk }: { risk: string }) {
  const normalized = risk.toLowerCase();
  return <StatusBadge tone={normalized.includes("high") || normalized.includes("critical") ? "critical" : normalized.includes("medium") ? "warning" : normalized.includes("low") ? "success" : "inactive"}>Risk: {risk || "Unavailable"}</StatusBadge>;
}

export function BlastRadiusIndicator({ value }: { value?: string }) {
  return <span className="k-fact-indicator"><small>Blast radius</small><strong>{value || "Not provided"}</strong></span>;
}

export function EvidenceBadge({ provenance }: { provenance: "LIVE" | "RECENT" | "HISTORICAL" | "INFERRED" | "SIMULATED" | "UNAVAILABLE" }) {
  return <span className={`k-evidence-badge is-${provenance.toLowerCase()}`}>{provenance}</span>;
}

export function FreshnessBadge({ timestamp }: { timestamp?: string }) {
  if (!timestamp) return <EvidenceBadge provenance="UNAVAILABLE" />;
  const age = Date.now() - new Date(timestamp).getTime();
  return <EvidenceBadge provenance={Number.isFinite(age) && age < 300_000 ? "LIVE" : "RECENT"} />;
}

export function RecoveryIndicator({ recovered, label }: { recovered: boolean; label?: string }) {
  return <StatusBadge tone={recovered ? "success" : "warning"}>{label || (recovered ? "Recovery verified" : "Recovery not verified")}</StatusBadge>;
}

export function LifecycleStepper({ stages, current }: { stages: readonly string[]; current: number }) {
  return <ol className="k-lifecycle-stepper" aria-label="Lifecycle progress">{stages.map((stage, index) => <li key={stage} className={index < current ? "is-complete" : index === current ? "is-current" : ""}><span>{index < current ? "✓" : index + 1}</span><strong>{stage}</strong></li>)}</ol>;
}

export function CausalPath({ nodes }: { nodes: readonly { label: string; kind?: string }[] }) {
  return <ol className="k-causal-path" aria-label="Causal path">{nodes.map((node) => <li key={`${node.kind}-${node.label}`}><small>{node.kind || "Evidence"}</small><strong>{node.label}</strong></li>)}</ol>;
}

export function ResolutionCard({ title, rationale, facts, actions }: { title: string; rationale?: string; facts?: readonly { label: string; value: ReactNode }[]; actions?: ReactNode }) {
  return <article className="k-resolution-card"><header><p>Recommended resolution</p><h3>{title}</h3></header>{rationale ? <p>{rationale}</p> : null}{facts?.length ? <dl>{facts.map((fact) => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}</dl> : null}{actions ? <footer>{actions}</footer> : null}</article>;
}

export function SafetyEnvelope({ controls }: { controls: readonly { label: string; value?: ReactNode }[] }) {
  return <section className="k-safety-envelope"><header><StatusBadge tone="info">Execution safety envelope</StatusBadge><small>Backend policy is authoritative</small></header><dl>{controls.map((control) => <div key={control.label}><dt>{control.label}</dt><dd>{control.value || "Not provided"}</dd></div>)}</dl></section>;
}

export function ApprovalCard({ title, reason, children, actions }: { title: string; reason?: string; children?: ReactNode; actions?: ReactNode }) {
  return <article className="k-approval-card"><header><FileCheckIcon /><span><small>Kai needs your decision</small><strong>{title}</strong></span></header>{reason ? <p>{reason}</p> : null}{children}{actions ? <footer>{actions}</footer> : null}</article>;
}

function FileCheckIcon() {
  return <CheckCircle2 aria-hidden="true" />;
}

export function ExecutionTimeline({ events }: { events: readonly { time?: string; title: string; detail?: string; state?: string }[] }) {
  return <ol className="k-execution-timeline">{events.map((event, index) => <li key={`${event.title}-${index}`}><time>{event.time || "Time unavailable"}</time><span><strong>{event.title}</strong>{event.detail ? <small>{event.detail}</small> : null}</span>{event.state ? <em>{event.state}</em> : null}</li>)}</ol>;
}

export function ValidationComparison({ rows }: { rows: readonly { signal: string; before?: ReactNode; after?: ReactNode; target?: ReactNode }[] }) {
  return <div className="k-validation-comparison" role="table" aria-label="Recovery validation"><div role="row"><strong>Signal</strong><strong>Before</strong><strong>After</strong><strong>Target</strong></div>{rows.map((row) => <div role="row" key={row.signal}><span>{row.signal}</span><span>{row.before || "Unavailable"}</span><span>{row.after || "Unavailable"}</span><span>{row.target || "Unavailable"}</span></div>)}</div>;
}

export function AttentionCard({ title, count, tone = "info", children, action }: { title: string; count?: number; tone?: SemanticState; children?: ReactNode; action?: ReactNode }) {
  return <article className={`k-attention-card is-${tone}`}><header><strong>{title}</strong>{count !== undefined ? <span>{count}</span> : null}</header>{children}{action ? <footer>{action}</footer> : null}</article>;
}

export function ServiceHealth({ service, status, detail }: { service: string; status: string; detail?: string }) {
  const healthy = ["healthy", "available", "up", "ok"].includes(status.toLowerCase());
  return <span className="k-service-health"><span className={healthy ? "is-healthy" : "is-unhealthy"} aria-hidden="true" /><span><strong>{service}</strong><small>{status}{detail ? ` · ${detail}` : ""}</small></span></span>;
}

export function ReadinessScore({ score, capabilities = [] }: { score?: number | null; capabilities?: readonly { label: string; score?: number | null }[] }) {
  return <section className="k-readiness"><header><span><small>Operational readiness</small><strong>{score === null || score === undefined ? "Unavailable" : `${Math.round(score)}%`}</strong></span>{score !== null && score !== undefined ? <meter min="0" max="100" value={score}>{score}%</meter> : null}</header>{capabilities.length ? <ul>{capabilities.map((capability) => <li key={capability.label}><span>{capability.label}</span><strong>{capability.score === null || capability.score === undefined ? "—" : `${Math.round(capability.score)}%`}</strong></li>)}</ul> : null}</section>;
}
