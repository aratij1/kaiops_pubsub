type AlertLike = Record<string, any>;

export function normalizeAlertChannel(value: unknown): "prometheus" | "telemetry" | "email" | "ticket" | "log" {
  const row = value && typeof value === "object" ? value as AlertLike : {};
  const labels = row.labels && typeof row.labels === "object" ? row.labels as AlertLike : {};
  const metadata = row.metadata && typeof row.metadata === "object" ? row.metadata as AlertLike : {};
  const project = String(row.project_name || row.application || labels.project_name || labels.application || "").toLowerCase();
  const source = [row.source, row.provider, row.source_type, row.origin_system, row.ingestion_channel, row.channel, metadata.source, metadata.origin_system, metadata.ingestion_channel, labels.source, labels.origin_system, labels.ingestion_channel, labels.job]
    .map((item) => String(item || "").toLowerCase()).join(" ");
  if (project === "telemetry" || project === "astronomy-shop" || /opentelemetry|telemetry/.test(source)) return "telemetry";
  if (/email|mailbox|smtp/.test(source)) return "email";
  if (/jira|ticket|itsm|servicenow|closed-incidents/.test(source)) return "ticket";
  if (/opensearch|elastic|\blog\b/.test(source)) return "log";
  return "prometheus";
}
