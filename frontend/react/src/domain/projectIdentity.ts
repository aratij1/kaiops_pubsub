export interface ProjectAlertLike {
  application?: unknown;
  project_name?: unknown;
  project?: unknown;
  service?: unknown;
  source?: unknown;
  name?: unknown;
  alert_name?: unknown;
  labels?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  annotations?: Record<string, unknown> | null;
}

const value = (input: unknown) => String(input || "").trim();
const usable = (input: unknown) => {
  const candidate = value(input);
  return candidate && candidate.toLowerCase() !== "unknown" ? candidate : "";
};

export function projectIdentityFromAlert(row: ProjectAlertLike | null | undefined): string {
  const labels = row?.labels && typeof row.labels === "object" ? row.labels : {};
  const metadata = row?.metadata && typeof row.metadata === "object" ? row.metadata : {};
  const direct = [
    row?.application, row?.project_name, row?.project,
    labels.application, labels.project_name, labels.project,
    metadata.application, metadata.project_name, metadata.project,
  ].map(usable).find(Boolean);
  if (direct) return direct;

  const contextText = value(row?.annotations?.kaiops_context);
  if (contextText) {
    try {
      const context = JSON.parse(contextText) as Record<string, unknown>;
      const embedded = usable(context.application || context.project_name || context.project);
      if (embedded) return embedded;
    } catch {
      // Optional malformed context must not hide other usable identity fields.
    }
  }

  if (value(row?.source).toLowerCase() === "jira") {
    const prefix = value(row?.name || row?.alert_name).split(":", 1)[0].trim();
    if (prefix && !prefix.includes(" ")) return prefix;
  }

  const service = usable(row?.service || labels.service);
  return ["", "unknown", "jira-tickets"].includes(service.toLowerCase()) ? "" : service;
}
