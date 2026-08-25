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
