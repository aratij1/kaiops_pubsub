import { MONITORING_TOOL_OPTIONS } from "./onboardingConfig";

export function normalizeRoleName(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_");
}

export function simplifyMonitoringUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`;
  return withScheme.replace(/\/+$/, "");
}

export function normalizeMatchToken(value) {
  return String(value || "").trim().toLowerCase();
}

export function severityOverrideKey(name, service = "", environment = "") {
  return [normalizeMatchToken(name), normalizeMatchToken(service), normalizeMatchToken(environment)].join("|");
}

export function extractMonitoringToolAndUrl(source, fallbackTool = "prometheus", fallbackUrl = "") {
  const payload = source && typeof source === "object" ? source : {};
  const provider = String(payload.selected_provider || payload.provider || fallbackTool || "prometheus").trim().toLowerCase();
  const tool = MONITORING_TOOL_OPTIONS.includes(provider) ? provider : fallbackTool;
  const urlsByTool = {
    prometheus: simplifyMonitoringUrl(payload.prometheus_url),
    new_relic: simplifyMonitoringUrl(payload.new_relic_url),
    datadog: simplifyMonitoringUrl(payload.datadog_url),
  };
  const url = urlsByTool[tool] || urlsByTool.prometheus || urlsByTool.new_relic || urlsByTool.datadog || simplifyMonitoringUrl(fallbackUrl);
  return { tool, url };
}

export function looksLikeUuid(value) {
  const token = String(value || "").trim();
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(token);
}

export function deriveMonitoringRequirementsFromDocument(name, text) {
  const docName = String(name || "uploaded-document").trim() || "uploaded-document";
  const docText = String(text || "").trim();
  if (!docText) {
    return [];
  }
  const lines = docText
    .split(/\r?\n/)
    .map((line) => line.replace(/^[-*#]+\s*/, "").trim())
    .filter((line) => line.length >= 8);
  const scored = lines.filter((line) => /(alert|latency|error|cpu|memory|availability|throughput|slo|sla|queue|topic|dependency|restart|health|5xx|threshold|response)/i.test(line));
  const selected = (scored.length ? scored : lines).slice(0, 6);
  return selected.map((line) => `${docName}: ${line}`);
}

export function summarizeUploadedDocument(text) {
  const compact = String(text || "").replace(/\s+/g, " ").trim();
  return compact ? compact.slice(0, 220) : "";
}

export function classifyOnboardingDocumentType(name, text) {
  const token = `${String(name || "")} ${String(text || "")}`.toLowerCase();
  if (/(ticket|incident|case|jira)/i.test(token)) {
    return "ticket";
  }
  if (/(troubleshoot|diagnostic|investigat|playbook)/i.test(token)) {
    return "troubleshooting";
  }
  if (/(rca|postmortem|root cause)/i.test(token)) {
    return "rca";
  }
  if (/(resolution|resolve|fix|remediation)/i.test(token)) {
    return "resolution";
  }
  if (/(log|trace|stdout|stderr)/i.test(token)) {
    return "logs";
  }
  return "other";
}

export function extractOnboardingProjectName(row) {
  if (!row || typeof row !== "object") {
    return "";
  }
  const projectPayload = row.project_payload && typeof row.project_payload === "object" ? row.project_payload : {};
  return String(row.project_name || projectPayload.name || "").trim();
}
