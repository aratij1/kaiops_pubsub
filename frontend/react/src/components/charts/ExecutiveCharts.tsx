import type { ChartItem } from "../../app/routeRuntime";

const number = (value: unknown) => Number.isFinite(Number(value)) ? Number(value) : 0;

export function HorizontalBarChart({ title, subtitle, items }: { title: string; subtitle?: string; items: readonly ChartItem[] }) {
  const rows = Array.isArray(items) ? items : [];
  const maxValue = rows.reduce((best, item) => Math.max(best, number(item?.value)), 0);
  return <article className="panel executive-chart-card"><div className="panel-head"><h3>{title}</h3></div>{subtitle ? <p className="subtitle">{subtitle}</p> : null}<div className="executive-bars">
    {rows.map((item, index) => { const value = number(item.value); const width = maxValue > 0 && value > 0 ? Math.max(4, (value / maxValue) * 100) : 0; return <div className="executive-bar-row" key={`${item.label}-${index}`}><span>{item.label || "-"}</span><strong>{item.displayValue ?? String(value)}</strong><div className="executive-bar-track"><div className={`executive-bar-fill tone-${String(item.tone || "ops")}`} style={{ width: `${width}%` }} /></div></div>; })}
    {!rows.length ? <p className="subtitle">No chart data available.</p> : null}
  </div></article>;
}

export function SuccessFailureDonut({ success, failure }: { success: number; failure: number }) {
  const safeSuccess = Math.max(0, number(success));
  const safeFailure = Math.max(0, number(failure));
  const total = safeSuccess + safeFailure;
  const successPercent = total > 0 ? (safeSuccess / total) * 100 : 0;
  return <article className="panel executive-chart-card"><div className="panel-head"><h3>Success vs Failure</h3></div><div className="executive-donut-wrap"><div className="executive-donut" style={{ background: `conic-gradient(var(--ok) 0 ${successPercent}%, var(--danger) ${successPercent}% 100%)` }}><div className="executive-donut-core"><strong>{total}</strong><span>Requests</span></div></div><div className="executive-donut-legend"><div><span className="legend-dot legend-ok" />Success: {safeSuccess}</div><div><span className="legend-dot legend-danger" />Failure: {safeFailure}</div></div></div></article>;
}
