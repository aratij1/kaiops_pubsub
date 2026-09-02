export function parseUtcTimestamp(value: unknown): Date | null {
  const raw = String(value || "").trim();
  if (!raw) return null;
  const parsed = new Date(/Z$|[+-]\d\d:\d\d$/.test(raw) ? raw : `${raw}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatIstTimestamp(value: unknown): string {
  const parsed = parseUtcTimestamp(value);
  if (!parsed) return "-";
  return `${new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(parsed)} IST`;
}

export const formatUtcTimestamp = formatIstTimestamp;

export function formatQualityPercent(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  return `${Math.round(Math.min(Math.max(numeric, 0), 1) * 100)}%`;
}

export function qualityToneFromScore(value: unknown, inverse = false): "success" | "warning" | "error" {
  const numeric = Number(value);
  const score = Number.isFinite(numeric) ? Math.min(Math.max(numeric, 0), 1) : inverse ? 1 : 0;
  const effective = inverse ? 1 - score : score;
  return effective >= 0.82 ? "success" : effective >= 0.62 ? "warning" : "error";
}

export function compactText(value: unknown, maxLength = 180): string {
  const text = String(value || "").trim();
  return text.length > maxLength ? `${text.slice(0, Math.max(24, maxLength - 1))}...` : text;
}

export function sourceChannelLabel(value: unknown): string {
  const labels: Record<string, string> = { prometheus: "Prometheus", email: "Email", ticket: "Ticket", telemetry: "Telemetry / Prometheus", log: "Logs / OpenSearch", other: "Other" };
  const key = String(value || "").trim().toLowerCase();
  return labels[key] || key || "Unknown";
}

export function statusPillClass(value: unknown): string {
  const token = String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (!token) return "status-open";
  if (token.includes("approved")) return "status-approved";
  if (token.includes("rejected")) return "status-rejected";
  if (token.includes("closed") || token.includes("resolved")) return "status-closed";
  if (["failed", "error", "blocked", "denied"].some((state) => token.includes(state))) return "status-failed";
  return `status-${token.replace(/[^a-z0-9]+/g, "_")}`;
}
