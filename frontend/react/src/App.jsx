import { useEffect, useMemo, useRef, useState } from "react";
import {
  ALERT_DOC_KIND_OPTIONS,
  APPROVAL_NAV_PRIMARY_ROLES,
  DOCUMENT_PROVIDER_ROLES,
  MONITORING_TOOL_OPTIONS,
  ONBOARDING_SOURCE_DOC_BUCKETS,
  ONBOARDING_SOURCE_DOC_EXTENSIONS,
  ONBOARDING_SOURCE_DOC_SAMPLE_FILES,
  ROLE_ALLOWED_TABS,
} from "./onboardingConfig";
import {
  classifyOnboardingDocumentType,
  deriveMonitoringRequirementsFromDocument,
  extractMonitoringToolAndUrl,
  extractOnboardingProjectName,
  looksLikeUuid,
  normalizeMatchToken,
  normalizeRoleName,
  severityOverrideKey,
  simplifyMonitoringUrl,
  summarizeUploadedDocument,
} from "./onboardingUtils";

const DEFAULT_ALERT = {
  source: "monitoring-adapter",
  name: "PaymentLatencySpike",
  service: "payments",
  severity: "high",
  description: "Payment latency crossed 2.5s threshold for 5m",
};

const SERVICE_TOPIC_FLOW = [
  { service: "monitoring-adapter", consumes: "-", publishes: "raw-alerts", agent: "alert" },
  { service: "alert-intelligence", consumes: "raw-alerts", publishes: "enriched-alerts", agent: "Alert Intelligence Agent" },
  { service: "orchestrator", consumes: "enriched-alerts", publishes: "orchestration-events", agent: "Orchestrator Agent" },
  { service: "context-agent", consumes: "orchestration-events", publishes: "context-events", agent: "Context Intelligence Agent" },
  { service: "resolution-agent", consumes: "context-events", publishes: "resolution-events", agent: "Resolution Intelligence Agent" },
  { service: "approval-service", consumes: "resolution-events", publishes: "approval-events", agent: "Human Approval Layer" },
  { service: "remediation-engine", consumes: "approval-events", publishes: "remediation-events", agent: "Remediation Automation Engine" },
  { service: "closure-service", consumes: "remediation-events", publishes: "closure-events", agent: "Closure & Validation" },
];

const AGENT_DISPLAY_ALIASES = {
  "orchestrator agent": "Master Agent",
  orchestrator: "Master Agent",
  "closure & validation": "Validator Agent",
  "closure-service": "Validator Agent",
};

const AGENT_ROUTE_ALIASES = {
  "master agent": "orchestrator agent",
  "master agent (orchestrator agent)": "orchestrator agent",
  "validator agent": "closure & validation",
  "validator agent (closure & validation)": "closure & validation",
};

const PREFERENCE_STORAGE_KEY = "kaiops.ui.preferences.v1";
const UI_THEME_VALUES = new Set(["auto", "light", "dark"]);
const TAB_SHORTCUT_MAP = {
  Digit1: "home",
  Digit2: "approval",
  Digit3: "executive",
  Digit4: "admin",
  Digit5: "trace",
  Digit6: "safety",
  Digit7: "rag",
  Digit9: "closed",
  Digit0: "summary",
};
const VALID_TABS = new Set(Object.values(TAB_SHORTCUT_MAP));
function extractObservedRoutingMetrics(workflow) {
  if (!workflow || typeof workflow !== "object") {
    return {};
  }
  const rawEvents = [workflow.events, workflow.workflow_events, workflow.agent_events]
    .find((items) => Array.isArray(items)) || [];
  const events = rawEvents.filter((item) => item && typeof item === "object");
  const traceRows = [workflow.event_trace, workflow.trace_events, workflow?.trace?.events]
    .find((items) => Array.isArray(items)) || [];
  const latestEvent = [...events].reverse().find((item) => item && typeof item === "object") || null;
  const orchestratorEvent = [...events].reverse().find((item) => {
    const agent = String(item?.agent || "").trim().toLowerCase();
    return agent.includes("orchestrator") || agent.includes("master");
  }) || latestEvent;
  const latestTrace = [...traceRows]
    .filter((row) => row && typeof row === "object")
    .sort((a, b) => {
      const aTime = parseUtcTimestamp(a.timestamp)?.getTime() || 0;
      const bTime = parseUtcTimestamp(b.timestamp)?.getTime() || 0;
      return bTime - aTime;
    })[0] || null;

  const recommendationMetadata =
    typeof workflow?.recommendation?.metadata === "object" ? workflow.recommendation.metadata : {};
  const metrics = typeof orchestratorEvent?.metrics === "object"
    ? { ...orchestratorEvent.metrics }
    : (typeof latestEvent?.metrics === "object" ? { ...latestEvent.metrics } : {});
  const decision =
    (typeof workflow?.decision === "object" && workflow.decision)
    || (typeof workflow?.orchestration_decision === "object" && workflow.orchestration_decision)
    || (typeof recommendationMetadata?.orchestration_decision === "object" && recommendationMetadata.orchestration_decision)
    || (typeof orchestratorEvent?.decision === "object" && orchestratorEvent.decision)
    || {};

  const provider =
    metrics.message_bus_provider
    || decision.message_bus_provider
    || latestTrace?.transport_provider
    || latestEvent?.input?.transport_provider
    || latestEvent?.transport_provider
    || workflow?.transport_provider
    || "";

  return {
    ...metrics,
    workflow: metrics.workflow || decision.workflow || workflow?.scenario?.id || "",
    next_action:
      metrics.next_action
      || decision.next_action
      || workflow?.next_step
      || workflow?.recommendation?.recommended_action
      || "",
    requires_approval:
      metrics.requires_approval
      ?? decision.requires_approval
      ?? workflow?.approval?.required
      ?? workflow?.recommendation?.requires_approval,
    risk_tier: metrics.risk_tier || decision.risk_tier || latestTrace?.risk_tier || "",
    execution_mode: metrics.execution_mode || decision.execution_mode || latestTrace?.execution_mode || "",
    policy_version: metrics.policy_version || decision.policy_version || workflow?.recommendation?.policy_version || "",
    message_bus_provider: provider,
  };
}

function normalizeMatchTokens(value) {
  return String(value || "")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .map((item) => item.trim())
    .filter((item) => item.length >= 3);
}

function hasTokenOverlap(left, right) {
  const leftTokens = normalizeMatchTokens(left);
  const rightTokens = normalizeMatchTokens(right);
  if (!leftTokens.length || !rightTokens.length) {
    return false;
  }
  const rightSet = new Set(rightTokens);
  return leftTokens.some((token) => rightSet.has(token));
}

const KAIOPS_CORE_SERVICE_SET = new Set([
  "api-gateway",
  "monitoring-adapter",
  "alert-intelligence",
  "orchestrator",
  "context-agent",
  "resolution-agent",
  "approval-service",
  "remediation-engine",
  "closure-service",
  "model-router",
]);

function normalizeMonitorToken(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-");
}

function isKaiopsCoreSelection(value) {
  const token = normalizeMonitorToken(value);
  return token === "kaiops-core" || token === "kaiops-core1" || token === "kaiops" || token === "core";
}

function isKaiopsCoreAlert(row) {
  const labels = typeof row?.labels === "object" && row?.labels ? row.labels : {};
  const metadata = typeof row?.metadata === "object" && row?.metadata ? row.metadata : {};
  const service = String(row?.service || labels?.service || "").trim().toLowerCase();
  const alertName = String(row?.name || labels?.alertname || "").trim().toLowerCase();
  const ownerTeam = String(metadata?.owner_team || labels?.team || "").trim().toLowerCase();
  const project = String(row?.project || row?.project_name || row?.application || labels?.project || labels?.project_name || "")
    .trim()
    .toLowerCase();

  if (KAIOPS_CORE_SERVICE_SET.has(service)) {
    return true;
  }
  if (alertName.includes("kaiops")) {
    return true;
  }
  if (ownerTeam === "platform-ops" || ownerTeam === "kaiops") {
    return true;
  }
  return project.includes("kaiops");
}

function filterAlertsForMonitor(rows, applicationToMonitor) {
  const target = String(applicationToMonitor || "").trim().toLowerCase();
  const alertRows = Array.isArray(rows) ? rows : [];
  if (!target) {
    return alertRows;
  }
  return alertRows.filter((row) => {
    if (isKaiopsCoreSelection(target)) {
      return isKaiopsCoreAlert(row);
    }
    const labels = typeof row?.labels === "object" && row?.labels ? row.labels : {};
    const metadata = typeof row?.metadata === "object" && row?.metadata ? row.metadata : {};
    const candidates = [
      row?.application,
      row?.project,
      row?.project_name,
      row?.service,
      row?.source,
      row?.name,
      metadata?.owner_team,
      labels?.application,
      labels?.project,
      labels?.project_name,
      labels?.deployment,
      labels?.namespace,
      labels?.service,
      labels?.job,
      labels?.instance,
      labels?.team,
      labels?.alertname,
    ]
      .map((value) => String(value || "").trim().toLowerCase())
      .filter(Boolean);
    return candidates.some(
      (value) =>
        value === target ||
        value.includes(target) ||
        target.includes(value) ||
        hasTokenOverlap(value, target)
    );
  });
}

function filterRowsForMonitor(rows, applicationToMonitor) {
  const target = String(applicationToMonitor || "").trim().toLowerCase();
  const items = Array.isArray(rows) ? rows : [];
  if (!target) {
    return items;
  }
  return items.filter((row) => {
    if (isKaiopsCoreSelection(target)) {
      const service = String(row?.service || "").trim().toLowerCase();
      const owner = String(row?.owner || row?.owner_team || "").trim().toLowerCase();
      return KAIOPS_CORE_SERVICE_SET.has(service) || owner === "platform-ops" || owner === "kaiops";
    }
    const labels = typeof row?.labels === "object" && row?.labels ? row.labels : {};
    const candidates = [
      row?.application,
      row?.project,
      row?.project_name,
      row?.service,
      row?.source,
      row?.provider_name,
      row?.owner,
      row?.owner_team,
      labels?.application,
      labels?.project,
      labels?.project_name,
      labels?.deployment,
      labels?.namespace,
      labels?.service,
      labels?.job,
      labels?.instance,
    ]
      .map((value) => String(value || "").trim().toLowerCase())
      .filter(Boolean);
    return candidates.some(
      (value) =>
        value === target ||
        value.includes(target) ||
        target.includes(value) ||
        hasTokenOverlap(value, target)
    );
  });
}

function isGeneratedOrTestAlert(row) {
  const tokens = [
    row?.name,
    row?.alert_name,
    row?.rule_name,
    row?.rule,
    row?.alert_rule,
    row?.labels?.alertname,
    row?.service,
    row?.application,
    row?.project_name,
    row?.project,
  ].map((value) => String(value || "").toLowerCase()).join(" ");
  return /(^|[-_\s])(e2e|ui-e2e|admin-e2e|setup-doc-e2e|stress|smoke|onboarding-smoke-test)([-_\s]|$)/i.test(tokens)
    || tokens.includes("stresspipelinealert")
    || tokens.includes("onboarding-smoke-test");
}

function onboardingSourceDocCategoryLabel(category) {
  const key = String(category || "other").trim();
  if (key === "knowledge_pack") {
    return "Service Knowledge";
  }
  return ONBOARDING_SOURCE_DOC_BUCKETS.find((bucket) => bucket.key === key)?.label || "Other Evidence";
}

async function fetchJson(path, options = {}) {
  const maxAttempts = 4;
  let lastError = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetch(path, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });

      if (!response.ok) {
        const text = await response.text();
        const shouldRetry = response.status >= 500 && attempt < maxAttempts;
        if (shouldRetry) {
          await new Promise((resolve) => setTimeout(resolve, attempt * 500));
          continue;
        }
        throw new Error(`HTTP ${response.status}: ${text || "request failed"}`);
      }

      return response.json();
    } catch (error) {
      const message = String(error?.message || "");
      lastError = message === "Failed to fetch"
        ? new Error(`Failed to reach ${path}. Open the UI through http://localhost:8501 with Docker/nginx running, or use the Vite proxy with api-gateway on http://localhost:8010.`)
        : error;
      if (attempt < maxAttempts) {
        await new Promise((resolve) => setTimeout(resolve, attempt * 500));
      }
    }
  }

  throw lastError || new Error("request failed");
}

function HealthBadge({ ok, label }) {
  return (
    <span className={`health ${ok ? "ok" : "error"}`}>
      <span className="health-dot" />
      {label}
    </span>
  );
}

function htmlEscape(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function asDisplayValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch (_error) {
      return "[object]";
    }
  }
  return String(value);
}

function parseUtcTimestamp(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return null;
  }
  const normalized = /Z$|[+-]\d\d:\d\d$/.test(raw) ? raw : `${raw}Z`;
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed;
}

function formatUtcTimestamp(value) {
  const parsed = parseUtcTimestamp(value);
  return parsed ? parsed.toISOString() : "-";
}

function clampQualityScore(value, fallback = 0) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.min(Math.max(numeric, 0), 1);
}

function formatQualityPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "-";
  }
  return `${Math.round(clampQualityScore(numeric) * 100)}%`;
}

function qualityToneFromScore(value, inverse = false) {
  const score = clampQualityScore(value, inverse ? 1 : 0);
  const effective = inverse ? 1 - score : score;
  if (effective >= 0.82) {
    return "success";
  }
  if (effective >= 0.62) {
    return "warning";
  }
  return "error";
}

function normalizeEvaluationEnvelope(source = {}, fallback = {}) {
  const raw = source && typeof source === "object" ? source : {};
  const fallbackConfidence = clampQualityScore(fallback.confidence, 0);
  const ragMatchScore = clampQualityScore(raw.rag_match_score ?? fallback.ragMatchScore, 0);
  const citationCoverage = clampQualityScore(raw.citation_coverage ?? fallback.citationCoverage, 0);
  const evidenceCoverage = clampQualityScore(raw.evidence_coverage ?? fallback.evidenceCoverage, 0);
  const groundingScore = clampQualityScore(raw.grounding_score ?? ((ragMatchScore * 0.45) + (citationCoverage * 0.25) + (evidenceCoverage * 0.3)), 0);
  const confidenceScore = clampQualityScore(raw.confidence_score ?? fallbackConfidence, fallbackConfidence);
  const hallucinationRisk = clampQualityScore(raw.hallucination_risk ?? (1 - ((groundingScore * 0.55) + (confidenceScore * 0.25) + (citationCoverage * 0.2))), 0);
  const hallucinationScore = clampQualityScore(raw.hallucination_score ?? (1 - hallucinationRisk), 0);
  const overallScore = clampQualityScore(
    raw.overall_score ?? ((confidenceScore * 0.3) + (groundingScore * 0.3) + (hallucinationScore * 0.2) + (citationCoverage * 0.1) + (evidenceCoverage * 0.1)),
    0,
  );
  return {
    contractVersion: raw.contract_version || "kaiops.evaluation.v1",
    provider: raw.provider || "ui-derived-quality-gate",
    confidenceScore,
    groundingScore,
    hallucinationRisk,
    hallucinationScore,
    citationCoverage,
    evidenceCoverage,
    ragMatchScore,
    overallScore,
    qualityLabel: raw.quality_label || (overallScore >= 0.82 ? "high" : overallScore >= 0.62 ? "medium" : "low"),
    requiresReview: Boolean(raw.requires_review ?? (hallucinationRisk >= 0.45 || groundingScore < 0.55 || confidenceScore < 0.65)),
    externalJudge: raw.external_judge && typeof raw.external_judge === "object" ? raw.external_judge : {},
    signals: raw.signals && typeof raw.signals === "object" ? raw.signals : {},
  };
}

function elapsedSeconds(start, end) {
  const startDate = parseUtcTimestamp(start);
  const endDate = parseUtcTimestamp(end);
  if (!startDate || !endDate) {
    return "-";
  }
  const delta = Math.max(0, endDate.getTime() - startDate.getTime());
  return (delta / 1000).toFixed(3);
}

function normalizeTraceServiceName(event) {
  const eventType = String(event?.event_type || "").trim().toLowerCase();
  if (eventType.includes("closure")) {
    return "closure-service";
  }
  if (eventType.includes("recommendation") || eventType.includes("resolution")) {
    return "resolution-agent";
  }
  if (eventType.includes("approval")) {
    return "approval-service";
  }
  if (eventType.includes("context")) {
    return "context-agent";
  }
  if (eventType.includes("workflow") || eventType.includes("orchestration")) {
    return "orchestrator";
  }
  if (eventType.includes("remediation")) {
    return "remediation-engine";
  }

  const rawService = String(event?.service || "").trim();
  if (!rawService) {
    return "-";
  }
  if (!looksLikeUuid(rawService)) {
    return rawService;
  }
  return "monitoring-adapter";
}

function routeForAgent(agentName) {
  const rawNeedle = String(agentName || "").trim().toLowerCase();
  const needle = AGENT_ROUTE_ALIASES[rawNeedle] || rawNeedle;
  if (!needle) {
    return null;
  }
  return (
    SERVICE_TOPIC_FLOW.find((row) => String(row?.agent || "").trim().toLowerCase() === needle) || null
  );
}

function displayAgentName(agentName) {
  const token = String(agentName || "").trim();
  if (!token) {
    return "-";
  }
  const alias = AGENT_DISPLAY_ALIASES[token.toLowerCase()];
  return alias ? `${alias} (${token})` : token;
}

function compactText(value, maxLength = 180) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  return text.length > maxLength ? `${text.slice(0, Math.max(24, maxLength - 1))}...` : text;
}

function hasMeaningfulValue(value) {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    const normalized = value.trim();
    return Boolean(normalized && normalized !== "-");
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value).length > 0;
  }
  return true;
}

function stringifyTimelineValue(value) {
  if (!hasMeaningfulValue(value)) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return String(value);
  }
}

function isFailureStatus(value) {
  const token = String(value || "").trim().toLowerCase();
  if (!token) {
    return false;
  }
  return ["fail", "failed", "failure", "error", "exception", "rejected", "timeout", "denied"].some((flag) => token.includes(flag));
}

function normalizeApprovalStatus(value) {
  return String(value || "").trim().toLowerCase();
}

function isApprovalResolvedStatus(value) {
  const token = normalizeApprovalStatus(value);
  if (!token) {
    return false;
  }
  return ["approved", "rejected", "closed", "resolved", "failed", "cancelled", "canceled"].includes(token);
}

function isApprovalPendingStatus(value) {
  const token = normalizeApprovalStatus(value);
  if (!token) {
    return false;
  }
  return ["awaiting_approval", "pending", "queued", "awaiting user approval", "standby"].includes(token);
}

function statusPillClass(value) {
  const token = normalizeApprovalStatus(value);
  if (!token) {
    return "status-open";
  }
  if (token.includes("approved")) {
    return "status-approved";
  }
  if (token.includes("rejected")) {
    return "status-rejected";
  }
  if (token.includes("closed") || token.includes("resolved")) {
    return "status-closed";
  }
  if (token.includes("failed") || token.includes("error") || token.includes("blocked") || token.includes("denied")) {
    return "status-failed";
  }
  const normalized = token.replace(/[^a-z0-9]+/g, "_");
  return normalized ? `status-${normalized}` : "status-open";
}

function extractEventError(event) {
  if (!event || typeof event !== "object") {
    return "";
  }
  const status = String(event.status || "").trim();
  const candidates = [
    event.error,
    event.errors,
    event.exception,
    event.failure,
    event.failure_reason,
    event.error_message,
    event.detail,
    event.message,
  ];
  const hit = candidates.find((item) => hasMeaningfulValue(item));
  if (hit !== undefined) {
    return stringifyTimelineValue(hit);
  }
  if (isFailureStatus(status)) {
    const reason = hasMeaningfulValue(event.policy_reason) ? stringifyTimelineValue(event.policy_reason) : "";
    return reason || `Status: ${status}`;
  }
  return "";
}

function extractEventInput(event) {
  if (!event || typeof event !== "object") {
    return null;
  }
  const payload = typeof event.payload === "object" && event.payload ? event.payload : null;
  const candidates = [
    event.input_value,
    event.input,
    event.input_payload,
    event.request,
    event.context,
    event.source_payload,
    payload?.input,
    payload?.request,
    payload?.context,
  ];
  const hit = candidates.find((item) => hasMeaningfulValue(item));
  return hit === undefined ? null : hit;
}

function extractEventOutput(event) {
  if (!event || typeof event !== "object") {
    return null;
  }
  const payload = typeof event.payload === "object" && event.payload ? event.payload : null;
  const candidates = [
    event.output_value,
    event.output,
    event.result,
    payload,
    event.response,
    event.recommendation,
    event.decision,
  ];
  const hit = candidates.find((item) => hasMeaningfulValue(item));
  if (!hasMeaningfulValue(hit)) {
    return null;
  }
  const eventType = String(event.event_type || "").trim();
  if (typeof hit === "string" && eventType && hit.trim() === eventType && hasMeaningfulValue(payload)) {
    return payload;
  }
  return hit;
}

function buildPreviewExecutionPlan(workflow) {
  const safeWorkflow = workflow && typeof workflow === "object" ? workflow : {};
  const recommendation = typeof safeWorkflow.recommendation === "object" && safeWorkflow.recommendation ? safeWorkflow.recommendation : {};
  const incident = typeof safeWorkflow.incident === "object" && safeWorkflow.incident ? safeWorkflow.incident : {};
  const alert = typeof safeWorkflow.alert === "object" && safeWorkflow.alert ? safeWorkflow.alert : {};

  const target = String(
    recommendation?.metadata?.remediation_target
    || recommendation?.target
    || incident?.service
    || alert?.service
    || "unknown-target"
  ).trim();
  const environment = String(incident?.environment || alert?.environment || "prod").trim() || "prod";
  const recommendationText = String(recommendation?.recommended_action || "rollback deployment").trim() || "rollback deployment";
  const lowered = recommendationText.toLowerCase();

  const actionType = lowered.includes("restart pod")
    ? "restart_pod"
    : lowered.includes("scale")
      ? "scale_deployment"
      : lowered.includes("restart service")
        ? "restart_service"
        : lowered.includes("cache")
          ? "clear_cache"
          : lowered.includes("failover") || lowered.includes("database")
            ? "failover_database"
            : lowered.includes("terraform")
              ? "terraform_rollback"
              : "rollback_deployment";

  const preview = {
    commands: [],
    scripts: [],
    queries: [],
  };

  if (actionType === "restart_pod") {
    preview.commands = [
      `kubectl rollout restart deployment/${target} -n ${environment}`,
      `kubectl rollout status deployment/${target} -n ${environment} --timeout=180s`,
    ];
    preview.scripts = [`scripts/remediation/restart_pod.ps1 -Service ${target} -Namespace ${environment}`];
    preview.queries = [`sum(rate(http_requests_total{service='${target}',status=~'5..'}[5m]))`];
  } else if (actionType === "scale_deployment") {
    preview.commands = [
      `kubectl scale deployment/${target} --replicas=3 -n ${environment}`,
      `kubectl rollout status deployment/${target} -n ${environment} --timeout=180s`,
    ];
    preview.scripts = [`scripts/remediation/scale_deployment.ps1 -Service ${target} -Namespace ${environment} -Replicas 3`];
    preview.queries = [`avg_over_time(container_cpu_usage_seconds_total{pod=~'${target}.*'}[10m])`];
  } else if (actionType === "restart_service") {
    preview.commands = [`ansible-playbook playbooks/restart-service.yml -e service=${target} -e env=${environment}`];
    preview.scripts = [`scripts/remediation/restart_service.ps1 -Service ${target} -Environment ${environment}`];
    preview.queries = [`max_over_time(up{job='${target}'}[5m])`];
  } else if (actionType === "clear_cache") {
    preview.commands = [`redis-cli -h ${target}-redis -n 0 FLUSHDB`];
    preview.scripts = [`scripts/remediation/clear_cache.ps1 -Service ${target}`];
    preview.queries = [`sum(rate(cache_miss_total{service='${target}'}[5m]))`];
  } else if (actionType === "failover_database") {
    preview.commands = ["mysql -e \"CALL mysql.rds_failover();\""];
    preview.scripts = ["scripts/remediation/failover_database.ps1"];
    preview.queries = ["SHOW REPLICA STATUS;"];
  } else if (actionType === "terraform_rollback") {
    preview.commands = [
      "terraform init",
      `terraform apply -auto-approve -var service=${target} -var rollback=true`,
    ];
    preview.scripts = [`scripts/remediation/terraform_rollback.ps1 -Service ${target} -Environment ${environment}`];
    preview.queries = [`sum(rate(terraform_apply_failures_total{service='${target}'}[15m]))`];
  } else {
    preview.commands = [
      `kubectl rollout undo deployment/${target} -n ${environment}`,
      `kubectl rollout status deployment/${target} -n ${environment} --timeout=180s`,
    ];
    preview.scripts = [`scripts/remediation/rollback_deployment.ps1 -Service ${target} -Namespace ${environment}`];
    preview.queries = [`sum(rate(http_requests_total{service='${target}',status=~'5..'}[5m]))`];
  }

  return {
    actionType,
    recommendationText,
    plan: preview,
  };
}

function deriveExecutionCommands(workflow, traceRows) {
  const safeWorkflow = workflow && typeof workflow === "object" ? workflow : {};
  const safeTraceRows = Array.isArray(traceRows) ? traceRows : [];
  const recommendation = typeof safeWorkflow.recommendation === "object" && safeWorkflow.recommendation ? safeWorkflow.recommendation : {};
  const recommendationMetadata = typeof recommendation.metadata === "object" && recommendation.metadata ? recommendation.metadata : {};
  const remediationAction = typeof safeWorkflow.remediation_action === "object" && safeWorkflow.remediation_action ? safeWorkflow.remediation_action : {};
  const decision =
    (typeof safeWorkflow.decision === "object" && safeWorkflow.decision)
    || (typeof safeWorkflow.orchestration_decision === "object" && safeWorkflow.orchestration_decision)
    || (typeof recommendationMetadata.orchestration_decision === "object" && recommendationMetadata.orchestration_decision)
    || {};

  const explicit =
    (Array.isArray(recommendation.commands) && recommendation.commands)
    || (Array.isArray(remediationAction.commands) && remediationAction.commands)
    || (Array.isArray(decision.commands) && decision.commands)
    || [];
  const derived = [];
  const seen = new Set();
  const pushUnique = (value, prefix = "") => {
    const token = String(value || "").trim();
    if (!token) {
      return;
    }
    const line = `${prefix}${token}`;
    const key = line.toLowerCase();
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    derived.push(line);
  };

  const pushPlan = (plan) => {
    if (!plan || typeof plan !== "object") {
      return;
    }
    (Array.isArray(plan.commands) ? plan.commands : []).forEach((item) => pushUnique(item, "cmd: "));
    (Array.isArray(plan.scripts) ? plan.scripts : []).forEach((item) => pushUnique(item, "script: "));
    (Array.isArray(plan.queries) ? plan.queries : []).forEach((item) => pushUnique(item, "query: "));
  };

  explicit.forEach((item) => pushUnique(item, "cmd: "));

  const remediationParams = typeof remediationAction.parameters === "object" && remediationAction.parameters
    ? remediationAction.parameters
    : {};
  pushPlan(remediationParams.execution_plan);
  (Array.isArray(remediationParams.commands) ? remediationParams.commands : []).forEach((item) => pushUnique(item, "cmd: "));

  safeTraceRows.forEach((row) => {
    const payload = typeof row?.payload === "object" && row.payload ? row.payload : {};
    pushPlan(payload?.execution_plan);

    const payloadAction = typeof payload?.remediation_action === "object" && payload.remediation_action ? payload.remediation_action : {};
    const payloadParams = typeof payloadAction.parameters === "object" && payloadAction.parameters ? payloadAction.parameters : {};
    pushPlan(payloadParams.execution_plan);
    (Array.isArray(payloadParams.commands) ? payloadParams.commands : []).forEach((item) => pushUnique(item, "cmd: "));

    const commands = Array.isArray(payload?.commands) ? payload.commands : [];
    commands.forEach((item) => pushUnique(item, "cmd: "));
  });

  if (!derived.length) {
    const preview = buildPreviewExecutionPlan(safeWorkflow);
    pushUnique("SIMULATED - no real command is executed, before or after approval", "cmd: ");
    pushUnique(`# recommended_action: ${preview.recommendationText}`, "cmd: ");
    (preview.plan.commands || []).forEach((item) => pushUnique(item, "cmd: "));
    (preview.plan.scripts || []).forEach((item) => pushUnique(item, "script: "));
    (preview.plan.queries || []).forEach((item) => pushUnique(item, "query: "));
  }

  return derived;
}

function firstTraceTimestamp(rows, predicate) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const hit = safeRows.find((row) => {
    if (!row || typeof row !== "object") {
      return false;
    }
    return predicate(row);
  });
  return String(hit?.timestamp || "").trim();
}

function firstEventTimestamp(rows, predicate) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const hit = safeRows.find((row) => {
    if (!row || typeof row !== "object") {
      return false;
    }
    return predicate(row);
  });
  return String(hit?.timestamp || "").trim();
}

function buildSyntheticFlowRows({ workflow, events, traceRows, ingestAt, incidentCreatedAt }) {
  const safeWorkflow = workflow && typeof workflow === "object" ? workflow : {};
  const safeEvents = Array.isArray(events) ? events : [];
  const safeTraceRows = Array.isArray(traceRows) ? traceRows : [];

  const alert = typeof safeWorkflow.alert === "object" && safeWorkflow.alert ? safeWorkflow.alert : {};
  const incident = typeof safeWorkflow.incident === "object" && safeWorkflow.incident ? safeWorkflow.incident : {};
  const context = typeof safeWorkflow.context === "object" && safeWorkflow.context ? safeWorkflow.context : {};
  const contextMetadata = typeof context.metadata === "object" && context.metadata ? context.metadata : {};
  const recommendation = typeof safeWorkflow.recommendation === "object" && safeWorkflow.recommendation ? safeWorkflow.recommendation : {};
  const recommendationMetadata = typeof recommendation.metadata === "object" && recommendation.metadata ? recommendation.metadata : {};
  const remediationAction =
    typeof safeWorkflow.remediation_action === "object" && safeWorkflow.remediation_action
      ? safeWorkflow.remediation_action
      : {};
  const decision =
    (typeof safeWorkflow.decision === "object" && safeWorkflow.decision)
    || (typeof safeWorkflow.orchestration_decision === "object" && safeWorkflow.orchestration_decision)
    || (typeof recommendationMetadata.orchestration_decision === "object" && recommendationMetadata.orchestration_decision)
    || {};

  const contextTraceRow = safeTraceRows
    .slice()
    .reverse()
    .find((row) => String(row?.event_type || "").toLowerCase().includes("context"));
  const contextEventPayload = (contextTraceRow && typeof contextTraceRow.payload === "object" && contextTraceRow.payload)
    ? contextTraceRow.payload
    : {};
  const contextEventMetadata = typeof contextEventPayload?.metadata === "object" && contextEventPayload.metadata
    ? contextEventPayload.metadata
    : {};

  const ragMatches =
    (Array.isArray(contextMetadata.rag_matches) && contextMetadata.rag_matches)
    || (Array.isArray(recommendationMetadata.rag_matches) && recommendationMetadata.rag_matches)
    || (Array.isArray(contextEventMetadata.rag_matches) && contextEventMetadata.rag_matches)
    || [];

  const ragDocumentsRaw =
    contextMetadata.rag_documents
    ?? recommendationMetadata.rag_documents
    ?? contextEventMetadata.rag_documents
    ?? contextEventPayload.rag_document_count
    ?? null;
  const ragTopSimilarityRaw =
    contextMetadata.rag_top_similarity
    ?? recommendationMetadata.rag_top_similarity
    ?? contextEventMetadata.rag_top_similarity
    ?? null;
  const ragDocuments = ragDocumentsRaw === null || ragDocumentsRaw === undefined || ragDocumentsRaw === ""
    ? null
    : Number(ragDocumentsRaw);
  const ragTopSimilarity = ragTopSimilarityRaw === null || ragTopSimilarityRaw === undefined || ragTopSimilarityRaw === ""
    ? null
    : Number(ragTopSimilarityRaw);
  const runbookFound =
    Boolean(context.runbook)
    || Boolean(recommendationMetadata.runbook_found)
    || Boolean(contextEventPayload.document_available)
    || Boolean(contextEventMetadata.document_available);
  const executionCommands = deriveExecutionCommands(safeWorkflow, safeTraceRows);
  const traceEventTypes = safeTraceRows
    .map((row) => String(row?.event_type || "").trim())
    .filter(Boolean);

  const findTraceEvents = (needles) => {
    const tokens = Array.isArray(needles) ? needles : [];
    const matches = traceEventTypes.filter((eventType) => {
      const normalized = eventType.toLowerCase();
      return tokens.some((needle) => normalized.includes(String(needle || "").toLowerCase()));
    });
    return Array.from(new Set(matches));
  };

  const landingTimestamp =
    String(ingestAt || "").trim()
    || firstTraceTimestamp(safeTraceRows, (row) => {
      const eventType = String(row?.event_type || "").toLowerCase();
      const source = String(row?.source_channel || "").toLowerCase();
      return eventType.includes("alert") || source.includes("raw-alert");
    })
    || String(incidentCreatedAt || "").trim();

  const dedupeTimestamp =
    firstEventTimestamp(safeEvents, (event) => String(event?.agent || "").toLowerCase().includes("alert intelligence"))
    || firstTraceTimestamp(safeTraceRows, (row) => String(row?.event_type || "").toLowerCase().includes("workflow"))
    || landingTimestamp;

  const contextTimestamp =
    firstEventTimestamp(safeEvents, (event) => String(event?.agent || "").toLowerCase().includes("context intelligence"))
    || firstTraceTimestamp(safeTraceRows, (row) => String(row?.event_type || "").toLowerCase().includes("context"))
    || dedupeTimestamp;

  const routingTimestamp =
    firstTraceTimestamp(safeTraceRows, (row) => {
      const eventType = String(row?.event_type || "").toLowerCase();
      return eventType.includes("workflow.selected") || eventType.includes("recommendation.generated");
    })
    || firstEventTimestamp(safeEvents, (event) => String(event?.agent || "").toLowerCase().includes("orchestrator"))
    || contextTimestamp;

  const remediationTimestamp =
    String(remediationAction.completed_at || remediationAction.started_at || "").trim()
    || firstEventTimestamp(safeEvents, (event) => String(event?.agent || "").toLowerCase().includes("remediation"))
    || firstTraceTimestamp(safeTraceRows, (row) => String(row?.event_type || "").toLowerCase().includes("remediation"))
    || routingTimestamp;

  const rows = [];
  const traceId = alert.trace_id || incident.trace_id || context.trace_id || recommendation.trace_id || remediationAction.trace_id || "";

  if (landingTimestamp || hasMeaningfulValue(alert)) {
    rows.push({
      stage: "Alert Landed In Landing Pad",
      agent: "Monitoring Adapter",
      service: "monitoring-adapter",
      consumes: "provider webhook",
      publishes: "raw-alerts",
      timestamp: landingTimestamp,
      elapsed: elapsedSeconds(ingestAt || incidentCreatedAt, landingTimestamp),
      detail: "Alert ingested from monitoring provider and staged for downstream workflow processing.",
      tables: "incident_events",
      inputValueText: stringifyTimelineValue({
        source: alert.source,
        name: alert.name,
        service: alert.service,
        severity: alert.severity,
      }),
      outputValueText: stringifyTimelineValue({
        correlation_id: alert.correlation_id,
        trace_id: traceId,
      }),
      errorValueText: "",
      backendEvents: findTraceEvents(["alert", "incident.opened", "incident.created"]),
    });
  }

  if (hasMeaningfulValue(alert.deduplicated_count) || dedupeTimestamp) {
    rows.push({
      stage: "Deduplication And Incident Correlation",
      agent: "Alert Intelligence Agent",
      service: "alert-intelligence",
      consumes: "raw-alerts",
      publishes: "enriched-alerts",
      timestamp: dedupeTimestamp,
      elapsed: elapsedSeconds(ingestAt || incidentCreatedAt, dedupeTimestamp),
      detail: "Deduplication, severity classification, and incident correlation completed.",
      tables: "alerts, incidents, incident_events",
      inputValueText: stringifyTimelineValue({
        deduplicated_count: alert.deduplicated_count,
        correlation_id: alert.correlation_id,
        incident_id: incident.id,
      }),
      outputValueText: stringifyTimelineValue({
        incident_title: incident.title,
        severity: incident.severity,
        status: incident.status,
        trace_id: traceId,
      }),
      errorValueText: "",
      backendEvents: findTraceEvents(["workflow.selected", "context.collected"]),
    });
  }

  if (ragDocuments > 0 || ragMatches.length || contextTimestamp) {
    rows.push({
      stage: "RAG Context Retrieval",
      agent: "Context Intelligence Agent",
      service: "context-agent",
      consumes: "orchestration-events",
      publishes: "context-events",
      timestamp: contextTimestamp,
      elapsed: elapsedSeconds(ingestAt || incidentCreatedAt, contextTimestamp),
      detail: "Context built from RAG corpus, dependencies, recent changes, and observability connectors.",
      tables: "incident_events, agent_work_items",
      inputValueText: stringifyTimelineValue({
        service: alert.service,
        deployment: context.deployment,
        related_incidents: Array.isArray(context.related_incidents) ? context.related_incidents.length : 0,
      }),
      outputValueText: stringifyTimelineValue({
        rag_documents: ragDocuments ?? "-",
        rag_matches: ragMatches,
        runbook_found: runbookFound,
        trace_id: traceId,
      }),
      errorValueText: "",
      backendEvents: findTraceEvents(["context.collected"]),
    });
  }

  if (ragMatches.length || (typeof ragTopSimilarity === "number" && ragTopSimilarity > 0)) {
    rows.push({
      stage: "Embedding And Semantic Search",
      agent: "VectorDB Connector",
      service: "context-agent",
      consumes: "context query",
      publishes: "ranked rag matches",
      timestamp: contextTimestamp,
      elapsed: elapsedSeconds(ingestAt || incidentCreatedAt, contextTimestamp),
      detail: "Vector similarity and metadata ranking used to retrieve the most relevant runbook, incident, and deployment documents.",
      tables: "rag corpus",
      inputValueText: stringifyTimelineValue({
        query: `${alert.service || ""} ${alert.name || ""} ${alert.description || ""}`.trim(),
        rag_document_count: ragDocuments,
      }),
      outputValueText: stringifyTimelineValue({
        rag_top_similarity: ragTopSimilarity ?? "-",
        top_matches: ragMatches.slice(0, 5),
        trace_id: traceId,
      }),
      errorValueText: "",
      backendEvents: findTraceEvents(["context.collected", "recommendation.generated"]),
    });
  }

  if (hasMeaningfulValue(decision) || routingTimestamp) {
    rows.push({
      stage: "Routing And Metadata Policy",
      agent: "Orchestrator Agent",
      service: "orchestrator",
      consumes: "enriched-alerts",
      publishes: "orchestration-events",
      timestamp: routingTimestamp,
      elapsed: elapsedSeconds(ingestAt || incidentCreatedAt, routingTimestamp),
      detail: "Workflow routing policy selected with risk tier, execution mode, and transport provider metadata.",
      tables: "incident_events, incident_projections",
      inputValueText: stringifyTimelineValue({
        workflow: decision.workflow,
        next_action: decision.next_action,
        requires_approval: decision.requires_approval,
      }),
      outputValueText: stringifyTimelineValue({
        risk_tier: decision.risk_tier,
        execution_mode: decision.execution_mode,
        policy_version: decision.policy_version,
        message_bus_provider: decision.message_bus_provider,
        trace_id: traceId,
      }),
      errorValueText: "",
      backendEvents: findTraceEvents(["workflow.selected", "recommendation.generated", "approval.recorded"]),
    });
  }

  if (executionCommands.length || hasMeaningfulValue(remediationAction.output) || remediationTimestamp) {
    const remediationParameters =
      typeof remediationAction.parameters === "object" && remediationAction.parameters
        ? remediationAction.parameters
        : {};
    const executionPlan =
      typeof remediationParameters.execution_plan === "object" && remediationParameters.execution_plan
        ? remediationParameters.execution_plan
        : {};
    const remediationExecuted = hasMeaningfulValue(remediationAction.status) || hasMeaningfulValue(remediationAction.output);
    rows.push({
      stage: "Remediation Command Execution",
      agent: "Remediation Automation Engine",
      service: "remediation-engine",
      consumes: "approval-events",
      publishes: "remediation-events",
      timestamp: remediationTimestamp,
      elapsed: elapsedSeconds(ingestAt || incidentCreatedAt, remediationTimestamp),
      detail: remediationExecuted
        ? "SIMULATED remediation completed - no real infrastructure was contacted; command/script payload and simulated status captured."
        : "SIMULATED remediation command/script/query preview generated; will remain simulated even after approval.",
      tables: "actions, audit_logs, incident_events",
      inputValueText: stringifyTimelineValue({
        mode: remediationExecuted ? "simulated_executed" : "simulated_preview",
        action_type: remediationAction.action_type,
        target: remediationAction.target,
        commands: Array.isArray(executionPlan.commands) ? executionPlan.commands : executionCommands,
        scripts: Array.isArray(executionPlan.scripts) ? executionPlan.scripts : [],
        queries: Array.isArray(executionPlan.queries) ? executionPlan.queries : [],
      }),
      outputValueText: stringifyTimelineValue({
        status: remediationAction.status || (remediationExecuted ? "-" : "pending"),
        output: remediationAction.output,
        error: remediationAction.error,
        trace_id: traceId,
      }),
      errorValueText: stringifyTimelineValue(remediationAction.error),
      backendEvents: findTraceEvents(["remediation.executed", "closure.completed"]),
    });
  }

  return rows;
}

function summarizeEventType(value) {
  const token = String(value || "").trim();
  if (!token) {
    return "Workflow Event";
  }
  return token
    .split(".")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" -> ");
}

function timelinePhaseOrder(row) {
  const stage = String(row?.stage || "").toLowerCase();
  const eventHints = Array.isArray(row?.backendEvents)
    ? row.backendEvents.map((item) => String(item || "").toLowerCase())
    : [];
  const haystack = `${stage} ${eventHints.join(" ")}`;

  if (haystack.includes("landing pad") || haystack.includes("alert received") || haystack.includes("alert landed") || haystack.includes("incident.alert")) {
    return 0;
  }
  if (haystack.includes("dedup") || haystack.includes("correlation") || haystack.includes("enrich")) {
    return 1;
  }
  if (haystack.includes("rag context") || haystack.includes("context retrieval") || haystack.includes("context intelligence") || haystack.includes("incident.context.collected")) {
    return 2;
  }
  if (haystack.includes("embedding") || haystack.includes("semantic") || haystack.includes("vector")) {
    return 3;
  }
  if (haystack.includes("routing") || haystack.includes("policy") || haystack.includes("workflow") || haystack.includes("recommendation")) {
    return 4;
  }
  if (haystack.includes("approval")) {
    return 5;
  }
  if (haystack.includes("remediation") || haystack.includes("command") || haystack.includes("execute") || haystack.includes("closure")) {
    return 6;
  }
  return 99;
}

function buildAlertDocumentDrafts(alertRow, workflowPayload) {
  const alertName = String(alertRow?.name || alertRow?.alert_name || "Alert").trim();
  const service = String(alertRow?.service || "unknown-service").trim();
  const severity = String(alertRow?.severity || "high").trim().toLowerCase();
  const alertId = String(alertRow?.alert_id || alertRow?.id || "").trim();
  const workflow = workflowPayload?.workflow || workflowPayload || {};
  const recommendation = typeof workflow?.recommendation === "object" && workflow.recommendation ? workflow.recommendation : {};
  const incident = typeof workflow?.incident === "object" && workflow.incident ? workflow.incident : {};
  const rootCause = String(recommendation?.root_cause || "").trim();
  const impact = String(recommendation?.impact || "").trim();
  const suggestedAction = String(recommendation?.recommended_action || "").trim();
  const commonHeader = `Alert ${alertName} observed on ${service} with severity ${severity.toUpperCase()}.`;
  const fallbackRootCause = "Investigate recent deploys, dependency health, and resource saturation.";
  const commonRoot = rootCause || fallbackRootCause;
  const remediationPreview = buildPreviewExecutionPlan(workflow);
  const remediationCommands = Array.isArray(remediationPreview?.plan?.commands) ? remediationPreview.plan.commands : [];
  const remediationScripts = Array.isArray(remediationPreview?.plan?.scripts) ? remediationPreview.plan.scripts : [];
  const remediationQueries = Array.isArray(remediationPreview?.plan?.queries) ? remediationPreview.plan.queries : [];
  const remediationPlanText = [
    remediationCommands.length ? `Commands:\n${remediationCommands.map((item) => `- ${item}`).join("\n")}` : "",
    remediationScripts.length ? `Scripts:\n${remediationScripts.map((item) => `- ${item}`).join("\n")}` : "",
    remediationQueries.length ? `Queries:\n${remediationQueries.map((item) => `- ${item}`).join("\n")}` : "",
  ].filter(Boolean).join("\n\n");

  return {
    incident: {
      kind: "incident",
      title: `${alertName} Incident Summary`.slice(0, 160),
      summary: [
        `${alertName} detected for ${service}.`,
        impact ? `Impact: ${impact}.` : "",
      ].filter(Boolean).join(" "),
      content: [
        commonHeader,
        `Probable root cause: ${commonRoot}`,
        incident?.id ? `Incident reference: ${String(incident.id)}.` : "",
        "Escalation path: L1 -> L2 -> L3 with timeline checkpoints at 5m, 15m, and 30m.",
      ].filter(Boolean).join("\n\n"),
      services: service,
      severity,
      alert_type: alertName,
      alert_id: alertId,
      root_cause: rootCause,
      impact,
      recommended_action: suggestedAction,
    },
    runbook: {
      kind: "runbook",
      title: `${alertName} Runbook`.slice(0, 160),
      summary: [
        `${alertName} detected for ${service}.`,
        suggestedAction ? `Recommended action: ${suggestedAction}.` : "",
      ].filter(Boolean).join(" "),
      content: [
        commonHeader,
        `Probable root cause: ${commonRoot}`,
        suggestedAction ? `Immediate action: ${suggestedAction}.` : "Immediate action: inspect logs, metrics, and dependency health.",
        "Verification: confirm error rate and latency return to baseline before closure.",
      ].filter(Boolean).join("\n\n"),
      services: service,
      severity,
      alert_type: alertName,
      alert_id: alertId,
      root_cause: rootCause,
      impact,
      recommended_action: suggestedAction,
    },
    deployment: {
      kind: "deployment",
      title: `${alertName} Deployment Guidance`.slice(0, 160),
      summary: `Deployment guardrails and rollback checks for ${service}.`,
      content: [
        commonHeader,
        "Pre-deploy checks: SLO burn rate, dependency readiness, and database migration safety.",
        "Post-deploy checks: p95 latency, error budget consumption, and alert noise monitoring for 30m.",
        "Rollback criteria: sustained critical alerts for 10m or failed synthetic checks.",
      ].join("\n\n"),
      services: service,
      severity,
      alert_type: alertName,
      alert_id: alertId,
      root_cause: rootCause,
      impact,
      recommended_action: suggestedAction,
    },
    change: {
      kind: "change",
      title: `${alertName} Change Record`.slice(0, 160),
      summary: `Change notes and approvals for ${service} remediation actions.`,
      content: [
        commonHeader,
        "Change scope: configuration, deployment, and policy updates tied to this alert pattern.",
        "Approval checklist: peer review, CAB approval (if required), and blast-radius assessment.",
        "Backout plan: revert config, redeploy previous version, and validate health endpoints.",
      ].join("\n\n"),
      services: service,
      severity,
      alert_type: alertName,
      alert_id: alertId,
      root_cause: rootCause,
      impact,
      recommended_action: suggestedAction,
    },
    dependency: {
      kind: "dependency",
      title: `${alertName} Dependency Map`.slice(0, 160),
      summary: `Dependency and upstream/downstream checks for ${service}.`,
      content: [
        commonHeader,
        "Dependencies to inspect: datastore latency, queue backlog, external API error rates, and network saturation.",
        "Signals to capture: timeout spikes, retry storms, and circuit breaker open rate.",
        "Mitigation path: isolate degraded dependency, apply traffic shaping, and monitor stabilization.",
      ].join("\n\n"),
      services: service,
      severity,
      alert_type: alertName,
      alert_id: alertId,
      root_cause: rootCause,
      impact,
      recommended_action: suggestedAction,
    },
    remediation: {
      kind: "remediation",
      title: `${alertName} Remediation Command Plan`.slice(0, 160),
      summary: `Auto-generated remediation commands/scripts/queries for ${service}.`,
      content: [
        commonHeader,
        `Recommended remediation action: ${remediationPreview.recommendationText || suggestedAction || "Rollback deployment"}.`,
        `Probable root cause: ${commonRoot}`,
        remediationPlanText || "No remediation command plan was generated.",
      ].filter(Boolean).join("\n\n"),
      services: service,
      severity,
      alert_type: alertName,
      alert_id: alertId,
      root_cause: rootCause,
      impact,
      recommended_action: remediationPreview.recommendationText || suggestedAction,
      execution_plan: remediationPlanText,
      commands: remediationCommands,
      scripts: remediationScripts,
      queries: remediationQueries,
    },
  };
}

function toFiniteNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function percentile(values, fraction) {
  const nums = (Array.isArray(values) ? values : [])
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value))
    .sort((a, b) => a - b);
  if (!nums.length) {
    return 0;
  }
  const index = Math.min(nums.length - 1, Math.max(0, Math.ceil(fraction * nums.length) - 1));
  return nums[index];
}

function normalizeUsageRow(row) {
  const entry = row && typeof row === "object" ? row : {};
  const usage = entry?.usage && typeof entry.usage === "object" ? entry.usage : {};
  const responseParams = entry?.response?.parameters && typeof entry.response.parameters === "object"
    ? entry.response.parameters
    : {};
  const inputTokens = toFiniteNumber(entry.input_tokens ?? usage.input_tokens ?? entry.prompt_tokens ?? usage.prompt_tokens);
  const outputTokens = toFiniteNumber(entry.output_tokens ?? usage.output_tokens ?? entry.completion_tokens ?? usage.completion_tokens);
  const totalTokens = toFiniteNumber(entry.total_tokens ?? usage.total_tokens ?? (inputTokens + outputTokens));
  const totalCostUsd = toFiniteNumber(
    entry.total_cost_usd
      ?? usage.total_cost_usd
      ?? entry.cost_usd
      ?? usage.cost_usd
      ?? entry.total_cost
      ?? usage.total_cost
  );
  const note = [entry.error, usage.error, entry.reason, usage.reason]
    .map((item) => String(item || "").trim())
    .find((item) => item && item !== "-") || "";
  const estimated = Boolean(entry.estimated ?? usage.estimated);
  return {
    task: entry.task || entry.agent || entry.service || entry.action || entry.event_type || "-",
    provider: entry.provider || entry.vendor || entry.model_provider || usage.provider || responseParams.provider || "-",
    model: entry.model || entry.model_name || entry.deployment || usage.model || responseParams.model || "-",
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    total_tokens: totalTokens,
    total_cost_usd: totalCostUsd,
    note,
    estimated,
  };
}

function isPlaceholderUsageValue(value) {
  const token = String(value || "").trim().toLowerCase();
  return !token || token === "-" || token === "unknown" || token === "n/a" || token === "na" || token === "none" || token === "null";
}

function isMeaningfulUsageRow(row) {
  const hasUsage = toFiniteNumber(row?.input_tokens) > 0 || toFiniteNumber(row?.output_tokens) > 0 || toFiniteNumber(row?.total_tokens) > 0 || toFiniteNumber(row?.total_cost_usd) > 0;
  const hasProvider = !isPlaceholderUsageValue(row?.provider);
  const hasModel = !isPlaceholderUsageValue(row?.model);
  const hasErrorNote = Boolean(String(row?.note || "").trim());
  return hasUsage || hasProvider || hasModel || hasErrorNote;
}

function HorizontalBarChart({ title, subtitle, items }) {
  const safeItems = Array.isArray(items) ? items : [];
  const maxValue = safeItems.reduce((best, item) => Math.max(best, toFiniteNumber(item?.value)), 0);
  return (
    <article className="panel executive-chart-card">
      <div className="panel-head">
        <h3>{title}</h3>
      </div>
      {subtitle ? <p className="subtitle">{subtitle}</p> : null}
      <div className="executive-bars">
        {safeItems.map((item, index) => {
          const value = toFiniteNumber(item?.value);
          const widthPct = maxValue > 0 ? (value / maxValue) * 100 : 0;
          const normalizedWidth = maxValue > 0 && value > 0 ? Math.max(4, widthPct) : 0;
          const tone = String(item?.tone || "ops");
          return (
            <div className="executive-bar-row" key={`bar-${index}`}>
              <span>{item?.label || "-"}</span>
              <strong>{item?.displayValue ?? String(value)}</strong>
              <div className="executive-bar-track">
                <div className={`executive-bar-fill tone-${tone}`} style={{ width: `${normalizedWidth}%` }} />
              </div>
            </div>
          );
        })}
        {!safeItems.length ? <p className="subtitle">No chart data available.</p> : null}
      </div>
    </article>
  );
}

function SuccessFailureDonut({ success, failure }) {
  const safeSuccess = Math.max(0, toFiniteNumber(success));
  const safeFailure = Math.max(0, toFiniteNumber(failure));
  const total = safeSuccess + safeFailure;
  const successPct = total > 0 ? (safeSuccess / total) * 100 : 0;
  return (
    <article className="panel executive-chart-card">
      <div className="panel-head">
        <h3>Success vs Failure</h3>
      </div>
      <div className="executive-donut-wrap">
        <div
          className="executive-donut"
          style={{
            background: `conic-gradient(var(--ok) 0 ${successPct}%, var(--danger) ${successPct}% 100%)`,
          }}
        >
          <div className="executive-donut-core">
            <strong>{total}</strong>
            <span>Requests</span>
          </div>
        </div>
        <div className="executive-donut-legend">
          <div><span className="legend-dot legend-ok" />Success: {safeSuccess}</div>
          <div><span className="legend-dot legend-danger" />Failure: {safeFailure}</div>
        </div>
      </div>
    </article>
  );
}

const ONBOARDING_STEP_BACKGROUND = {
  setup_monitoring: {
    1: "Saved to the OnboardingStateRecord table (keyed by project_name) via POST /onboarding/complete on monitoring-adapter.",
    2: "No backend call - determines which branch of the same request monitoring-adapter executes next (rule onboarding vs landing pad ingestion).",
    3: "Your plain-English lines are sent to the new-rule-onboarding pipeline, which asks the model-router (LLM) to translate them into concrete Prometheus rule specs (metric, threshold, duration).",
    4: "Generated rules are rendered into Prometheus rule YAML under backend/rag/changes/prometheus_rules, and Prometheus is asked to reload; a simulation check validates the rule behaves as expected.",
    5: "For each generated rule, a runbook document is created and saved via POST /rag/documents - the same endpoint used by Alert Knowledge and the Dashboard's Provide Docs - so it appears under the Alert Knowledge tab.",
  },
  existing_monitoring: {
    1: "Saved to the OnboardingStateRecord table (keyed by project_name) via POST /onboarding/complete on monitoring-adapter.",
    2: "No backend call - determines which branch of the same request monitoring-adapter executes next (rule onboarding vs landing pad ingestion).",
    3: "Saves the ingestion endpoint/connection profile you provide. This is the URL your monitoring tool's webhook (e.g. Alertmanager) should POST alerts to.",
    4: "Incoming alerts hit monitoring-adapter's /alerts/alertmanager endpoint, are written to the landing pad, published to the raw-alerts topic, and consumed by alert-intelligence -> orchestrator -> the rest of the incident pipeline.",
    5: "Optional. If rule onboarding was also enabled, documents are generated the same way as the Setup Monitoring path and appear under the Alert Knowledge tab.",
  },
};

function explainOnboardingStepBackground(stepNumber, isSetupMonitoring) {
  const table = ONBOARDING_STEP_BACKGROUND[isSetupMonitoring ? "setup_monitoring" : "existing_monitoring"];
  return table[stepNumber] || "No background detail available for this step.";
}

function FlowTimelineGraph({ rows }) {
  const timelineRows = Array.isArray(rows) ? rows : [];
  if (!timelineRows.length) {
    return <p className="subtitle">No timeline data found for selected alert.</p>;
  }

  const parseMaybeJson = (value) => {
    const text = String(value || "").trim();
    if (!text) {
      return null;
    }
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch (_error) {
      return null;
    }
  };

  const classifyStage = (row) => {
    const stage = String(row?.stage || "").toLowerCase();
    if (stage.includes("landing pad") || stage.includes("alert received") || stage.includes("alert landed")) {
      return { kind: "ingestion", short: "ING", label: "Landing Pad" };
    }
    if (stage.includes("dedup") || stage.includes("correlation") || stage.includes("enrich")) {
      return { kind: "dedupe", short: "DED", label: "Dedup" };
    }
    if (stage.includes("rag context") || stage.includes("context retrieval") || stage.includes("context intelligence")) {
      return { kind: "rag", short: "RAG", label: "RAG" };
    }
    if (stage.includes("embedding") || stage.includes("semantic") || stage.includes("vector")) {
      return { kind: "semantic", short: "SEM", label: "Semantic" };
    }
    if (stage.includes("routing") || stage.includes("policy") || stage.includes("workflow")) {
      return { kind: "policy", short: "POL", label: "Policy" };
    }
    if (stage.includes("remediation") || stage.includes("command") || stage.includes("execute")) {
      return { kind: "execution", short: "CMD", label: "Execution" };
    }
    return { kind: "generic", short: "EVT", label: "Event" };
  };

  const getRowBackendEvents = (row) => {
    const input = parseMaybeJson(row?.inputValueText);
    const output = parseMaybeJson(row?.outputValueText);
    const rawEvents = Array.from(
      new Set(
        [
          ...(Array.isArray(row?.backendEvents) ? row.backendEvents : []),
          String(input?.event_type || "").trim(),
          String(output?.event_type || "").trim(),
        ].filter(Boolean)
      )
    );

    const orderHints = [
      "incident.alert",
      "incident.workflow.selected",
      "incident.context.collected",
      "incident.recommendation.generated",
      "incident.approval.requested",
      "incident.approval.recorded",
      "incident.remediation.executed",
      "incident.closure.completed",
    ];

    const eventWeight = (eventName) => {
      const normalized = String(eventName || "").toLowerCase();
      const index = orderHints.findIndex((hint) => normalized.includes(hint));
      return index === -1 ? orderHints.length : index;
    };

    return rawEvents
      .slice()
      .sort((left, right) => {
        const leftWeight = eventWeight(left);
        const rightWeight = eventWeight(right);
        if (leftWeight !== rightWeight) {
          return leftWeight - rightWeight;
        }
        return String(left).localeCompare(String(right));
      });
  };

  const explainBackground = (row, stageMeta) => {
    const input = parseMaybeJson(row?.inputValueText);
    const output = parseMaybeJson(row?.outputValueText);
    const topicIn = String(row?.consumes || "-");
    const topicOut = String(row?.publishes || "-");
    const dbTables = String(row?.tables || "-");
    const mergedBackendEvents = getRowBackendEvents(row);
    const eventStage = String(output?.event_stage || input?.event_stage || row?.detail || "-").trim() || "-";
    const eventStatus = String(output?.status || input?.status || "-").trim() || "-";
    const traceId = String(output?.trace_id || input?.trace_id || "-").trim() || "-";

    return [
      `stage_kind: ${stageMeta.kind}`,
      `backend_events: ${mergedBackendEvents.length ? mergedBackendEvents.join(" | ") : "none"}`,
      `source_topic: ${topicIn}`,
      `target_topic: ${topicOut}`,
      `tables_touched: ${dbTables}`,
      `event_stage: ${eventStage}`,
      `event_status: ${eventStatus}`,
      `trace_id: ${traceId}`,
    ].join("\n");
  };

  const copyPlanStep = async (value) => {
    const text = String(value || "").trim();
    if (!text || typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
    } catch (_error) {
      // Best-effort copy for operator convenience.
    }
  };

  const extractExecutionPlan = (row) => {
    const input = parseMaybeJson(row?.inputValueText);
    const output = parseMaybeJson(row?.outputValueText);
    const commands = [];
    const scripts = [];
    const queries = [];
    const seenObjects = new WeakSet();

    const pushUnique = (target, value) => {
      const token = String(value || "").trim();
      if (!token) {
        return;
      }
      if (!target.some((item) => item.toLowerCase() === token.toLowerCase())) {
        target.push(token);
      }
    };

    const classifyLine = (raw) => {
      const token = String(raw || "").trim();
      if (!token) {
        return;
      }
      const lowered = token.toLowerCase();
      if (lowered.startsWith("cmd:")) {
        pushUnique(commands, token.slice(4).trim());
        return;
      }
      if (lowered.startsWith("script:")) {
        pushUnique(scripts, token.slice(7).trim());
        return;
      }
      if (lowered.startsWith("query:")) {
        pushUnique(queries, token.slice(6).trim());
        return;
      }
      pushUnique(commands, token);
    };

    const collectFromPlanText = (value) => {
      const text = String(value || "").trim();
      if (!text) {
        return;
      }
      let currentSection = "command";
      text.split(/\r?\n/).forEach((line) => {
        const token = String(line || "").trim();
        if (!token) {
          return;
        }
        if (/^commands?\s*:/i.test(token)) {
          currentSection = "command";
          const inline = token.replace(/^commands?\s*:/i, "").trim();
          if (inline) {
            classifyLine(`cmd: ${inline}`);
          }
          return;
        }
        if (/^scripts?\s*:/i.test(token)) {
          currentSection = "script";
          const inline = token.replace(/^scripts?\s*:/i, "").trim();
          if (inline) {
            classifyLine(`script: ${inline}`);
          }
          return;
        }
        if (/^(queries?|sql)\s*:/i.test(token)) {
          currentSection = "query";
          const inline = token.replace(/^(queries?|sql)\s*:/i, "").trim();
          if (inline) {
            classifyLine(`query: ${inline}`);
          }
          return;
        }

        const normalized = token.replace(/^[-*]\s*/, "").trim();
        if (!normalized) {
          return;
        }
        if (/^(cmd|command|script|query)\s*:/i.test(normalized)) {
          classifyLine(normalized);
          return;
        }
        if (currentSection === "script") {
          pushUnique(scripts, normalized);
          return;
        }
        if (currentSection === "query") {
          pushUnique(queries, normalized);
          return;
        }
        pushUnique(commands, normalized);
      });
    };

    const collectFromValue = (value) => {
      if (!hasMeaningfulValue(value)) {
        return;
      }
      if (Array.isArray(value)) {
        value.forEach(collectFromValue);
        return;
      }
      if (typeof value === "string") {
        collectFromPlanText(value);
        return;
      }
      if (typeof value !== "object" || value === null) {
        return;
      }
      if (seenObjects.has(value)) {
        return;
      }
      seenObjects.add(value);

      (Array.isArray(value.commands) ? value.commands : []).forEach(classifyLine);
      (Array.isArray(value.scripts) ? value.scripts : []).forEach((item) => pushUnique(scripts, item));
      (Array.isArray(value.queries) ? value.queries : []).forEach((item) => pushUnique(queries, item));

      if (hasMeaningfulValue(value.execution_plan)) {
        collectFromValue(value.execution_plan);
      }

      [
        value.parameters,
        value.remediation_action,
        value.source_payload,
        value.recommendation,
        value.decision,
        value.payload,
        value.input,
        value.output,
        value.result,
      ].forEach((item) => {
        if (item && typeof item === "object") {
          collectFromValue(item);
        }
      });
    };

    collectFromValue(input);
    collectFromValue(output);

    return {
      commands: commands.filter(Boolean),
      scripts: scripts.filter(Boolean),
      queries: queries.filter(Boolean),
    };
  };

  const phaseBlueprint = [
    { kind: "ingestion", label: "Landing" },
    { kind: "dedupe", label: "Dedup" },
    { kind: "rag", label: "RAG" },
    { kind: "semantic", label: "Semantic" },
    { kind: "policy", label: "Policy" },
    { kind: "execution", label: "Execution" },
  ];
  const presentKinds = new Set(timelineRows.map((row) => classifyStage(row).kind));
  const errorCount = timelineRows.filter((row) => hasMeaningfulValue(row?.errorValueText)).length;
  const compactRows = timelineRows.map((row, index) => {
    const stageMeta = classifyStage(row);
    return {
      key: `compact-${index}`,
      phase: stageMeta.label,
      stage: row.stage || "-",
      agent: row.agent || "-",
      elapsed: row.elapsed !== "-" ? `${row.elapsed}s` : "-",
      status: hasMeaningfulValue(row?.errorValueText) ? "error" : "ok",
      detail: compactText(row.detail, 120) || "-",
    };
  });
  const totalElapsedSeconds = timelineRows.reduce((sum, row) => {
    const value = Number(row?.elapsed);
    return Number.isFinite(value) ? sum + Math.max(0, value) : sum;
  }, 0);
  const totalElapsedDisplay = timelineRows.length ? `${totalElapsedSeconds.toFixed(3)}s` : "-";

  return (
    <div className="timeline-graph">
      <div className="timeline-summary-strip">
        <div className="timeline-summary-metric">
          <strong>{timelineRows.length}</strong>
          <span>Total Stages</span>
        </div>
        <div className="timeline-summary-metric">
          <strong>{phaseBlueprint.filter((phase) => presentKinds.has(phase.kind)).length}/{phaseBlueprint.length}</strong>
          <span>Pipeline Coverage</span>
        </div>
        <div className="timeline-summary-metric">
          <strong>{Math.max(0, timelineRows.length - errorCount)}</strong>
          <span>Successful Stages</span>
        </div>
        <div className="timeline-phase-strip">
          {phaseBlueprint.map((phase) => {
            const active = presentKinds.has(phase.kind);
            return (
              <span
                key={`phase-${phase.kind}`}
                className={`timeline-phase-pill phase-${phase.kind} ${active ? "is-active" : "is-missing"}`}
                title={active ? `${phase.label} observed` : `${phase.label} not observed in this run`}
              >
                {phase.label}
              </span>
            );
          })}
        </div>
      </div>
      {timelineRows.map((row, index) => (
        (() => {
          const stageMeta = classifyStage(row);
          const backendEvents = getRowBackendEvents(row);
          const executionPlan = extractExecutionPlan(row);
          const hasExecutionPlan = stageMeta.kind === "execution"
            && (executionPlan.commands.length || executionPlan.scripts.length || executionPlan.queries.length);
          return (
        <article
          className={`timeline-node stage-${stageMeta.kind} ${hasMeaningfulValue(row?.errorValueText) ? "timeline-has-error" : ""}`}
          key={`timeline-node-${index}`}
          style={{ animationDelay: `${Math.min(index * 70, 560)}ms` }}
        >
          <div className="timeline-rail">
            <span className="timeline-dot" />
            {index < timelineRows.length - 1 ? <span className="timeline-line" /> : null}
          </div>
          <div className="timeline-body">
            <div className="timeline-headline">
              <strong>
                <span className={`timeline-stage-badge stage-${stageMeta.kind}`}>{stageMeta.short}</span>
                {" "}
                {row.stage || "-"}
              </strong>
              <span>{formatUtcTimestamp(row.timestamp)}</span>
            </div>
            <div className="timeline-meta">
              <span>{row.agent || "-"}</span>
              <span>{row.service || "-"}</span>
              <span>{row.elapsed !== "-" ? `${row.elapsed}s` : "-"}</span>
            </div>
            <p>{row.detail || "-"}</p>
            {row.inputValueText ? (
              <details>
                <summary>Input Value</summary>
                <pre className="result">{row.inputValueText}</pre>
              </details>
            ) : null}
            {row.outputValueText ? (
              <details>
                <summary>Output Value</summary>
                <pre className="result">{row.outputValueText}</pre>
              </details>
            ) : null}
            {hasExecutionPlan ? (
              <details open>
                <summary>Resolution Plan (Commands, Scripts, Queries)</summary>
                <div className="timeline-plan-grid">
                  <div className="timeline-plan-section">
                    <h4>Commands</h4>
                    {executionPlan.commands.length ? executionPlan.commands.map((step, stepIndex) => (
                      <div className="timeline-plan-row" key={`cmd-${index}-${stepIndex}`}>
                        <pre className="result">{step}</pre>
                        <button type="button" className="timeline-copy-btn" onClick={() => copyPlanStep(step)}>Copy</button>
                      </div>
                    )) : <p className="subtitle">No command steps.</p>}
                  </div>
                  <div className="timeline-plan-section">
                    <h4>Scripts</h4>
                    {executionPlan.scripts.length ? executionPlan.scripts.map((step, stepIndex) => (
                      <div className="timeline-plan-row" key={`script-${index}-${stepIndex}`}>
                        <pre className="result">{step}</pre>
                        <button type="button" className="timeline-copy-btn" onClick={() => copyPlanStep(step)}>Copy</button>
                      </div>
                    )) : <p className="subtitle">No script steps.</p>}
                  </div>
                  <div className="timeline-plan-section">
                    <h4>Queries</h4>
                    {executionPlan.queries.length ? executionPlan.queries.map((step, stepIndex) => (
                      <div className="timeline-plan-row" key={`query-${index}-${stepIndex}`}>
                        <pre className="result">{step}</pre>
                        <button type="button" className="timeline-copy-btn" onClick={() => copyPlanStep(step)}>Copy</button>
                      </div>
                    )) : <p className="subtitle">No validation queries.</p>}
                  </div>
                </div>
              </details>
            ) : null}
            {row.errorValueText ? (
              <details open>
                <summary>Error</summary>
                <pre className="result">{row.errorValueText}</pre>
              </details>
            ) : null}
            <details>
              <summary>How This Worked In Background</summary>
              <pre className="result">{explainBackground(row, stageMeta)}</pre>
            </details>
            <div className="timeline-tags">
              <span className="timeline-tag">in: {row.consumes || "-"}</span>
              <span className="timeline-tag">out: {row.publishes || "-"}</span>
              <span className="timeline-tag">db: {row.tables || "-"}</span>
            </div>
            <div className="timeline-backend-events">
              <span className="timeline-backend-label">backend:</span>
              {backendEvents.length ? backendEvents.map((eventName, eventIndex) => (
                <span className="timeline-backend-chip" key={`backend-${index}-${eventIndex}`}>
                  {eventName}
                </span>
              )) : <span className="timeline-backend-chip is-empty">none</span>}
            </div>
          </div>
        </article>
          );
        })()
      ))}
      <article className="panel" style={{ marginTop: 10 }}>
        <div className="panel-head">
          <h3>Stage Summary Table</h3>
          <p>Compact timeline view with phase, ownership, and status.</p>
        </div>
        <div className="table-wrap table-wrap-scroll-x">
          <table>
            <thead>
              <tr>
                <th>Phase</th>
                <th>Stage</th>
                <th>Agent</th>
                <th>Elapsed</th>
                <th>Status</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {compactRows.map((row) => (
                <tr key={row.key}>
                  <td>{row.phase}</td>
                  <td>{row.stage}</td>
                  <td>{row.agent}</td>
                  <td>{row.elapsed}</td>
                  <td><span className={`pill ${row.status === "error" ? "status-failed" : "status-approved"}`}>{row.status}</span></td>
                  <td>{row.detail}</td>
                </tr>
              ))}
              <tr>
                <td colSpan={3}><strong>Total Alert Time</strong></td>
                <td><strong>{totalElapsedDisplay}</strong></td>
                <td>-</td>
                <td>Cumulative elapsed time across all listed stages.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>
  );
}

function AgentEventsGraph({ rows }) {
  const eventRows = Array.isArray(rows) ? rows : [];
  if (!eventRows.length) {
    return <p className="subtitle">No events found for selected alert.</p>;
  }

  const flowNodes = [
    { id: "alert-intelligence", label: "Alert Intelligence Agent", short: "A1" },
    { id: "orchestrator", label: "Master Agent", short: "M" },
    { id: "context-agent", label: "Context Intelligence Agent", short: "C" },
    { id: "resolution-agent", label: "Resolution Intelligence Agent", short: "R" },
    { id: "approval-service", label: "Human Approval Layer", short: "H" },
    { id: "remediation-engine", label: "Remediation Automation Engine", short: "X" },
    { id: "closure-service", label: "Validator Agent", short: "V" },
  ];

  const detectAgentId = (row) => {
    const haystack = [
      row?.agent,
      row?.action,
      row?.eventType,
      row?.detail,
      row?.backgroundDetailText,
      row?.inputValueText,
      row?.outputValueText,
    ]
      .map((item) => String(item || "").toLowerCase())
      .join(" | ");
    if (
      haystack.includes("alert intelligence")
      || haystack.includes("alert-intelligence")
      || haystack.includes("incident.alert")
      || haystack.includes("raw-alert")
      || haystack.includes("enriched-alert")
    ) {
      return "alert-intelligence";
    }
    if (haystack.includes("master agent") || haystack.includes("orchestrator")) {
      return "orchestrator";
    }
    if (haystack.includes("context intelligence") || haystack.includes("context-agent")) {
      return "context-agent";
    }
    if (haystack.includes("resolution intelligence") || haystack.includes("resolution-agent") || haystack.includes("recommendation")) {
      return "resolution-agent";
    }
    if (haystack.includes("approval") || haystack.includes("human approval")) {
      return "approval-service";
    }
    if (haystack.includes("remediation")) {
      return "remediation-engine";
    }
    if (haystack.includes("validator") || haystack.includes("closure")) {
      return "closure-service";
    }
    return "";
  };

  const groupedRows = new Map(flowNodes.map((node) => [node.id, []]));
  eventRows.forEach((row) => {
    const id = detectAgentId(row);
    if (!id || !groupedRows.has(id)) {
      return;
    }
    groupedRows.get(id).push(row);
  });

  // Some runs persist sparse early-stage metadata; synthesize one Alert Intelligence row for visibility.
  if (!(groupedRows.get("alert-intelligence") || []).length && eventRows.length) {
    const seed = eventRows
      .slice()
      .sort((a, b) => toFiniteNumber(a?.sequence) - toFiniteNumber(b?.sequence))[0];
    groupedRows.set("alert-intelligence", [
      {
        ...seed,
        action: "Alert landed, deduped, and enriched for orchestration.",
        decision: seed?.decision || "severity + correlation applied",
        output: seed?.output || "enriched-alert emitted",
        communicates_to: seed?.communicates_to || "orchestration-events",
      },
    ]);
  }

  const visibleFlowNodes = flowNodes.filter((node) => (groupedRows.get(node.id) || []).length > 0);
  if (!visibleFlowNodes.length) {
    return <p className="subtitle">No mapped agent events found for this alert yet.</p>;
  }

  return (
    <div className="agent-dag-flow">
      <div className="agent-dag-track">
        {visibleFlowNodes.map((node, index) => {
          const rowsForNode = (groupedRows.get(node.id) || [])
            .slice()
            .sort((a, b) => toFiniteNumber(a?.sequence) - toFiniteNumber(b?.sequence));
          const latest = rowsForNode[rowsForNode.length - 1] || null;
          const hasError = hasMeaningfulValue(latest?.errorValueText);
          const statusLabel = hasError ? "error" : "observed";

          return (
            <div key={`agent-dag-${node.id}`} className="agent-dag-segment">
              <article className={`agent-dag-node status-${statusLabel}`}>
                <div className="agent-dag-head">
                  <span className="agent-dag-badge">{node.short}</span>
                  <strong>{node.label}</strong>
                  <span className={`agent-dag-status status-${statusLabel}`}>{statusLabel}</span>
                </div>
                <p>{latest?.action || "No agent event captured yet."}</p>
                <div className="agent-event-kv">
                  <span>Decision: {compactText(latest?.decision, 140) || "-"}</span>
                  <span>Output: {compactText(latest?.output, 140) || "-"}</span>
                  <span>Next: {latest?.communicates_to || "-"}</span>
                  <span>Events: {rowsForNode.length}</span>
                </div>
                {latest?.backgroundDetailText ? (
                  <details>
                    <summary>Background Details</summary>
                    <pre className="result">{latest.backgroundDetailText}</pre>
                  </details>
                ) : null}
                {rowsForNode.length ? (
                  <details>
                    <summary>Agent Event Timeline ({rowsForNode.length})</summary>
                    <div className="agent-event-rows">
                      {rowsForNode.map((row, rowIndex) => (
                        <div key={`agent-node-${node.id}-row-${rowIndex}`} className="agent-event-row timeline">
                          <strong>{row.sequence || rowIndex + 1}.</strong>
                          <span>{compactText(row.action, 120) || "-"}</span>
                          <span>{compactText(row.decision, 120) || "-"}</span>
                          <span>{formatUtcTimestamp(row.timestamp)}</span>
                          <span>{row.eventType || "-"}</span>
                        </div>
                      ))}
                    </div>
                  </details>
                ) : null}
              </article>
              {index < flowNodes.length - 1 ? <div className="agent-dag-arrow" aria-hidden="true">→</div> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TopicFlowGraph({ routing, timelineRows }) {
  const safeRouting = routing && typeof routing === "object" ? routing : {};
  const safeRows = Array.isArray(timelineRows) ? timelineRows : [];
  const published = Array.from(new Set(
    safeRows
      .map((row) => String(row?.publishes || "").trim())
      .filter((item) => item && item !== "-" && item.toLowerCase() !== "unknown")
  ));
  const consumed = Array.from(new Set(
    safeRows
      .map((row) => String(row?.consumes || "").trim())
      .filter((item) => item && item !== "-" && item.toLowerCase() !== "unknown")
  ));
  const provider = String(safeRouting?.message_bus_provider || "rabbitmq").trim().toUpperCase();
  const actualRows = SERVICE_TOPIC_FLOW.map((row) => {
    const hasTopicActivity = published.includes(row.publishes) || consumed.includes(row.consumes);
    return {
      service: row.service,
      consumed: hasTopicActivity ? row.consumes : "-",
      published: hasTopicActivity ? row.publishes : "-",
      provider,
      status: hasTopicActivity ? "Observed" : "Configured",
    };
  });
  const configuredRows = SERVICE_TOPIC_FLOW.map((row) => ({
    service: row.service,
    consumes: row.consumes === "-" ? "-" : `${row.consumes} (enabled transports)`,
    publishes: row.publishes,
  }));

  return (
    <MessageBusTopology
      actual={{ rows: actualRows, published, consumed }}
      configuredRows={configuredRows}
      routing={safeRouting}
      primaryTopic={published[0] || "raw-alerts"}
      compact
    />
  );
}

function MessageBusTopology({ actual, configuredRows, routing, primaryTopic, compact = false }) {
  const safeActual = actual && typeof actual === "object" ? actual : {};
  const safeRouting = routing && typeof routing === "object" ? routing : {};
  const published = Array.isArray(safeActual.published) ? safeActual.published : [];
  const consumed = Array.isArray(safeActual.consumed) ? safeActual.consumed : [];
  const observedTopics = new Set([...published, ...consumed].map((topic) => String(topic || "").trim()).filter(Boolean));
  const rows = Array.isArray(configuredRows) ? configuredRows : [];
  const provider = String(safeRouting?.message_bus_provider || safeActual?.rows?.[0]?.provider || "Azure Service Bus").trim();
  const workflow = String(safeRouting?.workflow || "alert-workflow").trim();
  const executionMode = String(safeRouting?.execution_mode || "parallel-workers").trim();
  const sourceTopic = String(primaryTopic || rows.find((row) => row?.publishes)?.publishes || "kaiops-orchestration-events").trim();
  const workerNodes = [
    { title: "Alert Intelligence", service: "alert-intelligence", topic: "enriched-alerts", lane: "worker" },
    { title: "Context Worker", service: "context-agent", topic: "context-events", lane: "worker" },
    { title: "Resolution Worker", service: "resolution-agent", topic: "resolution-events", lane: "worker" },
    { title: "Approval Worker", service: "approval-service", topic: "approval-events", lane: "gate" },
    { title: "Remediation Worker", service: "remediation-engine", topic: "remediation-events", lane: "worker" },
    { title: "Closure Worker", service: "closure-service", topic: "closure-events", lane: "worker" },
  ];

  const isObserved = (topic) => observedTopics.has(String(topic || "").replace(" (enabled transports)", ""));

  return (
    <div className={`message-bus-topology ${compact ? "compact" : ""}`} aria-label="Message bus topology">
      <div className="bus-summary-strip">
        <div>
          <span>Provider</span>
          <strong>{provider}</strong>
        </div>
        <div>
          <span>Workflow</span>
          <strong>{workflow}</strong>
        </div>
        <div>
          <span>Execution</span>
          <strong>{executionMode}</strong>
        </div>
        <div>
          <span>Primary Topic</span>
          <strong>{sourceTopic}</strong>
        </div>
      </div>

      <div className="bus-path-stage-grid">
        <section className="bus-stage bus-stage-ingest">
          <div className="bus-stage-head">
            <span className="bus-node-icon">LP</span>
            <div>
              <strong>Landing Pad</strong>
              <span>Alert intake and normalization</span>
            </div>
          </div>
          <div className="bus-endpoint-box">
            <span>HTTP ingestion</span>
            <code>/alerts/alertmanager</code>
          </div>
          <div className="bus-topic-pill active">raw-alerts</div>
        </section>

        <section className="bus-stage bus-stage-topic">
          <div className="bus-stage-head">
            <span className="bus-node-icon">TC</span>
            <div>
              <strong>Topic Creation</strong>
              <span>Provisioned routing channels</span>
            </div>
          </div>
          <div className="bus-topic-sequence" aria-label="Sequential topic creation flow">
            {rows.map((row, index) => {
              const topic = String(row?.publishes || "").trim();
              const consumes = String(row?.consumes || "").replace(" (enabled transports)", "").trim();
              const state = isObserved(topic) ? "created" : "configured";
              return (
                <div className="bus-topic-sequence-step" key={`${topic || "topic"}-${index}`}>
                  <div className={`bus-topic-create-row ${state}`}>
                    <span>{index + 1}</span>
                    <div>
                      <strong>{topic || "-"}</strong>
                      <small>{consumes && consumes !== "-" ? `after ${consumes}` : "landing pad seed topic"}</small>
                    </div>
                    <em>{state}</em>
                  </div>
                  {index < rows.length - 1 ? (
                    <div className="bus-topic-sequence-arrow" aria-hidden="true">
                      <i />
                      <span>next</span>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>

        <section className="bus-stage bus-stage-master">
          <div className="bus-stage-head">
            <span className="bus-node-icon">MN</span>
            <div>
              <strong>Master Node</strong>
              <span>Orchestrator coordinates workers</span>
            </div>
          </div>
          <div className="bus-master-node">
            <strong>orchestrator</strong>
            <span>Consumes enriched-alerts</span>
            <span>Publishes orchestration-events</span>
          </div>
        </section>
      </div>

      <div className="bus-flow-arrow-row" aria-hidden="true">
        <span>Landing Pad</span>
        <i />
        <span>Topics</span>
        <i />
        <span>Master Node</span>
        <i />
        <span>Parallel Workers</span>
      </div>

      <section className="bus-parallel-section">
        <div className="bus-stage-head">
          <span className="bus-node-icon">PW</span>
          <div>
            <strong>Parallel Processing Workers</strong>
            <span>Independent consumers process topic events concurrently</span>
          </div>
        </div>
        <div className="bus-worker-grid">
          {workerNodes.map((worker) => (
            <div className={`bus-worker-node ${worker.lane}`} key={worker.service}>
              <span>{worker.service}</span>
              <strong>{worker.title}</strong>
              <em className={isObserved(worker.topic) ? "observed" : "pending"}>
                {isObserved(worker.topic) ? "observed" : "ready"}
              </em>
              <code>{worker.topic}</code>
            </div>
          ))}
        </div>
      </section>

      <div className="bus-observed-rail">
        <strong>Observed Topics</strong>
        <div>
          {[...observedTopics].map((topic) => (
            <span key={`observed-topic-${topic}`}>{topic}</span>
          ))}
          {!observedTopics.size ? <span>No live topic activity yet</span> : null}
        </div>
      </div>
    </div>
  );
}

function ExecutionPlanGraph({ plan }) {
  const safePlan = plan && typeof plan === "object" ? plan : {};
  const commands = Array.isArray(safePlan.commands) ? safePlan.commands : [];
  const grouped = { commands: [], scripts: [], queries: [] };
  commands.forEach((item) => {
    const token = String(item || "").trim();
    if (!token) {
      return;
    }
    if (/^script\s*:/i.test(token)) {
      grouped.scripts.push(token.replace(/^script\s*:/i, "").trim());
      return;
    }
    if (/^query\s*:/i.test(token)) {
      grouped.queries.push(token.replace(/^query\s*:/i, "").trim());
      return;
    }
    grouped.commands.push(token.replace(/^cmd\s*:/i, "").trim());
  });

  return (
    <div className="execution-graph">
      <article className="execution-card">
        <h4>Plan Core</h4>
        <div className="execution-grid">
          <span>Workflow</span><strong>{safePlan.workflow || "-"}</strong>
          <span>Action</span><strong>{safePlan.action || "-"}</strong>
          <span>Rationale</span><strong>{safePlan.rationale || "-"}</strong>
          <span>Mode</span><strong>{safePlan.executionMode || "-"}</strong>
          <span>Risk</span><strong>{safePlan.riskTier || "-"}</strong>
          <span>Provider</span><strong>{String(safePlan.provider || "-").toUpperCase()}</strong>
          <span>Approval</span><strong>{String(safePlan.requiresApproval)}</strong>
          <span>Incident Status</span><strong>{safePlan.incidentStatus || "-"}</strong>
          <span>Approval Status</span><strong>{safePlan.approvalStatus || "-"}</strong>
        </div>
      </article>
      <article className="execution-card">
        <h4>Remediation Plan</h4>
        <div className="execution-command-list">
          {grouped.commands.length ? grouped.commands.map((command, index) => (
            <div className="execution-command" key={`cmd-${index}`} style={{ animationDelay: `${Math.min(index * 80, 640)}ms` }}>
              <span>{index + 1}</span>
              <code>{String(command || "-")}</code>
            </div>
          )) : <p className="subtitle">No command sequence found.</p>}
          {grouped.scripts.length ? (
            <>
              <h4>Scripts</h4>
              {grouped.scripts.map((script, index) => (
                <div className="execution-command" key={`script-${index}`}>
                  <span>S{index + 1}</span>
                  <code>{script}</code>
                </div>
              ))}
            </>
          ) : null}
          {grouped.queries.length ? (
            <>
              <h4>Validation Queries</h4>
              {grouped.queries.map((query, index) => (
                <div className="execution-command" key={`query-${index}`}>
                  <span>Q{index + 1}</span>
                  <code>{query}</code>
                </div>
              ))}
            </>
          ) : null}
        </div>
      </article>
    </div>
  );
}

function renderHtmlTable(headers, rows) {
  const safeHeaders = Array.isArray(headers) ? headers : [];
  const safeRows = Array.isArray(rows) ? rows : [];
  const head = safeHeaders.map((header) => `<th>${htmlEscape(header)}</th>`).join("");
  const body = safeRows.length
    ? safeRows
        .map((row) => {
          const cells = Array.isArray(row) ? row : [];
          return `<tr>${cells.map((cell) => `<td>${htmlEscape(asDisplayValue(cell))}</td>`).join("")}</tr>`;
        })
        .join("")
    : `<tr><td colspan="${Math.max(1, safeHeaders.length)}">No rows available.</td></tr>`;
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function normalizeGeneratedRuleRows(source) {
  const payload = source && typeof source === "object" ? source : {};
  const candidates = [
    payload.generated_rules,
    payload.rules,
    payload.rule_candidates,
    payload.rule_set,
    payload.output?.rules,
    payload.result?.rules,
    payload.data?.rules,
  ];
  const first = candidates.find((item) => Array.isArray(item) && item.length) || [];
  return first.map((item, index) => {
    const row = item && typeof item === "object" ? item : {};
    return {
      id: String(row.id || row.rule_id || row.name || `rule-${index + 1}`),
      name: String(row.name || row.rule_name || row.alertname || `rule-${index + 1}`),
      platform: String(row.platform || row.target_platform || row.provider || "prometheus"),
      contractMode: String(row.contract_mode || row.adapter_mode || "-"),
      contractStatus: String(row.contract_status || row.adapter_status || "-"),
      severity: String(row.severity || row.level || "-").toLowerCase(),
      expression: String(row.expression || row.expr || row.query || row.condition || "-").trim(),
      status: String(row.status || row.state || "generated"),
    };
  });
}

function summarizeAlertRuleContext(row, workflow = {}) {
  const alertRow = row && typeof row === "object" ? row : {};
  const alertLabels = typeof alertRow.labels === "object" && alertRow.labels ? alertRow.labels : {};
  const alertAnnotations = typeof alertRow.annotations === "object" && alertRow.annotations ? alertRow.annotations : {};
  const workflowPayload = workflow && typeof workflow === "object" ? workflow : {};
  const recommendation = typeof workflowPayload.recommendation === "object" && workflowPayload.recommendation ? workflowPayload.recommendation : {};
  const recommendationMetadata = typeof recommendation.metadata === "object" && recommendation.metadata ? recommendation.metadata : {};
  const candidates = [
    alertRow.rule_name,
    alertRow.rule,
    alertRow.alert_rule,
    alertRow.rule_expression,
    alertRow.rule_query,
    alertLabels.rule_name,
    alertLabels.alertname,
    alertLabels.alert,
    alertLabels.rule,
    recommendationMetadata.rule_name,
    recommendationMetadata.rule,
    alertAnnotations.summary,
    alertAnnotations.description,
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  const expressionCandidates = [
    alertRow.expression,
    alertRow.expr,
    alertRow.query,
    alertRow.rule_expression,
    alertRow.rule_query,
    recommendationMetadata.rule_expression,
    recommendationMetadata.rule_query,
    alertAnnotations.expression,
    alertAnnotations.query,
    alertAnnotations.description,
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean);

  const ruleName = candidates[0] || String(alertRow.name || alertRow.alert_name || alertLabels.alertname || "Alert Rule").trim();
  const expression = expressionCandidates[0] || "No explicit rule expression was surfaced in the incident payload.";
  const service = String(alertRow.service || alertLabels.service || recommendationMetadata.service || "").trim();
  const environment = String(alertRow.environment || alertLabels.environment || recommendationMetadata.environment || "").trim();
  const note = [service ? `service=${service}` : "", environment ? `environment=${environment}` : ""].filter(Boolean).join(" | ");

  return {
    ruleName,
    expression,
    note: note || "Derived from alert labels and workflow metadata.",
    source: String(alertRow.source || alertRow.provider || alertLabels.job || "payload metadata").trim(),
    severity: String(alertRow.severity || alertLabels.severity || recommendation?.severity || "warning").trim().toLowerCase(),
  };
}

function buildWorkflowFlowStages(workflow, timelineRows = []) {
  const safeWorkflow = workflow && typeof workflow === "object" ? workflow : {};
  const safeRows = Array.isArray(timelineRows) ? timelineRows : [];
  const findStage = (needle) => safeRows.find((row) => String(row?.stage || row?.agent || row?.detail || "").toLowerCase().includes(needle));
  const hasParallelProcessing = safeRows.some((row) => {
    const token = String(row?.agent || row?.service || row?.detail || "").toLowerCase();
    return token.includes("alert intelligence") || token.includes("orchestrator") || token.includes("context") || token.includes("resolution");
  });
  return [
    {
      id: "landing-pad",
      label: "Landing Pad",
      detail: "Raw alerts are accepted, normalized, and added to the incident stream.",
      status: findStage("landing") ? "done" : "active",
    },
    {
      id: "parallel-processing",
      label: "Parallel Processing",
      detail: hasParallelProcessing
        ? "Alert intelligence, orchestration, context, and resolution work the stream in parallel workers."
        : "Backend workers fan out the alert stream through independent services for concurrent processing.",
      status: hasParallelProcessing ? "done" : "active",
    },
    {
      id: "approval",
      label: "Approval Gate",
      detail: String(safeWorkflow?.approval?.status || safeWorkflow?.decision?.status || "pending").trim(),
      status: safeWorkflow?.approval?.status ? "done" : "active",
    },
    {
      id: "remediation",
      label: "Remediation Execution",
      detail: `${Array.isArray(safeWorkflow?.remediation_action?.parameters?.execution_plan?.commands) ? safeWorkflow.remediation_action.parameters.execution_plan.commands.length : 0} commands captured for execution or review.`,
      status: safeWorkflow?.remediation_action?.status ? "done" : "active",
    },
    {
      id: "closure",
      label: "Closure & Validation",
      detail: String(safeWorkflow?.closure_report?.health_restored ? "Service restored and closure completed." : "Validation continues after remediation.").trim(),
      status: safeWorkflow?.closure_report?.health_restored ? "done" : "active",
    },
  ];
}

export default function App() {
  const defaultMonitorApplications = ["kaiops-core1", "kaiops-core"];
  const [applicationToMonitor, setApplicationToMonitor] = useState("kaiops-core1");
  const [monitorApplications, setMonitorApplications] = useState(defaultMonitorApplications);
  const [activeTab, setActiveTab] = useState("home");
  const [uiDensity, setUiDensity] = useState("comfortable");
  const [uiTheme, setUiTheme] = useState("auto");
  const [health, setHealth] = useState({ loading: false, ok: false, message: "Not checked" });
  const [alerts, setAlerts] = useState({ loading: false, rows: [], error: "" });
  const [alertsLimit, setAlertsLimit] = useState(50);
  const [alertSeverityOverrides, setAlertSeverityOverrides] = useState({ loading: false, rows: [], error: "", savingKey: "" });
  const [alertSeverityDrafts, setAlertSeverityDrafts] = useState({});
  const [dashboardAlertQuery, setDashboardAlertQuery] = useState("");
  const [dashboardAlertFocus, setDashboardAlertFocus] = useState("ops");
  const [incidentMetadata, setIncidentMetadata] = useState({ loading: false, rows: [], error: "" });
  const [closedIncidents, setClosedIncidents] = useState({ loading: false, rows: [], error: "" });
  const [flows, setFlows] = useState({ loading: false, rows: [], error: "" });
  const [gatewaySummary, setGatewaySummary] = useState({ loading: false, data: {}, error: "" });
  const [gatewayRecent, setGatewayRecent] = useState({ loading: false, rows: [], error: "" });
  const [landingPadRecent, setLandingPadRecent] = useState({ loading: false, rows: [], error: "" });
  const [ragDocs, setRagDocs] = useState({ loading: false, rows: [], error: "" });
  const [guidanceQuery, setGuidanceQuery] = useState("");
  const [guidanceState, setGuidanceState] = useState({ loading: false, rows: [], error: "" });
  const [submitState, setSubmitState] = useState({ loading: false, result: null, error: "" });
  const [workflowState, setWorkflowState] = useState({ loading: false, result: null, error: "" });
  const [approvalState, setApprovalState] = useState({ loading: false, result: null, error: "" });
  const [inlineRejectState, setInlineRejectState] = useState({ incidentId: "", comment: "" });
  const [showAdvancedApprovalForm, setShowAdvancedApprovalForm] = useState(false);
  const [approvalFilter, setApprovalFilter] = useState("all");
  const [approvalIncidentContext, setApprovalIncidentContext] = useState({
    loading: false,
    incident_id: "",
    payload: null,
    error: "",
  });
  const [selectedAlertId, setSelectedAlertId] = useState("");
  const [selectedApprovalIncidentId, setSelectedApprovalIncidentId] = useState("");
  const [selectedAlertData, setSelectedAlertData] = useState({ loading: false, payload: null, error: "", alertId: "" });
  const [selectedAlertDocumentLinks, setSelectedAlertDocumentLinks] = useState({
    loading: false,
    alertId: "",
    rows: [],
    canonicalAlert: null,
    contract: null,
    error: "",
  });
  const [selectedStageCompleteness, setSelectedStageCompleteness] = useState({
    loading: false,
    data: null,
    error: "",
    incidentId: "",
  });
  const [homeDetailTab, setHomeDetailTab] = useState("overview");
  const [diagnosticsDetailTab, setDiagnosticsDetailTab] = useState("timeline");
  const [approvalForm, setApprovalForm] = useState({
    action: "approve",
    incident_id: "",
    recommendation_id: "",
    approver: "admin",
    channel: "web",
    comment: "",
    modified_action: "",
  });
  const [remediationPlanEditor, setRemediationPlanEditor] = useState({
    commands: "",
    scripts: "",
    queries: "",
    connection_url: "",
    connection_type: "application",
    namespace: "",
    notes: "",
  });
  const [remediationExecutionState, setRemediationExecutionState] = useState({ loading: false, result: null, error: "" });
  const [selectedFlow, setSelectedFlow] = useState("payment-latency");
  const [metadataFilters, setMetadataFilters] = useState({
    risk_tier: "all",
    execution_mode: "all",
    transport_provider: "all",
    status: "all",
    service: "",
  });
  const [closedFilters, setClosedFilters] = useState({ risk: "all", mode: "all" });
  const [form, setForm] = useState(DEFAULT_ALERT);
  const [adminWorkspace, setAdminWorkspace] = useState("users");
  const [adminAuthForm, setAdminAuthForm] = useState({ username: "admin", password: "", device: "react-ui" });
  const [adminSession, setAdminSession] = useState({ loading: false, accessToken: "", refreshToken: "", user: null, error: "" });
  const [adminRoles, setAdminRoles] = useState([]);
  const [adminUsers, setAdminUsers] = useState({ loading: false, rows: [], error: "" });
  const [adminCreateUser, setAdminCreateUser] = useState({
    username: "",
    email: "",
    password: "",
    first_name: "",
    last_name: "",
    role_id: 1,
    status: "active",
    is_active: true,
  });
  const [adminEditUser, setAdminEditUser] = useState({
    id: null,
    username: "",
    email: "",
    first_name: "",
    last_name: "",
    role_id: 1,
    status: "active",
    is_active: true,
  });
  const [adminResetPasswordForm, setAdminResetPasswordForm] = useState({ user_id: null, new_password: "" });
  const [onboardingForm, setOnboardingForm] = useState({
    name: "kaiops-project",
    owner_team: "platform-ops",
    environment: "prod",
    region: "us-east-1",
    deployment_mode: "on_prem",
    monitoring_tool: "prometheus",
    monitoring_url: "http://prometheus:9090",
    prometheus_url: "http://prometheus:9090",
    new_relic_url: "",
    datadog_url: "",
    azure_subscription_id: "",
    azure_resource_group: "",
    azure_service_bus_namespace: "",
    azure_service_bus_topic: "kaiops-orchestration-events",
    azure_service_bus_subscription: "kaiops-orchestration-sub",
    azure_content_safety_enabled: false,
    azure_content_safety_endpoint: "",
    assignment_username: "",
    assignment_project: "",
    onboarding_path: "existing_monitoring",
    start_rule_onboarding: false,
    rule_onboarding_plain_language: "",
  });
  const [onboardingState, setOnboardingState] = useState({ loading: false, connectivity: {}, rows: [], error: "", success: "" });
  const [onboardingRuleCapabilities, setOnboardingRuleCapabilities] = useState({ loading: false, rows: [], error: "" });
  const [onboardingRuleWizardStep, setOnboardingRuleWizardStep] = useState(1);
  const [onboardingRuleWizardMode, setOnboardingRuleWizardMode] = useState("existing");
  const [existingRulePipelineForm, setExistingRulePipelineForm] = useState({
    platform: "prometheus",
    mode: "bidirectional",
    connection_url: "",
    rules_json: JSON.stringify([
      {
        name: "project_cpu_high",
        metric: "cpu_usage_percent",
        threshold: 85,
        duration: "5m",
        aggregation: "avg",
        severity: "high",
        labels: { project: "kaiops-project" },
      },
    ], null, 2),
  });
  const [newRulePipelineForm, setNewRulePipelineForm] = useState({
    requirements_text: [
      "Alert if CPU stays above 80% for more than 5 minutes with high severity",
      "Alert when latency is over 2000 for 10 minutes critical",
    ].join("\n"),
    selected_tool: "prometheus",
  });
  const [onboardingProjectMode, setOnboardingProjectMode] = useState("existing");
  const [onboardingRuleRunState, setOnboardingRuleRunState] = useState({ loading: false, result: null, error: "" });
  const [onboardingWorkflowSteps, setOnboardingWorkflowSteps] = useState([]);
  const [onboardingLandingPadSummary, setOnboardingLandingPadSummary] = useState({});
  const [onboardingGeneratedDocs, setOnboardingGeneratedDocs] = useState([]);
  const [onboardingSourceDocs, setOnboardingSourceDocs] = useState({ loading: false, rows: [], error: "" });
  const [knowledgePackState, setKnowledgePackState] = useState({
    loading: false,
    draft: null,
    error: "",
    success: "",
    approved: false,
  });
  const [knowledgePackCorrections, setKnowledgePackCorrections] = useState({});
  const [onboardingReviewAck, setOnboardingReviewAck] = useState({ rules: false, docs: false, metadata: false });
  const [onboardingDocApprovalState, setOnboardingDocApprovalState] = useState({
    loading: false,
    error: "",
    success: "",
    approved: false,
  });
  const [onboardingRuleLookup, setOnboardingRuleLookup] = useState({ workflow_id: "", loading: false, result: null, error: "" });
  const [selectedOnboardingProject, setSelectedOnboardingProject] = useState("");
  const [monitoringAppForm, setMonitoringAppForm] = useState({
    tenant_id: "default",
    name: "",
    owner_team: "platform-ops",
    owner_email: "",
    environment: "prod",
    namespace: "default",
    region: "us-east-1",
    technology: "python-fastapi",
    metrics_endpoint: "http://api-gateway:8000/metrics",
    labels_text: "security=internal,compliance=sox,workload_kind=Deployment",
  });
  const [monitoringApps, setMonitoringApps] = useState({ loading: false, rows: [], error: "" });
  const [monitoringAppSubmit, setMonitoringAppSubmit] = useState({ loading: false, error: "", success: "" });
  const [selectedMonitoringAppId, setSelectedMonitoringAppId] = useState("");
  const [monitoringAppDetails, setMonitoringAppDetails] = useState({ loading: false, history: [], validations: [], dashboards: [], error: "" });
  const [onboardingRuleEditor, setOnboardingRuleEditor] = useState({
    workflow_id: "",
    project_name: "",
    payload_json: "",
  });
  const [onboardingRuleEditorState, setOnboardingRuleEditorState] = useState({ loading: false, error: "", success: "" });
  const [alertOnboarding, setAlertOnboarding] = useState({
    kind: "incident",
    title: "New Alert Onboarding",
    summary: "",
    content: "Provide troubleshooting and escalation steps for this alert scenario.",
    services: "payments",
    severity: "high",
    alert_type: "availability",
    alert_id: "",
    execution_plan: "",
    remediation_commands_text: "",
    remediation_scripts_text: "",
    remediation_queries_text: "",
  });
  const [alertKnowledgePrompt, setAlertKnowledgePrompt] = useState("");
  const [alertKnowledgeSourceDoc, setAlertKnowledgeSourceDoc] = useState({
    loading: false,
    name: "",
    size: 0,
    text: "",
    excerpt: "",
    error: "",
  });
  const [alertKnowledgeView, setAlertKnowledgeView] = useState("onboarding");
  const [projectSetupStep, setProjectSetupStep] = useState("setup");
  const [projectSetupShowAll, setProjectSetupShowAll] = useState(false);
  const [alertOnboardingState, setAlertOnboardingState] = useState({ loading: false, result: null, error: "" });
  const [docPromptAlert, setDocPromptAlert] = useState(null);
  const [docPromptKind, setDocPromptKind] = useState("runbook");
  const [docPromptMode, setDocPromptMode] = useState("create");
  const [docPromptExistingDoc, setDocPromptExistingDoc] = useState(null);
  const [docPromptDocsByKind, setDocPromptDocsByKind] = useState({});
  const [alertRuleDraft, setAlertRuleDraft] = useState({ platform: "prometheus", requirement: "" });
  const [alertRuleState, setAlertRuleState] = useState({ loading: false, result: null, error: "" });
  const alertDetailsRef = useRef(null);
  const docPromptRef = useRef(null);
  const approvalQueueRef = useRef(null);
  const monitoringInspectRef = useRef(null);
  const alertKnowledgeRef = useRef(null);
  const approvalIncidentRequestRef = useRef({ incidentId: "", inFlight: false, lastFetchedAt: 0 });

  const formValid = useMemo(() => {
    return [form.source, form.name, form.service, form.severity, form.description].every((v) => String(v || "").trim());
  }, [form]);

  async function checkHealth() {
    setHealth({ loading: true, ok: false, message: "Checking API Gateway..." });
    try {
      const data = await fetchJson("/api-gateway/healthz");
      await loadMonitorApplications();
      setHealth({ loading: false, ok: data?.status === "ok", message: `${data?.service || "api-gateway"} is ${data?.status || "unknown"}` });
    } catch (error) {
      setHealth({ loading: false, ok: false, message: error.message });
    }
  }

  function unwrap(payload) {
    return payload?.data || payload || {};
  }

  async function loadRecentAlerts() {
    setAlerts((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const payload = await fetchJson(`/api-gateway/alerts/all?limit=${alertsLimit}`);
      const data = unwrap(payload);
      const rows = data?.rows || [];
      setAlerts({ loading: false, rows: Array.isArray(rows) ? rows : [], error: "" });
    } catch (error) {
      setAlerts({ loading: false, rows: [], error: error.message });
    }
  }

  async function loadAlertSeverityOverrides() {
    setAlertSeverityOverrides((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const payload = await fetchJson("/api-gateway/alerts/severity-overrides");
      const data = unwrap(payload);
      const rows = Array.isArray(data?.rows) ? data.rows : [];
      setAlertSeverityOverrides((prev) => ({ ...prev, loading: false, rows, error: "" }));
    } catch (error) {
      setAlertSeverityOverrides((prev) => ({ ...prev, loading: false, rows: [], error: error.message }));
    }
  }

  async function applyAlertSeverityOverrideRule(row) {
    const alertName = String(row?.name || row?.alert_name || "").trim();
    const service = String(row?.service || "").trim();
    const environment = String(row?.environment || "").trim();
    const key = severityOverrideKey(alertName, service, environment);
    const draftSeverity = String(alertSeverityDrafts[key] || row?.severity || "warning").trim().toLowerCase();
    if (!alertName) {
      setAlertSeverityOverrides((prev) => ({ ...prev, error: "Alert name is required for severity override." }));
      return;
    }
    setAlertSeverityOverrides((prev) => ({ ...prev, savingKey: key, error: "" }));
    try {
      await fetchJson("/api-gateway/alerts/severity-overrides", {
        method: "PUT",
        body: JSON.stringify({
          name: alertName,
          service,
          environment,
          severity: draftSeverity,
          requested_by: String(adminSession?.user?.username || "ui-user").trim(),
          requested_role: String(currentRole || "").trim(),
          updated_at: new Date().toISOString(),
        }),
      });
      await loadAlertSeverityOverrides();
      setAlertSeverityOverrides((prev) => ({ ...prev, savingKey: "", error: "" }));
    } catch (error) {
      setAlertSeverityOverrides((prev) => ({ ...prev, savingKey: "", error: error.message }));
    }
  }

  async function clearAlertSeverityOverrideRule(row) {
    const alertName = String(row?.name || row?.alert_name || "").trim();
    const service = String(row?.service || "").trim();
    const environment = String(row?.environment || "").trim();
    const key = severityOverrideKey(alertName, service, environment);
    if (!alertName) {
      return;
    }
    setAlertSeverityOverrides((prev) => ({ ...prev, savingKey: key, error: "" }));
    try {
      const params = new URLSearchParams({ name: alertName, service, environment });
      await fetchJson(`/api-gateway/alerts/severity-overrides?${params.toString()}`, { method: "DELETE" });
      await loadAlertSeverityOverrides();
      setAlertSeverityOverrides((prev) => ({ ...prev, savingKey: "", error: "" }));
    } catch (error) {
      setAlertSeverityOverrides((prev) => ({ ...prev, savingKey: "", error: error.message }));
    }
  }

  async function loadMonitoringApplications() {
    setMonitoringApps((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const payload = await fetchJson("/api-gateway/applications", authenticatedOptions());
      const data = unwrap(payload);
      const rows = Array.isArray(data?.rows) ? data.rows : [];
      setMonitoringApps({ loading: false, rows, error: "" });
      setSelectedMonitoringAppId((current) => {
        const normalizedCurrent = String(current || "").trim();
        if (normalizedCurrent && rows.some((row) => String(row?.id || "").trim() === normalizedCurrent)) {
          return normalizedCurrent;
        }
        return String(rows[0]?.id || "").trim();
      });
    } catch (error) {
      setMonitoringApps({ loading: false, rows: [], error: error.message });
    }
  }

  async function loadMonitoringApplicationDetails(applicationId) {
    const normalized = String(applicationId || "").trim();
    if (!normalized) {
      setMonitoringAppDetails({ loading: false, history: [], validations: [], dashboards: [], error: "" });
      return;
    }
    setMonitoringAppDetails((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const [historyPayload, validationsPayload, dashboardsPayload] = await Promise.all([
        fetchJson(`/api-gateway/applications/${normalized}/history`, authenticatedOptions()),
        fetchJson(`/api-gateway/applications/${normalized}/validations`, authenticatedOptions()),
        fetchJson(`/api-gateway/applications/${normalized}/dashboards`, authenticatedOptions()),
      ]);
      const historyRows = Array.isArray(unwrap(historyPayload)?.rows) ? unwrap(historyPayload).rows : [];
      const validationRows = Array.isArray(unwrap(validationsPayload)?.rows) ? unwrap(validationsPayload).rows : [];
      const dashboardRows = Array.isArray(unwrap(dashboardsPayload)?.rows) ? unwrap(dashboardsPayload).rows : [];
      setMonitoringAppDetails({ loading: false, history: historyRows, validations: validationRows, dashboards: dashboardRows, error: "" });
    } catch (error) {
      setMonitoringAppDetails({ loading: false, history: [], validations: [], dashboards: [], error: error.message });
    }
  }

  async function submitMonitoringApplication(event) {
    event.preventDefault();
    setMonitoringAppSubmit({ loading: true, error: "", success: "" });
    try {
      const metricsEndpoint = String(monitoringAppForm.metrics_endpoint || "").trim() || "http://api-gateway:8000/metrics";
      if (!/^https?:\/\//i.test(metricsEndpoint)) {
        setMonitoringAppSubmit({
          loading: false,
          error: "Metrics Endpoint must start with http:// or https:// (for example, http://api-gateway:8000/metrics).",
          success: "",
        });
        return;
      }
      const labels = Object.fromEntries(
        String(monitoringAppForm.labels_text || "")
          .split(",")
          .map((entry) => entry.trim())
          .filter(Boolean)
          .map((entry) => {
            const [key, ...rest] = entry.split("=");
            return [String(key || "").trim(), rest.join("=").trim()];
          })
          .filter(([key]) => key)
      );
      const payload = {
        tenant_id: monitoringAppForm.tenant_id,
        name: monitoringAppForm.name,
        owner_team: monitoringAppForm.owner_team,
        owner_email: monitoringAppForm.owner_email || null,
        environment: monitoringAppForm.environment,
        namespace: monitoringAppForm.namespace,
        region: monitoringAppForm.region,
        technology: monitoringAppForm.technology,
        metrics_endpoint: metricsEndpoint,
        monitoring_platform: "prometheus",
        labels,
      };
      await fetchJson("/api-gateway/applications", authenticatedOptions({
        method: "POST",
        body: JSON.stringify(payload),
      }));
      setMonitoringAppSubmit({ loading: false, error: "", success: `Queued onboarding for ${monitoringAppForm.name}` });
      setMonitoringAppForm((curr) => ({ ...curr, name: "", owner_email: "", metrics_endpoint: "http://api-gateway:8000/metrics" }));
      await loadMonitoringApplications();
      await loadMonitorApplications();
      await refreshViewsAfterSubmit();
    } catch (error) {
      setMonitoringAppSubmit({ loading: false, error: error.message, success: "" });
    }
  }

  async function loadAlertDetails(alertId) {
    const normalized = String(alertId || "").trim();
    if (!normalized) {
      return;
    }
    setSelectedAlertData({ loading: true, payload: null, error: "", alertId: normalized });
    try {
      const payload = await fetchJson(`/monitoring-adapter/alerts/${normalized}/processed-result`);
      setSelectedAlertData((prev) => {
        if (String(prev.alertId || "") !== normalized) {
          return prev;
        }
        return { loading: false, payload, error: "", alertId: normalized };
      });
    } catch (error) {
      setSelectedAlertData((prev) => {
        if (String(prev.alertId || "") !== normalized) {
          return prev;
        }
        return { loading: false, payload: null, error: error.message, alertId: normalized };
      });
    }
  }

  async function loadSelectedAlertDocumentLinks(alertId) {
    const normalized = String(alertId || "").trim();
    if (!normalized) {
      setSelectedAlertDocumentLinks({ loading: false, alertId: "", rows: [], canonicalAlert: null, contract: null, error: "" });
      return;
    }
    setSelectedAlertDocumentLinks((current) => ({
      ...current,
      loading: true,
      alertId: normalized,
      error: "",
    }));
    try {
      const payload = await fetchJson(`/api-gateway/alerts/${encodeURIComponent(normalized)}/linked-documents?limit=${alertsLimit}`);
      const data = unwrap(payload);
      const rows = Array.isArray(data?.linked_documents) ? data.linked_documents : [];
      setSelectedAlertDocumentLinks((current) => {
        if (String(current.alertId || "") !== normalized) {
          return current;
        }
        return {
          loading: false,
          alertId: normalized,
          rows,
          canonicalAlert: data?.canonical_alert || null,
          contract: data || null,
          error: "",
        };
      });
    } catch (error) {
      setSelectedAlertDocumentLinks((current) => {
        if (String(current.alertId || "") !== normalized) {
          return current;
        }
        return {
          ...current,
          loading: false,
          rows: [],
          canonicalAlert: null,
          contract: null,
          error: String(error?.message || "Unable to load linked documents"),
        };
      });
    }
  }

  async function loadIncidentStageCompleteness(incidentId) {
    const normalized = String(incidentId || "").trim();
    if (!normalized) {
      setSelectedStageCompleteness({ loading: false, data: null, error: "", incidentId: "" });
      return;
    }
    setSelectedStageCompleteness({ loading: true, data: null, error: "", incidentId: normalized });
    try {
      const payload = await fetchJson(`/api-gateway/incidents/${normalized}/stage-completeness`);
      const stageData = payload?.data || payload;
      setSelectedStageCompleteness((prev) => {
        if (String(prev.incidentId || "") !== normalized) {
          return prev;
        }
        return { loading: false, data: stageData, error: "", incidentId: normalized };
      });
    } catch (error) {
      setSelectedStageCompleteness((prev) => {
        if (String(prev.incidentId || "") !== normalized) {
          return prev;
        }
        return { loading: false, data: null, error: error.message, incidentId: normalized };
      });
    }
  }

  function openAlertDetails(row) {
    const alertId = row?.alert_id || row?.id || row?.incident_id;
    if (!alertId) {
      return;
    }
    setSelectedAlertId(String(alertId));
    setActiveTab("home");
    setHomeDetailTab("overview");
    loadAlertDetails(alertId);
    loadSelectedAlertDocumentLinks(alertId);
  }

  function openAlertDetailsFromIncident(row) {
    const incidentId = String(row?.incident_id || row?.id || "").trim();
    if (!incidentId) {
      return;
    }
    setApprovalState({ loading: false, result: null, error: "" });
    const scopedAlerts = filterAlertsForMonitor(alerts.rows, applicationToMonitor);
    const matchedAlert = scopedAlerts.find((alertRow) => {
      const alertId = String(alertRow?.alert_id || alertRow?.id || alertRow?.incident_id || "").trim();
      const sourceIncident = String(alertRow?.incident_id || "").trim();
      return alertId === incidentId || sourceIncident === incidentId;
    });
    openAlertDetails(matchedAlert || row);
  }

  useEffect(() => {
    if (activeTab !== "home" || !selectedAlertId) {
      return;
    }
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(() => {
      alertDetailsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [activeTab, selectedAlertId]);

  useEffect(() => {
    if (activeTab !== "home") {
      return;
    }
    const payload = selectedAlertData?.payload?.data || selectedAlertData?.payload || {};
    const workflow = payload?.workflow || payload || {};
    const currentIncidentId = String(workflow?.incident?.id || workflow?.incident_id || "").trim();

    if (!currentIncidentId) {
      setSelectedStageCompleteness({ loading: false, data: null, error: "", incidentId: "" });
      return;
    }
    if (
      String(selectedStageCompleteness.incidentId || "") === String(currentIncidentId)
      && (selectedStageCompleteness.data || selectedStageCompleteness.loading || selectedStageCompleteness.error)
    ) {
      return;
    }
    loadIncidentStageCompleteness(currentIncidentId);
  }, [activeTab, selectedAlertData.payload, selectedStageCompleteness.incidentId, selectedStageCompleteness.data, selectedStageCompleteness.loading, selectedStageCompleteness.error]);

  useEffect(() => {
    const scopedRows = filterAlertsForMonitor(alerts.rows, applicationToMonitor);
    if (activeTab !== "home") {
      return;
    }
    if (!scopedRows.length) {
      if (selectedAlertId) {
        setSelectedAlertId("");
      }
      if (selectedAlertData.payload || selectedAlertData.error) {
        setSelectedAlertData({ loading: false, payload: null, error: "", alertId: "" });
      }
      return;
    }
    const selectedExists = scopedRows.some(
      (row) => String(row?.alert_id || row?.id || row?.incident_id || "") === selectedAlertId
    );
    if (selectedExists) {
      if (String(selectedAlertData.alertId || "") !== String(selectedAlertId || "")) {
        loadAlertDetails(selectedAlertId);
      }
      if (String(selectedAlertDocumentLinks.alertId || "") !== String(selectedAlertId || "")) {
        loadSelectedAlertDocumentLinks(selectedAlertId);
      }
      return;
    }
    openAlertDetails(scopedRows[0]);
  }, [activeTab, alerts.rows, applicationToMonitor, selectedAlertId, selectedAlertData.payload, selectedAlertData.error, selectedAlertData.alertId, selectedAlertDocumentLinks.alertId]);

  async function loadIncidentMetadata() {
    setIncidentMetadata((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const params = new URLSearchParams({ limit: "120" });
      if (metadataFilters.risk_tier !== "all") {
        params.set("risk_tier", metadataFilters.risk_tier);
      }
      if (metadataFilters.execution_mode !== "all") {
        params.set("execution_mode", metadataFilters.execution_mode);
      }
      if (metadataFilters.transport_provider !== "all") {
        params.set("transport_provider", metadataFilters.transport_provider);
      }
      if (metadataFilters.status !== "all") {
        params.set("status", metadataFilters.status);
      }
      if (String(metadataFilters.service || "").trim()) {
        params.set("service", String(metadataFilters.service).trim());
      }
      const payload = await fetchJson(`/api-gateway/incidents/metadata?${params.toString()}`);
      const data = unwrap(payload);
      const rows = data?.rows || [];
      setIncidentMetadata({ loading: false, rows: Array.isArray(rows) ? rows : [], error: "" });
    } catch (error) {
      setIncidentMetadata({ loading: false, rows: [], error: error.message });
    }
  }

  async function loadClosedIncidents() {
    setClosedIncidents((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const payload = await fetchJson("/api-gateway/incidents/closed?limit=120");
      const data = unwrap(payload);
      const rows = Array.isArray(data?.rows) ? data.rows : [];
      if (rows.length) {
        setClosedIncidents({ loading: false, rows, error: "" });
        return;
      }

      const [closedPayload, resolvedPayload, failedPayload] = await Promise.all([
        fetchJson("/api-gateway/incidents/metadata?limit=120&status=closed"),
        fetchJson("/api-gateway/incidents/metadata?limit=120&status=resolved"),
        fetchJson("/api-gateway/incidents/metadata?limit=120&status=failed"),
      ]);
      const closedRows = Array.isArray(unwrap(closedPayload)?.rows) ? unwrap(closedPayload).rows : [];
      const resolvedRows = Array.isArray(unwrap(resolvedPayload)?.rows) ? unwrap(resolvedPayload).rows : [];
      const failedRows = Array.isArray(unwrap(failedPayload)?.rows) ? unwrap(failedPayload).rows : [];
      const merged = [...closedRows, ...resolvedRows, ...failedRows];
      const deduped = [];
      const seen = new Set();
      merged.forEach((row) => {
        const key = String(row?.incident_id || row?.id || "").trim();
        if (!key || seen.has(key)) {
          return;
        }
        seen.add(key);
        deduped.push(row);
      });
      setClosedIncidents({ loading: false, rows: deduped, error: "" });
    } catch (error) {
      setClosedIncidents({ loading: false, rows: [], error: error.message });
    }
  }

  async function refreshApprovalDrivenViews(incidentId = "") {
    const normalizedIncidentId = String(incidentId || "").trim();
    const tasks = [
      loadRecentAlerts(),
      loadIncidentMetadata(),
      loadGatewayRecent(),
      loadGatewaySummary(),
      loadClosedIncidents(),
    ];

    if (selectedAlertId) {
      tasks.push(loadAlertDetails(selectedAlertId));
      tasks.push(loadSelectedAlertDocumentLinks(selectedAlertId));
    }

    if (selectedApprovalIncidentId && (!normalizedIncidentId || selectedApprovalIncidentId === normalizedIncidentId)) {
      tasks.push(loadApprovalIncidentContext(selectedApprovalIncidentId));
    }

    await Promise.all(tasks);
  }

  function refreshApprovalDrivenViewsSoon(incidentId = "") {
    window.setTimeout(() => {
      refreshApprovalDrivenViews(incidentId);
    }, 1200);
  }

  async function loadFlows() {
    setFlows((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const payload = await fetchJson("/api-gateway/sample/flows");
      const data = unwrap(payload);
      const rows = data?.flows || [];
      const normalizedRows = Array.isArray(rows) ? rows : [];
      const firstFlowId = normalizedRows[0]?.id || normalizedRows[0]?.flow_id;
      if (firstFlowId && !selectedFlow) {
        setSelectedFlow(firstFlowId);
      }
      setFlows({ loading: false, rows: normalizedRows, error: "" });
    } catch (error) {
      setFlows({ loading: false, rows: [], error: error.message });
    }
  }

  async function loadGatewaySummary() {
    setGatewaySummary((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const payload = await fetchJson("/api-gateway/observability/summary");
      setGatewaySummary({ loading: false, data: payload || {}, error: "" });
    } catch (error) {
      setGatewaySummary({ loading: false, data: {}, error: error.message });
    }
  }

  async function loadGatewayRecent() {
    setGatewayRecent((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const payload = await fetchJson("/api-gateway/observability/recent");
      const rows = payload?.events || [];
      setGatewayRecent({ loading: false, rows: Array.isArray(rows) ? rows : [], error: "" });
    } catch (error) {
      setGatewayRecent({ loading: false, rows: [], error: error.message });
    }
  }

  async function loadLandingPadRecent() {
    setLandingPadRecent((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const payload = await fetchJson("/api-gateway/landing-pad/recent?limit=50");
      const data = unwrap(payload);
      const rows = data?.rows || [];
      setLandingPadRecent({ loading: false, rows: Array.isArray(rows) ? rows : [], error: "" });
    } catch (error) {
      setLandingPadRecent({ loading: false, rows: [], error: error.message });
    }
  }

  async function loadRagDocs() {
    setRagDocs((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const payload = await fetchJson("/api-gateway/rag/documents");
      const rows = payload?.documents || payload?.data?.documents || [];
      setRagDocs({ loading: false, rows: Array.isArray(rows) ? rows : [], error: "" });
    } catch (error) {
      setRagDocs({ loading: false, rows: [], error: error.message });
    }
  }

  async function loadMonitorApplications() {
    try {
      const [onboardingPayload, monitoringPayload] = await Promise.all([
        fetchJson("/api-gateway/onboarding/state", authenticatedOptions()),
        fetchJson("/api-gateway/applications", authenticatedOptions()).catch(() => ({})),
      ]);
      const onboardingData = unwrap(onboardingPayload);
      const onboardingRows = Array.isArray(onboardingData?.rows) ? onboardingData.rows : [];
      const projects = onboardingRows
        .map((row) => extractOnboardingProjectName(row))
        .filter(Boolean);
      const monitoringRows = Array.isArray(unwrap(monitoringPayload)?.rows) ? unwrap(monitoringPayload).rows : [];
      const monitoringApplications = monitoringRows
        .map((row) => String(row?.name || row?.application || row?.project_name || "").trim())
        .filter(Boolean);
      const alertApplications = alerts.rows
        .flatMap((row) => {
          const labels = typeof row?.labels === "object" && row?.labels ? row.labels : {};
          const metadata = typeof row?.metadata === "object" && row?.metadata ? row.metadata : {};
          const base = [
            row?.application,
            row?.project_name,
            row?.project,
            row?.service,
            labels?.application,
            labels?.project,
            labels?.project_name,
            labels?.deployment,
            labels?.service,
            labels?.job,
            labels?.instance,
            metadata?.owner_team,
          ]
            .map((value) => String(value || "").trim())
            .filter(Boolean);
          if (isKaiopsCoreAlert(row)) {
            base.push("kaiops-core");
          }
          return base;
        })
        .filter(Boolean);
      const isDisplayableMonitorApp = (value) => {
        const normalized = String(value || "").trim();
        if (!normalized) {
          return false;
        }
        if (defaultMonitorApplications.includes(normalized)) {
          return true;
        }
        // Drop URLs, host:port exporter/instance targets, and raw infra job
        // names (node-exporter, blackbox, mysql, etc.) - keep only real
        // kaiops-* application/service names.
        if (/[:/]/.test(normalized)) {
          return false;
        }
        return /^kaiops(-|$)/i.test(normalized);
      };
      const unique = Array.from(
        new Set([...defaultMonitorApplications, ...projects, ...monitoringApplications, ...alertApplications].filter(isDisplayableMonitorApp)),
      );
      setMonitorApplications(unique.length ? unique : defaultMonitorApplications);
    } catch (_error) {
      setMonitorApplications(defaultMonitorApplications);
    }
  }

  async function searchGuidanceDocs() {
    const query = String(guidanceQuery || "").trim();
    if (!query) {
      setGuidanceState({ loading: false, rows: [], error: "Enter search text to find guidance." });
      return;
    }
    setGuidanceState({ loading: true, rows: [], error: "" });
    try {
      const params = new URLSearchParams({ query, limit: "8" });
      const payload = await fetchJson(`/api-gateway/rag/search?${params.toString()}`);
      const rows = payload?.matches || payload?.data?.matches || [];
      setGuidanceState({ loading: false, rows: Array.isArray(rows) ? rows : [], error: "" });
    } catch (error) {
      setGuidanceState({ loading: false, rows: [], error: error.message });
    }
  }

  async function reloadRagDocs() {
    try {
      await fetchJson("/api-gateway/rag/reload", authenticatedOptions({ method: "POST", body: JSON.stringify({}) }));
      await loadRagDocs();
    } catch (error) {
      setRagDocs((prev) => ({ ...prev, error: error.message }));
    }
  }

  async function submitAlert(event) {
    event.preventDefault();
    setSubmitState({ loading: true, result: null, error: "" });
    try {
      const payload = await fetchJson("/api-gateway/alerts", {
        method: "POST",
        body: JSON.stringify(form),
      });
      setSubmitState({ loading: false, result: payload, error: "" });
      await loadRecentAlerts();
    } catch (error) {
      setSubmitState({ loading: false, result: null, error: error.message });
    }
  }

  async function runWorkflow(flowId) {
    const normalized = String(flowId || "").trim();
    if (!normalized) {
      return;
    }
    setWorkflowState({ loading: true, result: null, error: "" });
    try {
      const payload = await fetchJson(`/api-gateway/sample/${normalized}/workflow`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setWorkflowState({ loading: false, result: payload, error: "" });
      await Promise.all([loadRecentAlerts(), loadGatewaySummary(), loadGatewayRecent(), loadIncidentMetadata(), loadClosedIncidents()]);
    } catch (error) {
      setWorkflowState({ loading: false, result: null, error: error.message });
    }
  }

  function adminHeaders() {
    const token = String(adminSession.accessToken || "").trim();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  function authenticatedOptions(options = {}) {
    const headers = adminHeaders();
    return {
      ...options,
      headers: {
        ...headers,
        ...(options.headers || {}),
      },
    };
  }

  async function adminLogin(event) {
    event.preventDefault();
    setAdminSession((current) => ({ ...current, loading: true, error: "" }));
    try {
      const response = await fetchJson("/api-gateway/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: String(adminAuthForm.username || "").trim(),
          password: String(adminAuthForm.password || ""),
          device: String(adminAuthForm.device || "react-ui").trim(),
        }),
      });
      setAdminSession({
        loading: false,
        accessToken: response?.access_token || "",
        refreshToken: response?.refresh_token || "",
        user: response?.user || null,
        error: "",
      });
    } catch (error) {
      setAdminSession((current) => ({ ...current, loading: false, error: error.message }));
    }
  }

  async function adminLogout() {
    const headers = adminHeaders();
    try {
      if (headers.Authorization) {
        await fetchJson("/api-gateway/auth/logout", { method: "POST", headers, body: JSON.stringify({}) });
      }
    } catch (_error) {
      // Ignore logout errors and clear local session regardless.
    }
    setAdminSession({ loading: false, accessToken: "", refreshToken: "", user: null, error: "" });
    setAdminUsers({ loading: false, rows: [], error: "" });
    setAdminEditUser({ id: null, username: "", email: "", first_name: "", last_name: "", role_id: 1, status: "active", is_active: true });
    setAdminResetPasswordForm({ user_id: null, new_password: "" });
    setActiveTab("home");
  }

  async function loadAdminUsersAndRoles() {
    const headers = adminHeaders();
    if (!headers.Authorization) {
      return;
    }
    setAdminUsers((current) => ({ ...current, loading: true, error: "" }));
    try {
      const [usersPayload, rolesPayload] = await Promise.all([
        fetchJson("/api-gateway/users?page=1&page_size=50", { headers }),
        fetchJson("/api-gateway/roles", { headers }),
      ]);
      const usersRows = usersPayload?.rows || usersPayload?.data?.rows || [];
      const rolesRows = rolesPayload?.data || rolesPayload || [];
      setAdminUsers({ loading: false, rows: Array.isArray(usersRows) ? usersRows : [], error: "" });
      setAdminRoles(Array.isArray(rolesRows) ? rolesRows : []);
    } catch (error) {
      setAdminUsers({ loading: false, rows: [], error: error.message });
    }
  }

  async function createAdminUser(event) {
    event.preventDefault();
    const headers = adminHeaders();
    if (!headers.Authorization) {
      setAdminUsers((current) => ({ ...current, error: "Admin login required." }));
      return;
    }
    setAdminUsers((current) => ({ ...current, loading: true, error: "" }));
    try {
      await fetchJson("/api-gateway/users", {
        method: "POST",
        headers,
        body: JSON.stringify({
          ...adminCreateUser,
          role_id: Number(adminCreateUser.role_id || 1),
        }),
      });
      setAdminCreateUser({
        username: "",
        email: "",
        password: "",
        first_name: "",
        last_name: "",
        role_id: 1,
        status: "active",
        is_active: true,
      });
      await loadAdminUsersAndRoles();
    } catch (error) {
      setAdminUsers((current) => ({ ...current, loading: false, error: error.message }));
    }
  }

  function selectAdminUserForEdit(row) {
    const selectedId = Number(row?.id || 0);
    if (!selectedId) {
      return;
    }
    setAdminEditUser({
      id: selectedId,
      username: String(row?.username || "").trim(),
      email: String(row?.email || "").trim(),
      first_name: String(row?.first_name || "").trim(),
      last_name: String(row?.last_name || "").trim(),
      role_id: Number(row?.role_id || 1),
      status: String(row?.status || "active").trim(),
      is_active: Boolean(row?.is_active),
    });
    setAdminResetPasswordForm((current) => ({ ...current, user_id: selectedId, new_password: "" }));
  }

  async function updateAdminUser(event) {
    event.preventDefault();
    const headers = adminHeaders();
    if (!headers.Authorization || !adminEditUser.id) {
      setAdminUsers((current) => ({ ...current, error: "Admin login and selected user are required." }));
      return;
    }
    setAdminUsers((current) => ({ ...current, loading: true, error: "" }));
    try {
      await fetchJson(`/api-gateway/users/${adminEditUser.id}`, {
        method: "PUT",
        headers,
        body: JSON.stringify({
          email: String(adminEditUser.email || "").trim(),
          first_name: String(adminEditUser.first_name || "").trim(),
          last_name: String(adminEditUser.last_name || "").trim(),
          role_id: Number(adminEditUser.role_id || 1),
          status: String(adminEditUser.status || "active").trim(),
          is_active: Boolean(adminEditUser.is_active),
        }),
      });
      await loadAdminUsersAndRoles();
    } catch (error) {
      setAdminUsers((current) => ({ ...current, loading: false, error: error.message }));
    }
  }

  async function resetAdminUserPassword(event) {
    event.preventDefault();
    const headers = adminHeaders();
    const selectedUserId = Number(adminResetPasswordForm.user_id || 0);
    if (!headers.Authorization || !selectedUserId) {
      setAdminUsers((current) => ({ ...current, error: "Select a user to reset password." }));
      return;
    }
    setAdminUsers((current) => ({ ...current, loading: true, error: "" }));
    try {
      await fetchJson(`/api-gateway/users/${selectedUserId}/reset-password`, {
        method: "PATCH",
        headers,
        body: JSON.stringify({ new_password: String(adminResetPasswordForm.new_password || "") }),
      });
      setAdminResetPasswordForm((current) => ({ ...current, new_password: "" }));
      await loadAdminUsersAndRoles();
    } catch (error) {
      setAdminUsers((current) => ({ ...current, loading: false, error: error.message }));
    }
  }

  function applyProjectOnboardingRow(row) {
    if (!row || typeof row !== "object") {
      return;
    }
    const projectPayload = row.project_payload && typeof row.project_payload === "object" ? row.project_payload : {};
    const connectivityPayload = row.connectivity_payload && typeof row.connectivity_payload === "object" ? row.connectivity_payload : {};
    const monitoring = extractMonitoringToolAndUrl(connectivityPayload);
    setSelectedOnboardingProject(String(row.project_name || projectPayload.name || "").trim());
    setOnboardingForm((curr) => ({
      ...curr,
      name: String(row.project_name || projectPayload.name || curr.name || "").trim(),
      owner_team: String(row.owner_team || projectPayload.owner_team || curr.owner_team || "").trim(),
      environment: String(row.environment || projectPayload.environment || curr.environment || "prod").trim(),
      region: String(row.region || projectPayload.region || curr.region || "").trim(),
      deployment_mode: String(connectivityPayload.deployment_mode || curr.deployment_mode || "on_prem").trim(),
      monitoring_tool: monitoring.tool,
      monitoring_url: monitoring.url,
      prometheus_url: monitoring.tool === "prometheus" ? monitoring.url : "",
      new_relic_url: monitoring.tool === "new_relic" ? monitoring.url : "",
      datadog_url: monitoring.tool === "datadog" ? monitoring.url : "",
      azure_subscription_id: String(connectivityPayload.azure_subscription_id || curr.azure_subscription_id || "").trim(),
      azure_resource_group: String(connectivityPayload.azure_resource_group || curr.azure_resource_group || "").trim(),
      azure_service_bus_namespace: String(connectivityPayload.azure_service_bus_namespace || curr.azure_service_bus_namespace || "").trim(),
      azure_service_bus_topic: String(connectivityPayload.azure_service_bus_topic || curr.azure_service_bus_topic || "").trim(),
      azure_service_bus_subscription: String(connectivityPayload.azure_service_bus_subscription || curr.azure_service_bus_subscription || "").trim(),
      azure_content_safety_enabled: Boolean(connectivityPayload.azure_content_safety_enabled ?? curr.azure_content_safety_enabled),
      azure_content_safety_endpoint: String(connectivityPayload.azure_content_safety_endpoint || curr.azure_content_safety_endpoint || "").trim(),
      assignment_project: String(row.project_name || projectPayload.name || curr.name || "").trim(),
    }));
    setOnboardingProjectMode("existing");
    setExistingRulePipelineForm((curr) => ({
      ...curr,
      platform: monitoring.tool,
      connection_url: monitoring.url,
    }));
    setNewRulePipelineForm((curr) => ({
      ...curr,
      selected_tool: monitoring.tool,
    }));
    setOnboardingSourceDocs({ loading: false, rows: [], error: "" });
  }

  function resetNewProjectOnboardingDraft() {
    setSelectedOnboardingProject("");
    setOnboardingWorkflowSteps([]);
    setOnboardingGeneratedDocs([]);
    setOnboardingSourceDocs({ loading: false, rows: [], error: "" });
    setOnboardingDocApprovalState({ loading: false, error: "", success: "", approved: false });
    setOnboardingForm((curr) => ({
      ...curr,
      name: "",
      owner_team: "",
      environment: "prod",
      region: curr.region || "us-east-1",
      monitoring_tool: curr.monitoring_tool || "prometheus",
      monitoring_url: "",
      prometheus_url: "",
      new_relic_url: "",
      datadog_url: "",
      assignment_username: "",
      assignment_project: "",
      onboarding_path: "existing_monitoring",
      start_rule_onboarding: false,
      rule_onboarding_plain_language: "",
    }));
  }

  function currentOnboardedApplicationName() {
    return String(selectedOnboardingProject || onboardingForm.name || monitoringAppForm.name || "").trim();
  }

  function findMonitoringApplicationForName(name) {
    const normalized = String(name || "").trim().toLowerCase();
    if (!normalized) {
      return null;
    }
    return (Array.isArray(monitoringApps.rows) ? monitoringApps.rows : []).find((row) => {
      const candidates = [
        row?.id,
        row?.name,
        row?.application,
        row?.project_name,
        row?.service,
      ].map((value) => String(value || "").trim().toLowerCase()).filter(Boolean);
      return candidates.some((candidate) => candidate === normalized || candidate.includes(normalized) || normalized.includes(candidate));
    }) || null;
  }

  async function openOnboardedApplicationDashboard(url = "") {
    const appName = currentOnboardedApplicationName();
    if (appName) {
      setMonitorApplications((current) => current.includes(appName) ? current : [appName, ...current]);
      setApplicationToMonitor(appName);
      const row = findMonitoringApplicationForName(appName);
      const appId = String(row?.id || "").trim();
      if (appId) {
        setSelectedMonitoringAppId(appId);
        loadMonitoringApplicationDetails(appId);
      }
    }
    setDashboardAlertFocus("all");
    setDashboardAlertQuery("");
    setActiveTab("home");
    if (url && typeof window !== "undefined") {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  }

  async function ingestGeneratedOnboardingDocuments(documents) {
    const rows = Array.isArray(documents) ? documents : [];
    if (!rows.length) {
      return { total: 0, ingested: 0, failed: 0 };
    }

    let ingested = 0;
    let failed = 0;
    for (const row of rows) {
      try {
        await fetchJson("/api-gateway/rag/documents", authenticatedOptions({
          method: "POST",
          body: JSON.stringify(row),
        }));
        ingested += 1;
      } catch (_error) {
        failed += 1;
      }
    }
    if (ingested > 0) {
      await loadRagDocs();
    }
    return { total: rows.length, ingested, failed };
  }

  async function approveGeneratedOnboardingDocuments() {
    const docs = Array.isArray(onboardingGeneratedDocs) ? onboardingGeneratedDocs : [];
    if (!docs.length) {
      return;
    }
    setOnboardingDocApprovalState({ loading: true, error: "", success: "", approved: false });
    try {
      const summary = await ingestGeneratedOnboardingDocuments(docs);
      if (summary.failed > 0) {
        setOnboardingDocApprovalState({
          loading: false,
          error: `Approved, but ${summary.failed} document(s) failed to ingest.`,
          success: "",
          approved: false,
        });
        return;
      }
      setOnboardingDocApprovalState({
        loading: false,
        error: "",
        success: `Approved and ingested ${summary.ingested}/${summary.total} document(s).`,
        approved: true,
      });
      setOnboardingReviewAck((current) => ({ ...current, docs: true }));
      setOnboardingState((current) => ({ ...current, success: `Project onboarding saved. Documents approved: ${summary.ingested}/${summary.total}.` }));
      const appName = currentOnboardedApplicationName();
      if (appName) {
        setMonitorApplications((current) => current.includes(appName) ? current : [appName, ...current]);
        setApplicationToMonitor(appName);
      }
      setProjectSetupStep("status");
    } catch (error) {
      setOnboardingDocApprovalState({ loading: false, error: error.message, success: "", approved: false });
    }
  }

  const onboardingDerivedRequirements = useMemo(() => {
    const rows = Array.isArray(onboardingSourceDocs.rows) ? onboardingSourceDocs.rows : [];
    const merged = [];
    rows.forEach((row) => {
      (Array.isArray(row?.derived_requirements) ? row.derived_requirements : []).forEach((item) => {
        const token = String(item || "").trim();
        if (token && !merged.some((existing) => existing.toLowerCase() === token.toLowerCase())) {
          merged.push(token);
        }
      });
    });
    return merged;
  }, [onboardingSourceDocs.rows]);

  const onboardingKnowledgePack = knowledgePackState.draft?.knowledge_pack || knowledgePackState.draft || null;
  const onboardingKnowledgeFacts = onboardingKnowledgePack?.facts || {};
  const onboardingKnowledgeValidation = onboardingKnowledgePack?.validation || {};
  const KNOWLEDGE_LIST_FACTS = new Set(["dependencies", "alert_patterns", "commands", "rollback_plan", "validation_checks"]);
  const KNOWLEDGE_FACT_LABELS = {
    service: "Service",
    environment: "Environment",
    owner_team: "Owner team",
    dependencies: "Dependencies",
    alert_patterns: "Alert patterns",
    commands: "Commands or queries",
    rollback_plan: "Rollback or failback",
    validation_checks: "Validation checks",
  };
  const KNOWLEDGE_FACT_HINTS = {
    dependencies: "Example: mysql, redis, rabbitmq, kafka",
    commands: "Example: kubectl logs deployment/service -n prod",
    rollback_plan: "Example: rollback deployment to previous version and restore config",
    validation_checks: "Example: verify /health, Prometheus target up, and error rate recovered",
    alert_patterns: "Example: alert when exporter is down for 5m",
    owner_team: "Example: platform-ops",
  };

  function normalizeKnowledgeCorrectionValue(key, value) {
    const text = String(value || "").trim();
    if (!text) {
      return KNOWLEDGE_LIST_FACTS.has(key) ? [] : "";
    }
    if (KNOWLEDGE_LIST_FACTS.has(key)) {
      return text.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
    }
    return text;
  }

  const correctedKnowledgeFacts = useMemo(() => {
    const next = {};
    Object.entries(onboardingKnowledgeFacts).forEach(([key, fact]) => {
      const correction = knowledgePackCorrections[key];
      const hasCorrection = String(correction || "").trim().length > 0;
      next[key] = hasCorrection
        ? {
          ...(fact || {}),
          value: normalizeKnowledgeCorrectionValue(key, correction),
          confidence: 0.95,
          status: "accepted",
          sources: [...(Array.isArray(fact?.sources) ? fact.sources : []), "user-confirmed"],
        }
        : fact;
    });
    return next;
  }, [knowledgePackCorrections, onboardingKnowledgeFacts]);
  const knowledgeReviewFields = useMemo(
    () => Object.entries(correctedKnowledgeFacts).filter(([, fact]) => {
      const value = fact?.value;
      const empty = Array.isArray(value) ? value.length === 0 : !String(value || "").trim();
      return empty || Number(fact?.confidence || 0) < 0.78 || String(fact?.status || "") === "needs_review";
    }),
    [correctedKnowledgeFacts],
  );
  const correctedKnowledgeConfidence = useMemo(() => {
    const rows = Object.values(correctedKnowledgeFacts);
    if (!rows.length) {
      return Number(onboardingKnowledgeValidation.overall_confidence || 0);
    }
    return rows.reduce((sum, fact) => sum + Number(fact?.confidence || 0), 0) / rows.length;
  }, [correctedKnowledgeFacts, onboardingKnowledgeValidation.overall_confidence]);

  function buildKnowledgePackPayload(rows = onboardingSourceDocs.rows) {
    const validRows = (Array.isArray(rows) ? rows : []).filter((row) => String(row?.text || "").trim() && !String(row?.warning || "").trim());
    return {
      service: String(onboardingForm.name || monitoringAppForm.name || "kaiops-project").trim(),
      environment: String(onboardingForm.environment || monitoringAppForm.environment || "prod").trim(),
      owner_team: String(onboardingForm.owner_team || monitoringAppForm.owner_team || "platform-ops").trim(),
      documents: validRows.map((row) => ({
        name: String(row?.name || "uploaded-document").trim(),
        category: String(row?.category || "knowledge_pack").trim(),
        text: String(row?.text || ""),
        excerpt: String(row?.excerpt || ""),
      })),
    };
  }

  async function draftKnowledgePack(rows = onboardingSourceDocs.rows) {
    const payload = buildKnowledgePackPayload(rows);
    if (!payload.documents.length) {
      setKnowledgePackState({ loading: false, draft: null, error: "", success: "", approved: false });
      setKnowledgePackCorrections({});
      return null;
    }
    setKnowledgePackState((current) => ({ ...current, loading: true, error: "", success: "", approved: false }));
    try {
      const response = unwrap(await fetchJson("/api-gateway/knowledge-pack/draft", authenticatedOptions({
        method: "POST",
        body: JSON.stringify(payload),
      })));
      setKnowledgePackCorrections({});
      setKnowledgePackState({ loading: false, draft: response?.knowledge_pack ? response : { knowledge_pack: response }, error: "", success: "", approved: false });
      return response;
    } catch (error) {
      setKnowledgePackState((current) => ({ ...current, loading: false, error: error.message, success: "", approved: false }));
      return null;
    }
  }

  async function approveKnowledgePack() {
    const payload = buildKnowledgePackPayload(onboardingSourceDocs.rows);
    if (!payload.documents.length) {
      setKnowledgePackState((current) => ({ ...current, error: "Upload at least one knowledge document before approval.", success: "" }));
      return;
    }
    setKnowledgePackState((current) => ({ ...current, loading: true, error: "", success: "" }));
    try {
      const acceptedFacts = Object.fromEntries(
        Object.entries(correctedKnowledgeFacts).map(([key, fact]) => [key, fact?.value]),
      );
      const response = unwrap(await fetchJson("/api-gateway/knowledge-pack/approve", authenticatedOptions({
        method: "POST",
        body: JSON.stringify({
          ...payload,
          accepted_facts: acceptedFacts,
          approved_by: currentRole || "administrator",
        }),
      })));
      setKnowledgePackState({
        loading: false,
        draft: response?.knowledge_pack ? response : { knowledge_pack: response },
        error: "",
        success: "Service Knowledge approved and saved to Alert Knowledge. Next, click Generate Documents & Rules to create reviewable artifacts.",
        approved: true,
      });
      setOnboardingReviewAck((current) => ({ ...current, docs: true }));
    } catch (error) {
      setKnowledgePackState((current) => ({ ...current, loading: false, error: error.message, success: "", approved: false }));
    }
  }

  function buildServiceKnowledgeGeneratedDocs({ projectName, selectedTool }) {
    if (!onboardingKnowledgePack || !onboardingSourceDocRows.length) {
      return [];
    }
    const factValue = (key, fallback = "") => {
      const value = correctedKnowledgeFacts?.[key]?.value;
      return value == null || value === "" ? fallback : value;
    };
    const asList = (value) => Array.isArray(value) ? value.filter((item) => String(item || "").trim()) : [value].filter((item) => String(item || "").trim());
    const service = String(factValue("service", projectName || onboardingForm.name || "service")).trim();
    const environment = String(factValue("environment", onboardingForm.environment || "prod")).trim();
    const owner = String(factValue("owner_team", onboardingForm.owner_team || "platform-ops")).trim();
    const alertPatterns = asList(factValue("alert_patterns", []));
    const dependencies = asList(factValue("dependencies", []));
    const commands = asList(factValue("commands", []));
    const rollback = asList(factValue("rollback_plan", []));
    const checks = asList(factValue("validation_checks", []));
    const sourceLines = onboardingSourceDocRows.map((row) => `- ${String(row?.name || "service-knowledge").trim()}: ${String(row?.excerpt || "").trim()}`).join("\n");
    const bulletSection = (title, rows, empty = "Not provided") => `${title}:\n${rows.length ? rows.map((item) => `- ${item}`).join("\n") : `- ${empty}`}`;
    const metadata = {
      project_name: String(projectName || service).trim(),
      owner_team: owner,
      environment,
      selected_monitoring_tool: String(selectedTool || onboardingForm.monitoring_tool || "prometheus").trim(),
      source_system: "service-knowledge",
      knowledge_confidence: String(correctedKnowledgeConfidence || ""),
    };
    return [
      {
        kind: "runbook",
        alert_id: `${service}-service-knowledge-runbook`,
        alert_type: "service-knowledge-onboarding",
        severity: "high",
        title: `${service} Service Knowledge Runbook`,
        summary: "Generated from uploaded Service Knowledge for triage, RCA, and remediation.",
        content: [
          `Service ${service} in ${environment}.`,
          bulletSection("Alert patterns", alertPatterns),
          bulletSection("Dependencies", dependencies),
          bulletSection("Validation checks", checks),
          bulletSection("Rollback plan", rollback),
          "Source evidence:",
          sourceLines || "- Uploaded Service Knowledge",
        ].join("\n\n"),
        services: [service],
        deployment: environment,
        dependencies,
        commands,
        queries: checks,
        recommended_action: "Use this runbook during alert triage and update it after the first live incident.",
        source_system: "service-knowledge",
        resolved_by: owner,
        metadata,
      },
      {
        kind: "incident",
        alert_id: `${service}-service-knowledge-incident`,
        alert_type: "service-knowledge-baseline",
        severity: "warning",
        title: `${service} Service Knowledge Incident Baseline`,
        summary: "Incident baseline generated from uploaded Service Knowledge.",
        content: [
          `Baseline incident guidance for ${service}.`,
          bulletSection("Expected alert patterns", alertPatterns),
          bulletSection("Known dependencies", dependencies),
          bulletSection("Evidence", [sourceLines].filter(Boolean), "Uploaded Service Knowledge"),
        ].join("\n\n"),
        services: [service],
        deployment: environment,
        source_system: "service-knowledge",
        resolved_by: owner,
        metadata,
      },
    ];
  }

  async function handleOnboardingSourceDocuments(files, category = "other") {
    const rows = Array.from(files || []);
    if (!rows.length) {
      return;
    }
    setOnboardingSourceDocs((current) => ({ ...current, loading: true, error: "" }));
    try {
      const parsedRows = await Promise.all(rows.map(async (file) => {
        const fileName = String(file?.name || "uploaded-document").trim() || "uploaded-document";
        const extension = fileName.includes(".") ? fileName.split(".").pop().toLowerCase() : "";
        if (!ONBOARDING_SOURCE_DOC_EXTENSIONS.has(extension)) {
          return {
            category,
            name: fileName,
            size: Number(file?.size || 0),
            text: "",
            excerpt: "",
            derived_requirements: [],
            warning: `Unsupported file type .${extension || "unknown"}. Use text-based docs such as .md, .txt, .json, .csv, .yaml.`,
          };
        }
        const text = await file.text();
        return {
          category,
          name: fileName,
          size: Number(file?.size || 0),
          text,
          excerpt: summarizeUploadedDocument(text),
          derived_requirements: deriveMonitoringRequirementsFromDocument(fileName, text),
          warning: "",
        };
      }));
      const existingRows = Array.isArray(onboardingSourceDocs.rows) ? onboardingSourceDocs.rows : [];
      const retainedRows = existingRows.filter((row) => String(row?.category || "other") !== category);
      const nextRows = [...retainedRows, ...parsedRows];
      setOnboardingSourceDocs({ loading: false, rows: nextRows, error: "" });
      await draftKnowledgePack(nextRows);
      const derived = parsedRows.flatMap((row) => (Array.isArray(row.derived_requirements) ? row.derived_requirements : []));
      if (derived.length) {
        const manual = String(onboardingForm.rule_onboarding_plain_language || "")
          .split(/\r?\n/)
          .map((line) => line.trim())
          .filter(Boolean);
        const combined = [...manual, ...derived].filter(
          (line, index, array) => array.findIndex((item) => item.toLowerCase() === line.toLowerCase()) === index,
        );
        const nextText = combined.join("\n");
        setOnboardingForm((curr) => ({ ...curr, rule_onboarding_plain_language: nextText }));
        setNewRulePipelineForm((curr) => ({ ...curr, requirements_text: nextText }));
      }
    } catch (error) {
      setOnboardingSourceDocs((current) => ({
        loading: false,
        rows: Array.isArray(current?.rows) ? current.rows : [],
        error: String(error?.message || "Failed to read uploaded documents."),
      }));
    }
  }

  async function handleAlertKnowledgeSourceDocument(files) {
    const file = Array.from(files || [])[0];
    if (!file) {
      return;
    }
    const fileName = String(file?.name || "uploaded-document").trim() || "uploaded-document";
    const extension = fileName.includes(".") ? fileName.split(".").pop().toLowerCase() : "";
    setAlertKnowledgeSourceDoc((current) => ({ ...current, loading: true, error: "" }));
    try {
      if (!ONBOARDING_SOURCE_DOC_EXTENSIONS.has(extension)) {
        setAlertKnowledgeSourceDoc({
          loading: false,
          name: fileName,
          size: Number(file?.size || 0),
          text: "",
          excerpt: "",
          error: `Unsupported file type .${extension || "unknown"}. Upload a text-based file such as .md, .txt, .json, .csv, .yaml, or .log.`,
        });
        return;
      }
      const text = await file.text();
      const excerpt = summarizeUploadedDocument(text);
      const derivedRequirements = deriveMonitoringRequirementsFromDocument(fileName, text);
      setAlertKnowledgeSourceDoc({
        loading: false,
        name: fileName,
        size: Number(file?.size || 0),
        text,
        excerpt,
        error: "",
      });
      if (!String(alertKnowledgePrompt || "").trim() && derivedRequirements.length) {
        setAlertKnowledgePrompt(derivedRequirements.slice(0, 6).join("\n"));
      }
    } catch (error) {
      setAlertKnowledgeSourceDoc({
        loading: false,
        name: fileName,
        size: Number(file?.size || 0),
        text: "",
        excerpt: "",
        error: String(error?.message || "Failed to read the uploaded alert knowledge document."),
      });
    }
  }

  function buildAlertKnowledgePromptInput() {
    const prompt = String(alertKnowledgePrompt || "").trim();
    const sourceText = String(alertKnowledgeSourceDoc?.text || "").trim();
    if (!sourceText) {
      return prompt;
    }
    const sourceName = String(alertKnowledgeSourceDoc?.name || "uploaded alert knowledge document").trim();
    const sourceExcerpt = String(alertKnowledgeSourceDoc?.excerpt || "").trim();
    const sourceBlock = [
      `Supporting document: ${sourceName}`,
      sourceExcerpt ? `Extracted summary: ${sourceExcerpt}` : "",
      "Document content:",
      sourceText.slice(0, 12000),
    ].filter(Boolean).join("\n");
    return [prompt, sourceBlock].filter(Boolean).join("\n\n");
  }

  function clearAlertKnowledgeSourceDocument() {
    setAlertKnowledgeSourceDoc({ loading: false, name: "", size: 0, text: "", excerpt: "", error: "" });
  }

  function applyUploadedDocumentsToRuleIntent() {
    if (!onboardingDerivedRequirements.length) {
      return;
    }
    const manual = String(onboardingForm.rule_onboarding_plain_language || "").trim();
    const combined = [
      ...manual.split(/\r?\n/).map((line) => line.trim()).filter(Boolean),
      ...onboardingDerivedRequirements,
    ].filter((line, index, array) => array.findIndex((item) => item.toLowerCase() === line.toLowerCase()) === index);
    const nextText = combined.join("\n");
    setOnboardingForm((curr) => ({ ...curr, rule_onboarding_plain_language: nextText }));
    setNewRulePipelineForm((curr) => ({ ...curr, requirements_text: nextText }));
  }

  function openRuleWorkflowEditor(row) {
    const connectivityPayload = row?.connectivity_payload && typeof row.connectivity_payload === "object" ? row.connectivity_payload : {};
    const workflowId = String(connectivityPayload.workflow_id || "").trim();
    const resultPayload = connectivityPayload.result && typeof connectivityPayload.result === "object" ? connectivityPayload.result : {};
    setOnboardingRuleEditor({
      workflow_id: workflowId,
      project_name: String(row?.project_name || "").trim(),
      payload_json: JSON.stringify(resultPayload, null, 2),
    });
    setOnboardingRuleEditorState({ loading: false, error: "", success: "" });
    setOnboardingRuleLookup((current) => ({ ...current, workflow_id: workflowId }));
  }

  async function saveRuleWorkflowEditor(event) {
    event.preventDefault();
    const workflowId = String(onboardingRuleEditor.workflow_id || "").trim();
    const projectName = String(onboardingRuleEditor.project_name || onboardingForm.name || "").trim();
    if (!workflowId || !projectName) {
      setOnboardingRuleEditorState({ loading: false, error: "Workflow ID and project name are required.", success: "" });
      return;
    }
    setOnboardingRuleEditorState({ loading: true, error: "", success: "" });
    try {
      const parsedResult = JSON.parse(String(onboardingRuleEditor.payload_json || "{}").trim() || "{}");
      await fetchJson(`/api-gateway/onboarding/rules/pipeline/${encodeURIComponent(workflowId)}`, authenticatedOptions({
        method: "PUT",
        body: JSON.stringify({
          project_name: projectName,
          result: parsedResult,
          status: "updated",
        }),
      }));
      await loadOnboardingAdminData();
      setOnboardingRuleEditorState({ loading: false, error: "", success: "Rule workflow updated." });
    } catch (error) {
      setOnboardingRuleEditorState({ loading: false, error: error.message, success: "" });
    }
  }

  async function deleteRuleWorkflow(workflowId) {
    const normalizedWorkflowId = String(workflowId || "").trim();
    if (!normalizedWorkflowId) {
      return;
    }
    setOnboardingRuleEditorState({ loading: true, error: "", success: "" });
    try {
      await fetchJson(`/api-gateway/onboarding/rules/pipeline/${encodeURIComponent(normalizedWorkflowId)}`, authenticatedOptions({
        method: "DELETE",
      }));
      await loadOnboardingAdminData();
      setOnboardingRuleEditor((current) => (
        String(current.workflow_id || "") === normalizedWorkflowId
          ? { workflow_id: "", project_name: "", payload_json: "" }
          : current
      ));
      setOnboardingRuleEditorState({ loading: false, error: "", success: "Rule workflow deleted." });
    } catch (error) {
      setOnboardingRuleEditorState({ loading: false, error: error.message, success: "" });
    }
  }

  async function deleteProjectOnboarding(projectName) {
    const normalizedProject = String(projectName || "").trim();
    if (!normalizedProject) {
      return;
    }
    setOnboardingState((current) => ({ ...current, loading: true, error: "", success: "" }));
    try {
      await fetchJson(`/api-gateway/onboarding/state/${encodeURIComponent(normalizedProject)}`, authenticatedOptions({
        method: "DELETE",
      }));
      await loadOnboardingAdminData();
      await refreshViewsAfterSubmit();
      setOnboardingState((current) => ({ ...current, success: "Project onboarding deleted." }));
    } catch (error) {
      setOnboardingState((current) => ({ ...current, loading: false, error: error.message, success: "" }));
    }
  }

  async function loadOnboardingAdminData() {
    setOnboardingState((current) => ({ ...current, loading: true, error: "", success: "" }));
    try {
      const [connectivityPayload, statePayload] = await Promise.all([
        fetchJson("/api-gateway/onboarding/connectivity", authenticatedOptions()),
        fetchJson("/api-gateway/onboarding/state", authenticatedOptions()),
      ]);
      const connectivity = connectivityPayload?.data?.connectivity || connectivityPayload?.connectivity || {};
      const rows = statePayload?.data?.rows || statePayload?.rows || [];
      const project = connectivity?.project || {};
      const allRows = Array.isArray(rows) ? rows : [];
      const projectRows = allRows.filter((row) => extractOnboardingProjectName(row));
      const preferredProjectName = String(project?.name || selectedOnboardingProject || "").trim();
      const preferredProjectRow = projectRows.find((row) => extractOnboardingProjectName(row) === preferredProjectName)
        || projectRows[0]
        || null;
      const monitoring = extractMonitoringToolAndUrl(connectivity);
      setOnboardingForm((curr) => ({
        ...curr,
        name: String(project?.name || curr.name || "").trim(),
        owner_team: String(project?.owner_team || curr.owner_team || "").trim(),
        environment: String(project?.environment || curr.environment || "prod").trim(),
        region: String(project?.region || curr.region || "").trim(),
        deployment_mode: String(connectivity?.deployment_mode || curr.deployment_mode || "on_prem").trim(),
        monitoring_tool: monitoring.tool,
        monitoring_url: monitoring.url,
        prometheus_url: monitoring.tool === "prometheus" ? monitoring.url : "",
        new_relic_url: monitoring.tool === "new_relic" ? monitoring.url : "",
        datadog_url: monitoring.tool === "datadog" ? monitoring.url : "",
        azure_subscription_id: String(connectivity?.azure_subscription_id || curr.azure_subscription_id || "").trim(),
        azure_resource_group: String(connectivity?.azure_resource_group || curr.azure_resource_group || "").trim(),
        azure_service_bus_namespace: String(connectivity?.azure_service_bus_namespace || curr.azure_service_bus_namespace || "").trim(),
        azure_service_bus_topic: String(connectivity?.azure_service_bus_topic || curr.azure_service_bus_topic || "").trim(),
        azure_service_bus_subscription: String(connectivity?.azure_service_bus_subscription || curr.azure_service_bus_subscription || "").trim(),
        azure_content_safety_enabled: Boolean(connectivity?.azure_content_safety_enabled ?? curr.azure_content_safety_enabled),
        azure_content_safety_endpoint: String(connectivity?.azure_content_safety_endpoint || curr.azure_content_safety_endpoint || "").trim(),
        assignment_project: String(project?.name || curr.name || "").trim(),
      }));
      setExistingRulePipelineForm((curr) => ({ ...curr, platform: monitoring.tool, connection_url: monitoring.url }));
      setNewRulePipelineForm((curr) => ({ ...curr, selected_tool: monitoring.tool }));
      if (preferredProjectRow && onboardingProjectMode !== "new") {
        applyProjectOnboardingRow(preferredProjectRow);
      } else if (String(project?.name || "").trim()) {
        setSelectedOnboardingProject(String(project.name).trim());
      }
      setOnboardingState({ loading: false, connectivity, rows: allRows, error: "", success: "" });
    } catch (error) {
      setOnboardingState({ loading: false, connectivity: {}, rows: [], error: error.message, success: "" });
    }
  }

  async function saveOnboardingConnectivity(event) {
    event.preventDefault();
    const pendingApprovalDocs = Array.isArray(onboardingGeneratedDocs) ? onboardingGeneratedDocs : [];
    const hasPendingApproval = pendingApprovalDocs.length > 0 && !Boolean(onboardingDocApprovalState.approved);
    if (hasPendingApproval) {
      setOnboardingState((current) => ({
        ...current,
        loading: false,
        error: "Please review and approve generated documents before creating/updating another project.",
        success: "",
      }));
      return;
    }
    setOnboardingState((current) => ({ ...current, loading: true, error: "", success: "" }));
    setOnboardingGeneratedDocs([]);
    setOnboardingDocApprovalState({ loading: false, error: "", success: "", approved: false });
    setOnboardingReviewAck({ rules: false, docs: false, metadata: false });
    try {
      const selectedMonitoringTool = String(onboardingForm.monitoring_tool || "prometheus").trim().toLowerCase();
      const monitoringUrl = simplifyMonitoringUrl(onboardingForm.monitoring_url);
      const username = String(onboardingForm.assignment_username || "").trim();
      const assignmentProject = String(onboardingForm.name || "").trim();
      const userAssignments = username && assignmentProject ? { [username]: [assignmentProject] } : {};
      const monitoringUrls = {
        prometheus_url: selectedMonitoringTool === "prometheus" ? monitoringUrl : "",
        new_relic_url: selectedMonitoringTool === "new_relic" ? monitoringUrl : "",
        datadog_url: selectedMonitoringTool === "datadog" ? monitoringUrl : "",
      };
      const payload = {
        project: {
          name: String(onboardingForm.name || "").trim(),
          owner_team: String(onboardingForm.owner_team || "").trim(),
          environment: String(onboardingForm.environment || "prod").trim(),
          region: String(onboardingForm.region || "").trim(),
        },
        deployment_mode: String(onboardingForm.deployment_mode || "on_prem").trim(),
        ...monitoringUrls,
        azure_subscription_id: String(onboardingForm.azure_subscription_id || "").trim(),
        azure_resource_group: String(onboardingForm.azure_resource_group || "").trim(),
        azure_service_bus_namespace: String(onboardingForm.azure_service_bus_namespace || "").trim(),
        azure_service_bus_topic: String(onboardingForm.azure_service_bus_topic || "").trim(),
        azure_service_bus_subscription: String(onboardingForm.azure_service_bus_subscription || "").trim(),
        azure_content_safety_enabled: Boolean(onboardingForm.azure_content_safety_enabled),
        azure_content_safety_endpoint: String(onboardingForm.azure_content_safety_endpoint || "").trim(),
        user_assignments: userAssignments,
        active_provider: selectedMonitoringTool,
      };

      const onboardingPath = String(onboardingForm.onboarding_path || "existing_monitoring").trim().toLowerCase();
      const plainLanguageRequirements = [
        ...String(onboardingForm.rule_onboarding_plain_language || "")
          .split(/\r?\n/)
          .map((line) => line.trim())
          .filter(Boolean),
        ...onboardingDerivedRequirements,
      ].filter((line, index, array) => array.findIndex((item) => item.toLowerCase() === line.toLowerCase()) === index);
      const shouldStartRuleOnboarding = plainLanguageRequirements.length > 0;

      const response = await fetchJson("/api-gateway/onboarding/complete", authenticatedOptions({
        method: "POST",
        body: JSON.stringify({
          project_mode: onboardingProjectMode === "new" ? "new" : "existing",
          onboarding_path: onboardingPath,
          connectivity: payload,
          start_rules_onboarding: shouldStartRuleOnboarding,
          plain_language_requirements: plainLanguageRequirements,
          source_documents: onboardingSourceDocRows.map((row) => ({
            name: String(row?.name || "uploaded-document").trim() || "uploaded-document",
            kind: String(row?.category || classifyOnboardingDocumentType(row?.name, row?.text)).trim().toLowerCase() || "other",
            excerpt: String(row?.excerpt || "").trim(),
            content: String(row?.text || "").slice(0, 12000),
            size: Number(row?.size || 0),
          })),
          selected_monitoring_tool: selectedMonitoringTool,
          generate_documents: true,
        }),
      }));

      const completePayload = unwrap(response);
      const workflowSteps = Array.isArray(completePayload?.workflow_steps) ? completePayload.workflow_steps : [];
      const landingPadSummary = completePayload?.landing_pad_ingestion && typeof completePayload.landing_pad_ingestion === "object"
        ? completePayload.landing_pad_ingestion
        : {};
      setOnboardingWorkflowSteps(workflowSteps);
      setOnboardingLandingPadSummary(landingPadSummary);
      setOnboardingForm((curr) => ({
        ...curr,
        monitoring_tool: selectedMonitoringTool,
        monitoring_url: monitoringUrl,
        assignment_project: String(curr.name || "").trim(),
        ...monitoringUrls,
      }));

      const rulesOnboarding = completePayload?.rules_onboarding || {};
      if (rulesOnboarding?.started && rulesOnboarding?.result) {
        const ruleResult = rulesOnboarding.result;
        setOnboardingRuleRunState({ loading: false, result: ruleResult, error: "" });
        setOnboardingRuleLookup((current) => ({
          ...current,
          workflow_id: String(rulesOnboarding.workflow_id || ruleResult?.workflow_id || current.workflow_id || "").trim(),
        }));
      } else {
        setOnboardingRuleRunState((current) => ({ ...current, loading: false }));
      }
      const backendGeneratedDocs = Array.isArray(completePayload?.rag_documents) ? completePayload.rag_documents : [];
      const generatedDocs = backendGeneratedDocs.length
        ? backendGeneratedDocs
        : buildServiceKnowledgeGeneratedDocs({ projectName: payload.project.name, selectedTool: selectedMonitoringTool });
      setOnboardingGeneratedDocs(generatedDocs);

      setSelectedOnboardingProject(String(payload.project.name || "").trim());
      if (onboardingProjectMode === "new") {
        setOnboardingProjectMode("existing");
      }
      await loadOnboardingAdminData();
      const knowledgeAutoGenerated = onboardingSourceDocCount > 0
        ? await autoGenerateAlertKnowledgeFromSourceDocs({ projectName: payload.project.name, onboardingPath })
        : false;
      await refreshViewsAfterSubmit();
      setOnboardingState((current) => ({
        ...current,
        success: shouldStartRuleOnboarding
          ? generatedDocs.length
            ? `Workflow completed through step ${workflowSteps.length || 0}. Review generated documents and click Approve.`
            : onboardingSourceDocCount > 0
              ? `Workflow completed through step ${workflowSteps.length || 0}. Generated ${generatedDocs.length} Service Knowledge document(s) for review.`
              : `Workflow completed through step ${workflowSteps.length || 0}. No Service Knowledge file was uploaded.`
          : onboardingSourceDocCount > 0
            ? knowledgeAutoGenerated
              ? "Project onboarding saved. Alert Knowledge Onboarding draft was auto-generated from Service Knowledge."
              : "Project onboarding saved. Service Knowledge was detected, but Alert Knowledge auto-generation failed; use manual prompt flow below."
            : "Project onboarding saved. No Service Knowledge uploaded; continue with manual Alert Knowledge prompt and click Create Alert Onboarding Doc.",
      }));
      if (adminWorkspace === "project" && projectSetupStep === "setup") {
        setProjectSetupStep("docs_rules");
      }
      if (onboardingSourceDocCount === 0) {
        setAlertKnowledgeView("onboarding");
      }
    } catch (error) {
      setOnboardingState((current) => ({ ...current, loading: false, error: error.message, success: "" }));
      setOnboardingRuleRunState((current) => ({ ...current, loading: false }));
    }
  }

  function onboardingProjectSeed() {
    const projectName = String(selectedOnboardingProject || onboardingForm.name || "").trim();
    const selectedMonitoringTool = String(onboardingForm.monitoring_tool || "prometheus").trim().toLowerCase();
    return {
      project_name: projectName,
      description: "",
      business_unit: "",
      environment: String(onboardingForm.environment || "prod").trim().toLowerCase(),
      criticality: "high",
      sla: "",
      support_team: String(onboardingForm.owner_team || "").trim(),
      business_owner: "",
      technical_owner: "",
      technology_stack: [],
      cloud_provider: onboardingForm.deployment_mode === "azure_cloud" ? "azure" : "on_prem",
      region: String(onboardingForm.region || "").trim(),
      monitoring_platforms: MONITORING_TOOL_OPTIONS.includes(selectedMonitoringTool) ? [selectedMonitoringTool] : ["prometheus"],
      notification_platforms: ["slack", "teams", "pagerduty"],
    };
  }

  async function loadOnboardingRuleCapabilities() {
    setOnboardingRuleCapabilities((current) => ({ ...current, loading: true, error: "" }));
    try {
      const response = await fetchJson("/api-gateway/onboarding/rules/capabilities", authenticatedOptions());
      const payload = unwrap(response);
      const rows = Array.isArray(payload?.rows) ? payload.rows : [];
      setOnboardingRuleCapabilities({ loading: false, rows, error: "" });
    } catch (error) {
      setOnboardingRuleCapabilities({ loading: false, rows: [], error: error.message });
    }
  }

  async function runExistingRulePipeline(event) {
    event.preventDefault();
    setOnboardingRuleRunState({ loading: true, result: null, error: "" });
    try {
      let rulesToPush = [];
      const rawRules = String(existingRulePipelineForm.rules_json || "").trim();
      if (rawRules) {
        const parsed = JSON.parse(rawRules);
        if (!Array.isArray(parsed)) {
          throw new Error("Rules JSON must be an array of rule objects.");
        }
        rulesToPush = parsed;
      }

      const payload = {
        project: onboardingProjectSeed(),
        platform: String(existingRulePipelineForm.platform || "prometheus").trim(),
        mode: String(existingRulePipelineForm.mode || "bidirectional").trim(),
        rules_to_push: rulesToPush,
        connection_profile: {
          endpoint_url: String(existingRulePipelineForm.connection_url || "").trim(),
        },
      };

      const response = await fetchJson("/api-gateway/onboarding/rules/pipeline/existing", authenticatedOptions({
        method: "POST",
        body: JSON.stringify(payload),
      }));
      const result = unwrap(response);
      setOnboardingRuleRunState({ loading: false, result, error: "" });
      setOnboardingRuleLookup((current) => ({
        ...current,
        workflow_id: String(result?.workflow_id || current.workflow_id || "").trim(),
      }));
      await loadOnboardingAdminData();
    } catch (error) {
      setOnboardingRuleRunState({ loading: false, result: null, error: error.message });
    }
  }

  async function runNewRulePipeline(event) {
    event.preventDefault();
    setOnboardingRuleRunState({ loading: true, result: null, error: "" });
    try {
      const requirements = String(newRulePipelineForm.requirements_text || "")
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
      if (!requirements.length) {
        throw new Error("Provide at least one monitoring requirement.");
      }

      const selectedTool = String(newRulePipelineForm.selected_tool || onboardingForm.monitoring_tool || "prometheus").trim().toLowerCase();
      const targetPlatforms = MONITORING_TOOL_OPTIONS.includes(selectedTool) ? [selectedTool] : ["prometheus"];
      const discoveryInputs = {
        endpoint_url: simplifyMonitoringUrl(onboardingForm.monitoring_url),
        deployment_mode: String(onboardingForm.deployment_mode || "on_prem").trim(),
        environment: String(onboardingForm.environment || "prod").trim(),
        generated_from_plain_language: true,
      };

      const payload = {
        project: onboardingProjectSeed(),
        monitoring_requirements: requirements,
        target_platforms: targetPlatforms,
        discovery_inputs: discoveryInputs,
      };

      const response = await fetchJson("/api-gateway/onboarding/rules/pipeline/new", authenticatedOptions({
        method: "POST",
        body: JSON.stringify(payload),
      }));
      const result = unwrap(response);
      setOnboardingRuleRunState({ loading: false, result, error: "" });
      setOnboardingRuleLookup((current) => ({
        ...current,
        workflow_id: String(result?.workflow_id || current.workflow_id || "").trim(),
      }));
      await loadOnboardingAdminData();
    } catch (error) {
      setOnboardingRuleRunState({ loading: false, result: null, error: error.message });
    }
  }

  async function lookupOnboardingRuleWorkflow(event) {
    event.preventDefault();
    const workflowId = String(onboardingRuleLookup.workflow_id || "").trim();
    if (!workflowId) {
      setOnboardingRuleLookup((current) => ({ ...current, error: "Workflow ID is required." }));
      return;
    }
    setOnboardingRuleLookup((current) => ({ ...current, loading: true, result: null, error: "" }));
    try {
      const response = await fetchJson(`/api-gateway/onboarding/rules/pipeline/${encodeURIComponent(workflowId)}`, authenticatedOptions());
      const result = unwrap(response);
      setOnboardingRuleLookup((current) => ({ ...current, loading: false, result, error: "" }));
    } catch (error) {
      setOnboardingRuleLookup((current) => ({ ...current, loading: false, result: null, error: error.message }));
    }
  }

  function normalizeDocumentToken(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[\s_]+/g, "-")
      .replace(/-+/g, "-");
  }

  function collectDocumentTokens(...values) {
    const tokens = new Set();
    values.forEach((value) => {
      if (Array.isArray(value)) {
        value.forEach((item) => collectDocumentTokens(item).forEach((token) => tokens.add(token)));
        return;
      }
      const raw = String(value || "").trim();
      if (!raw) {
        return;
      }
      const normalizedRaw = normalizeDocumentToken(raw);
      if (normalizedRaw) {
        tokens.add(normalizedRaw);
      }
      raw
        .split(/[,;|\s]+/)
        .map(normalizeDocumentToken)
        .filter(Boolean)
        .forEach((token) => tokens.add(token));
    });
    return tokens;
  }

  function getAlertDocumentMatchContext(alertRow) {
    const labels = typeof alertRow?.labels === "object" && alertRow?.labels ? alertRow.labels : {};
    const metadata = typeof alertRow?.metadata === "object" && alertRow?.metadata ? alertRow.metadata : {};
    const ids = collectDocumentTokens(
      alertRow?.alert_id,
      alertRow?.id,
      alertRow?.incident_id,
      metadata?.alert_id,
      metadata?.incident_id,
      labels?.alert_id,
    );
    const alertTypes = collectDocumentTokens(
      alertRow?.alert_type,
      alertRow?.name,
      alertRow?.alert_name,
      alertRow?.alertname,
      labels?.alertname,
      labels?.alert_type,
      labels?.rule,
    );
    const services = collectDocumentTokens(
      alertRow?.service,
      alertRow?.application,
      alertRow?.project,
      alertRow?.project_name,
      alertRow?.component,
      metadata?.service,
      metadata?.application,
      metadata?.project,
      labels?.service,
      labels?.job,
      labels?.application,
      labels?.project,
      labels?.project_name,
      labels?.deployment,
      labels?.namespace,
      labels?.instance,
    );
    const genericServiceDocsAllowed = alertRow?.document_available === true || Boolean(metadata?.runbook_hint);
    return { ids, alertTypes, services, genericServiceDocsAllowed };
  }

  function ragDocumentMatchesAlert(doc, context) {
    const docIds = collectDocumentTokens(doc?.alert_id, doc?.id, doc?.metadata?.alert_id, doc?.metadata?.incident_id);
    if ([...context.ids].some((id) => docIds.has(id))) {
      return true;
    }
    const docAlertTypes = collectDocumentTokens(doc?.alert_type, doc?.alert_name, doc?.alertname, doc?.metadata?.alert_type);
    const docServices = collectDocumentTokens(doc?.services, doc?.service, doc?.metadata?.service, doc?.metadata?.services);
    const hasAlertTypeMatch = [...context.alertTypes].some((type) => docAlertTypes.has(type));
    const hasServiceMatch = [...context.services].some((service) => docServices.has(service));
    if (hasAlertTypeMatch && hasServiceMatch) {
      return true;
    }
    const docKind = String(doc?.kind || doc?.document_kind || "").trim().toLowerCase();
    const isGenericServiceDoc = !docIds.size && hasServiceMatch && ["runbook", "incident", "sop", "onboarding"].includes(docKind);
    return Boolean(context.genericServiceDocsAllowed && isGenericServiceDoc);
  }

  function findMatchingRagDocument(alertRow, preferredKind = "") {
    const context = getAlertDocumentMatchContext(alertRow);
    const normalizedKind = String(preferredKind || "").trim().toLowerCase();
    const docs = Array.isArray(ragDocs.rows) ? ragDocs.rows : [];
    return docs.find((doc) => {
      const docKind = String(doc?.kind || doc?.document_kind || "").trim().toLowerCase();
      if (normalizedKind && docKind && docKind !== normalizedKind) {
        return false;
      }
      return ragDocumentMatchesAlert(doc, context);
    }) || null;
  }

  function findAlertRagDocuments(alertRow) {
    if (!alertRow || typeof alertRow !== "object") {
      return [];
    }
    const context = getAlertDocumentMatchContext(alertRow);
    const docs = Array.isArray(ragDocs.rows) ? ragDocs.rows : [];
    return docs.filter((doc) => ragDocumentMatchesAlert(doc, context));
  }

  async function downloadRagDocument(doc) {
    const path = String(doc?.path || "").trim();
    if (!path) {
      return;
    }
    try {
      const full = unwrap(await fetchJson(`/api-gateway/rag/documents/content?path=${encodeURIComponent(path)}`, authenticatedOptions()));
      const title = String(full?.title || doc?.title || path.split(/[\\/]/).pop() || "alert-document").trim();
      const content = [
        `# ${title}`,
        "",
        full?.summary ? `Summary: ${String(full.summary).trim()}` : "",
        full?.kind || doc?.kind ? `Kind: ${String(full?.kind || doc?.kind).trim()}` : "",
        full?.alert_id || doc?.alert_id ? `Alert ID: ${String(full?.alert_id || doc?.alert_id).trim()}` : "",
        "",
        String(full?.content || doc?.content || "").trim(),
      ].filter((line) => line !== "").join("\n");
      const safeName = `${title || "alert-document"}`.replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "alert-document";
      const blob = new Blob([content || JSON.stringify(full || doc, null, 2)], { type: "text/markdown;charset=utf-8" });
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `${safeName}.md`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setRagDocs((current) => ({ ...current, error: `Download failed: ${String(error?.message || "Unknown error")}` }));
    }
  }

  function backendDocumentPreview(doc) {
    const summary = String(doc?.summary || "").trim();
    const action = String(doc?.recommended_action || "").trim();
    const content = String(doc?.content || "").trim();
    const rootCause = String(doc?.root_cause || "").trim();
    const impact = String(doc?.impact || "").trim();
    const fallback = [rootCause, impact, action].filter(Boolean).join(" ");
    return String(summary || content || fallback || "Open the document view to inspect backend metadata and download the document.")
      .replace(/\s+/g, " ")
      .slice(0, 240);
  }

  async function downloadConsolidatedAlertDocument(docs) {
    const rows = Array.isArray(docs) ? docs.filter(Boolean) : [];
    if (!rows.length) {
      return;
    }
    const alertName = String(selectedAlertRow?.name || selectedAlertId || "alert").trim();
    const service = String(selectedAlertRow?.service || rows[0]?.services?.[0] || rows[0]?.service || "service").trim();
    try {
      const sections = [];
      for (const [index, doc] of rows.entries()) {
        const path = String(doc?.path || "").trim();
        let full = {};
        if (path) {
          try {
            full = unwrap(await fetchJson(`/api-gateway/rag/documents/content?path=${encodeURIComponent(path)}`, authenticatedOptions()));
          } catch (_error) {
            full = {};
          }
        }
        const title = String(full?.title || doc?.title || `Document ${index + 1}`).trim();
        sections.push([
          `## ${title}`,
          "",
          `Kind: ${String(full?.kind || doc?.kind || doc?.document_kind || "document").trim()}`,
          doc?.match_reason ? `Match reason: ${String(doc.match_reason).trim()}` : "",
          doc?.match_confidence ? `Match confidence: ${Math.round(Number(doc.match_confidence) * 100)}%` : "",
          full?.summary || doc?.summary ? `Summary: ${String(full?.summary || doc?.summary).trim()}` : "",
          "",
          String(full?.content || doc?.content || doc?.recommended_action || "Document content is available in backend metadata.").trim(),
        ].filter((line) => line !== "").join("\n"));
      }
      const content = [
        `# ${service} Alert Knowledge Document`,
        "",
        `Alert: ${alertName}`,
        `Service: ${service}`,
        `Linked backend documents: ${rows.length}`,
        "",
        ...sections,
      ].join("\n\n");
      const safeName = `${service || "service"}-${alertName || "alert"}-knowledge`
        .replace(/[^a-zA-Z0-9._-]+/g, "-")
        .replace(/^-+|-+$/g, "") || "alert-knowledge";
      const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `${safeName}.md`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setRagDocs((current) => ({ ...current, error: `Download failed: ${String(error?.message || "Unknown error")}` }));
    }
  }

  function hasAlertDocuments(alertRow) {
    if (!alertRow || typeof alertRow !== "object") {
      return false;
    }
    const explicitFlag = alertRow.document_available === true;
    if (explicitFlag) {
      return true;
    }
    return Boolean(findMatchingRagDocument(alertRow));
  }

  function buildAlertDocumentDraft(alertRow, workflowPayload, preferredKind = "runbook") {
    const allDrafts = buildAlertDocumentDrafts(alertRow, workflowPayload);
    const kind = String(preferredKind || "runbook").trim().toLowerCase();
    return allDrafts[kind] || allDrafts.runbook;
  }

  async function buildAlertDocumentDraftWithAnalysis(alertRow, preferredKind = "runbook") {
    const alertId = String(alertRow?.alert_id || alertRow?.id || "").trim();
    let workflowPayload = {};
    if (alertId && String(selectedAlertData?.alertId || "").trim() === alertId && selectedAlertData?.payload) {
      workflowPayload = selectedAlertData.payload?.data || selectedAlertData.payload;
    } else if (alertId) {
      try {
        const payload = await fetchJson(`/monitoring-adapter/alerts/${alertId}/processed-result`);
        workflowPayload = payload?.data || payload;
      } catch (_error) {
        workflowPayload = {};
      }
    }
    return buildAlertDocumentDraft(alertRow, workflowPayload, preferredKind);
  }

  function buildDocPayloadFromDraft(draft) {
    const toPlanLines = (value) => {
      if (Array.isArray(value)) {
        return value.map((item) => String(item || "").trim()).filter(Boolean);
      }
      return String(value || "")
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);
    };

    const commands = toPlanLines(draft.remediation_commands_text ?? draft.commands);
    const scripts = toPlanLines(draft.remediation_scripts_text ?? draft.scripts);
    const queries = toPlanLines(draft.remediation_queries_text ?? draft.queries);
    const executionPlan = String(draft.execution_plan || "").trim() || [
      commands.length ? `Commands:\n${commands.map((item) => `- ${item}`).join("\n")}` : "",
      scripts.length ? `Scripts:\n${scripts.map((item) => `- ${item}`).join("\n")}` : "",
      queries.length ? `Queries:\n${queries.map((item) => `- ${item}`).join("\n")}` : "",
    ].filter(Boolean).join("\n\n");

    return {
      kind: draft.kind,
      title: draft.title,
      summary: draft.summary || null,
      content: draft.content,
      services: String(draft.services || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      severity: draft.severity,
      alert_type: draft.alert_type,
      alert_id: draft.alert_id || null,
      root_cause: draft.root_cause || null,
      impact: draft.impact || null,
      execution_plan: executionPlan || null,
      commands,
      scripts,
      queries,
      recommended_action: draft.recommended_action || null,
    };
  }

  async function setDocPromptDraftForKind(row, kind) {
    const normalizedKind = String(kind || "runbook").trim().toLowerCase();
    const alertId = String(row?.alert_id || row?.id || "").trim();
    const existingDoc = findMatchingRagDocument(row, normalizedKind);
    setDocPromptKind(normalizedKind);
    setDocPromptExistingDoc(existingDoc);
    setDocPromptMode(existingDoc?.path ? "update" : "create");

    if (existingDoc?.path) {
      // Show the real saved document instead of a freshly generated draft.
      setAlertOnboardingState({ loading: true, result: null, error: "" });
      try {
        const full = unwrap(await fetchJson(`/api-gateway/rag/documents/content?path=${encodeURIComponent(existingDoc.path)}`));
        setAlertOnboarding((curr) => ({
          ...curr,
          kind: normalizedKind,
          title: String(full.title || existingDoc.title || "Alert Document").slice(0, 160),
          summary: String(full.summary || "").trim(),
          content: String(full.content || "").trim(),
          services: Array.isArray(full.services) ? full.services.join(", ") : String(full.services || "").trim(),
          severity: String(full.severity || "high").toLowerCase(),
          alert_type: String(full.alert_type || "").trim(),
          alert_id: alertId,
        }));
        setAlertOnboardingState({ loading: false, result: null, error: "" });
      } catch (error) {
        setAlertOnboardingState({ loading: false, result: null, error: error.message });
      }
      return;
    }

    const selectedPayload = String(selectedAlertData?.alertId || "").trim() === alertId
      ? (selectedAlertData.payload?.data || selectedAlertData.payload || {})
      : {};
    const draft = buildAlertDocumentDraft(row, selectedPayload, normalizedKind);
    setAlertOnboarding((curr) => ({
      ...curr,
      kind: draft.kind,
      title: String(draft.title || "Alert Document").slice(0, 160),
      summary: String(draft.summary || "").trim(),
      content: String(draft.content || "Provide troubleshooting and escalation steps for this alert scenario.").trim(),
      services: String(draft.services || "").trim(),
      severity: String(draft.severity || "high").toLowerCase(),
      alert_type: String(draft.alert_type || "").trim(),
      alert_id: alertId,
      execution_plan: String(draft.execution_plan || "").trim(),
      remediation_commands_text: Array.isArray(draft.commands) ? draft.commands.join("\n") : "",
      remediation_scripts_text: Array.isArray(draft.scripts) ? draft.scripts.join("\n") : "",
      remediation_queries_text: Array.isArray(draft.queries) ? draft.queries.join("\n") : "",
    }));
  }

  async function autoGenerateRemediationPlan(alertRow = null) {
    const sourceRow = alertRow && typeof alertRow === "object"
      ? alertRow
      : {
          alert_id: alertOnboarding.alert_id,
          name: alertOnboarding.alert_type || alertOnboarding.title || "Alert",
          service: String(alertOnboarding.services || "").split(",")[0]?.trim() || "unknown-service",
          severity: alertOnboarding.severity || "high",
        };
    const draft = alertRow && typeof alertRow === "object"
      ? await buildAlertDocumentDraftWithAnalysis(sourceRow, "remediation")
      : buildAlertDocumentDraft(sourceRow, {}, "remediation");
    setAlertOnboarding((curr) => ({
      ...curr,
      kind: "remediation",
      title: String(draft.title || curr.title || "Remediation Plan").slice(0, 160),
      summary: String(draft.summary || curr.summary || "").trim(),
      content: String(draft.content || curr.content || "").trim(),
      services: String(draft.services || curr.services || "").trim(),
      severity: String(draft.severity || curr.severity || "high").toLowerCase(),
      alert_type: String(draft.alert_type || curr.alert_type || "").trim(),
      alert_id: String(draft.alert_id || curr.alert_id || "").trim(),
      execution_plan: String(draft.execution_plan || "").trim(),
      remediation_commands_text: Array.isArray(draft.commands) ? draft.commands.join("\n") : "",
      remediation_scripts_text: Array.isArray(draft.scripts) ? draft.scripts.join("\n") : "",
      remediation_queries_text: Array.isArray(draft.queries) ? draft.queries.join("\n") : "",
    }));
  }

  function parseAiDraftContent(content) {
    const text = String(content || "").trim();
    if (!text) {
      return null;
    }
    const candidates = [text];
    const fenced = text.match(/```json\s*([\s\S]*?)```/i);
    if (fenced?.[1]) {
      candidates.push(String(fenced[1]).trim());
    }
    const objectBlock = text.match(/\{[\s\S]*\}/);
    if (objectBlock?.[0]) {
      candidates.push(String(objectBlock[0]).trim());
    }
    for (const candidate of candidates) {
      try {
        const parsed = JSON.parse(candidate);
        if (parsed && typeof parsed === "object") {
          return parsed;
        }
      } catch (_error) {
        // Try next extraction candidate.
      }
    }
    return null;
  }

  function normalizeDraftList(value) {
    if (Array.isArray(value)) {
      return value.map((item) => String(item || "").trim()).filter(Boolean);
    }
    return String(value || "")
      .split(/\r?\n/)
      .map((item) => item.replace(/^[-*]\s*/, "").trim())
      .filter(Boolean);
  }

  async function generateAlertKnowledgeDraftFromPrompt() {
    const prompt = buildAlertKnowledgePromptInput();
    if (!prompt) {
      setAlertOnboardingState({ loading: false, result: null, error: "Enter a prompt or upload a supporting document to generate the document draft." });
      return;
    }

    const normalizedKind = String(alertOnboarding.kind || "incident").trim().toLowerCase();
    const sourceDocName = String(alertKnowledgeSourceDoc?.name || "").trim();
    const lines = prompt
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    const sentences = prompt
      .split(/(?<=[.!?])\s+/)
      .map((item) => item.trim())
      .filter(Boolean);
    const summary = String(sentences[0] || lines[0] || prompt).slice(0, 260);
    const titleSeed = String(lines[0] || prompt)
      .replace(/^[-*#\d.\s]+/, "")
      .split(/\s+/)
      .slice(0, 8)
      .join(" ")
      .trim();
    const fallbackTitle = `${normalizedKind[0]?.toUpperCase() || "D"}${normalizedKind.slice(1)} Doc`;
    const generatedTitle = titleSeed ? titleSeed.slice(0, 160) : fallbackTitle;

    const commandMatches = [];
    const scriptMatches = [];
    const queryMatches = [];

    const cleanToken = (value) => String(value || "").trim().replace(/^[-*]\s*/, "");
    const pushUnique = (target, value) => {
      const normalized = cleanToken(value);
      if (!normalized) {
        return;
      }
      if (!target.some((item) => item.toLowerCase() === normalized.toLowerCase())) {
        target.push(normalized);
      }
    };

    const extractTaggedValues = (inputText, tagPattern) => {
      const regex = new RegExp(`\\b(?:${tagPattern})\\s*[:\\-]\\s*([^\\n;|]+)`, "ig");
      const values = [];
      let match = regex.exec(inputText);
      while (match) {
        values.push(match[1]);
        match = regex.exec(inputText);
      }
      return values;
    };

    const shellLike = /^(kubectl|kubeadm|helm|docker|docker-compose|compose|terraform|ansible|oc|az|aws|gcloud|systemctl|journalctl|curl|wget|psql|mysql|redis-cli|kafka-|python\s+|pip\s+|npm\s+|node\s+|pwsh\s+|powershell\s+|bash\s+)/i;
    const sqlLike = /\b(select|update|delete|insert|with|merge|create\s+table|drop\s+table|alter\s+table)\b/i;

    extractTaggedValues(prompt, "cmd|command").forEach((value) => pushUnique(commandMatches, value));
    extractTaggedValues(prompt, "script|ps1|sh|bash").forEach((value) => pushUnique(scriptMatches, value));
    extractTaggedValues(prompt, "query|sql").forEach((value) => pushUnique(queryMatches, value));

    const codeFenceRegex = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g;
    let fenceMatch = codeFenceRegex.exec(prompt);
    while (fenceMatch) {
      const lang = String(fenceMatch[1] || "").trim().toLowerCase();
      const body = String(fenceMatch[2] || "")
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .join(" ; ");
      if (body) {
        if (lang.includes("sql") || sqlLike.test(body)) {
          pushUnique(queryMatches, body);
        } else if (lang.includes("bash") || lang.includes("sh") || lang.includes("ps") || lang.includes("powershell")) {
          pushUnique(scriptMatches, body);
        } else if (shellLike.test(body)) {
          pushUnique(commandMatches, body);
        }
      }
      fenceMatch = codeFenceRegex.exec(prompt);
    }

    const taggedSegment = /\b(cmd|command|script|query|sql|ps1|bash|sh)\s*[:\-]/i;
    const fallbackSegments = prompt
      .split(/[\r\n;]+/)
      .map((item) => item.trim())
      .filter(Boolean);

    fallbackSegments.forEach((segment) => {
      if (taggedSegment.test(segment)) {
        return;
      }
      if (shellLike.test(segment)) {
        pushUnique(commandMatches, segment);
        return;
      }
      if (sqlLike.test(segment)) {
        pushUnique(queryMatches, segment);
      }
    });

    const narrativeSegments = fallbackSegments.filter((segment) => {
      if (taggedSegment.test(segment)) {
        return false;
      }
      if (shellLike.test(segment) || sqlLike.test(segment)) {
        return false;
      }
      return true;
    });

    const sentenceTail = sentences
      .slice(1, 4)
      .map((item) => item.trim())
      .filter(Boolean)
      .join(" ");

    const narrativeDetail = [
      ...narrativeSegments,
      sentenceTail,
    ]
      .map((item) => String(item || "").trim())
      .filter(Boolean)
      .filter((item, index, arr) => arr.findIndex((other) => other.toLowerCase() === item.toLowerCase()) === index)
      .join("\n");

    const contentBody = [
      summary,
      narrativeDetail,
    ].filter(Boolean).join("\n\n");

    let aiDraft = null;
    let aiUsage = null;
    try {
      const aiResponseRaw = await fetchJson("/api-gateway/model/route", authenticatedOptions({
        method: "POST",
        body: JSON.stringify({
          severity: String(alertOnboarding.severity || "high").trim().toLowerCase(),
          task: normalizedKind === "remediation" ? "fix" : "summarization",
          prompt: [
            `Generate a meaningful ${normalizedKind} document draft for SRE operations from user input.`,
            "Return ONLY valid JSON with keys: title, summary, content, commands, scripts, queries, metadata.",
            "Use commands/scripts/queries only when relevant and keep content actionable.",
          ].join(" "),
          payload: {
            kind: normalizedKind,
            alert_type: String(alertOnboarding.alert_type || "").trim(),
            services: String(alertOnboarding.services || "").trim(),
            user_prompt: prompt,
            source_document: sourceDocName || null,
          },
        }),
      }));
      const aiResponse = aiResponseRaw?.data && typeof aiResponseRaw.data === "object"
        ? aiResponseRaw.data
        : aiResponseRaw;
      aiUsage = aiResponse?.usage || null;
      aiDraft = parseAiDraftContent(aiResponse?.content || "");
    } catch (_error) {
      aiDraft = null;
    }

    const mergeUnique = (base, extra) => {
      const out = [];
      [...normalizeDraftList(base), ...normalizeDraftList(extra)].forEach((item) => {
        if (!out.some((existing) => existing.toLowerCase() === item.toLowerCase())) {
          out.push(item);
        }
      });
      return out;
    };

    const aiCommands = normalizeDraftList(aiDraft?.commands);
    const aiScripts = normalizeDraftList(aiDraft?.scripts);
    const aiQueries = normalizeDraftList(aiDraft?.queries);
    const mergedCommands = mergeUnique(aiCommands, commandMatches);
    const mergedScripts = mergeUnique(aiScripts, scriptMatches);
    const mergedQueries = mergeUnique(aiQueries, queryMatches);
    const mergedExecutionPlan = [
      mergedCommands.length ? `Commands:\n${mergedCommands.map((item) => `- ${item}`).join("\n")}` : "",
      mergedScripts.length ? `Scripts:\n${mergedScripts.map((item) => `- ${item}`).join("\n")}` : "",
      mergedQueries.length ? `Queries:\n${mergedQueries.map((item) => `- ${item}`).join("\n")}` : "",
    ].filter(Boolean).join("\n\n");

    setAlertOnboarding((curr) => ({
      ...curr,
      title: String(aiDraft?.title || generatedTitle).slice(0, 160),
      summary: String(aiDraft?.summary || summary).trim(),
      content: String(aiDraft?.content || contentBody || prompt).trim(),
      execution_plan: normalizedKind === "remediation" ? mergedExecutionPlan : curr.execution_plan,
      remediation_commands_text: normalizedKind === "remediation" ? mergedCommands.join("\n") : curr.remediation_commands_text,
      remediation_scripts_text: normalizedKind === "remediation" ? mergedScripts.join("\n") : curr.remediation_scripts_text,
      remediation_queries_text: normalizedKind === "remediation" ? mergedQueries.join("\n") : curr.remediation_queries_text,
    }));

    setAlertOnboardingState({
      loading: false,
      result: {
        message: aiDraft
          ? `Draft generated from ${sourceDocName ? "prompt + document" : "prompt"} using AI + heuristics. Review and click Create Alert Onboarding Doc.`
          : `Draft generated from ${sourceDocName ? "prompt + document" : "prompt"} using heuristics fallback. Review and click Create Alert Onboarding Doc.`,
        source_document: sourceDocName || null,
        ai_usage: aiUsage,
      },
      error: "",
    });
  }

  async function autoCreateAlertDocument(alertRow, preferredKind = "runbook") {
    if (!alertRow || alertOnboardingState.loading) {
      return;
    }
    setAlertOnboardingState({ loading: true, result: null, error: "" });
    try {
      const draft = await buildAlertDocumentDraftWithAnalysis(alertRow, preferredKind);
      const existingDoc = findMatchingRagDocument(alertRow, draft.kind);
      const payload = buildDocPayloadFromDraft(draft);
      const response = await fetchJson("/api-gateway/rag/documents", authenticatedOptions({
        method: existingDoc?.path ? "PUT" : "POST",
        body: JSON.stringify(existingDoc?.path ? { ...payload, path: existingDoc.path } : payload),
      }));
      const responseData = response?.data || response || {};
      setAlertOnboardingState({
        loading: false,
        error: "",
        result: {
          ...response,
          message: existingDoc?.path
            ? `${draft.kind} document updated from alert analysis.`
            : `${draft.kind} document created from alert analysis.`,
        },
      });
      await Promise.all([loadRagDocs(), loadRecentAlerts()]);
      if (docPromptAlert) {
        const mergedDoc = {
          ...(existingDoc || {}),
          ...(typeof responseData === "object" && responseData ? responseData : {}),
          kind: draft.kind,
          path: responseData?.path || existingDoc?.path,
          alert_id: draft.alert_id || existingDoc?.alert_id || null,
        };
        setDocPromptDocsByKind((curr) => ({ ...curr, [draft.kind]: mergedDoc }));
        if (String(docPromptKind || "").trim().toLowerCase() === draft.kind) {
          setDocPromptExistingDoc(mergedDoc);
          setDocPromptMode(mergedDoc?.path ? "update" : "create");
        }
      }
    } catch (error) {
      setAlertOnboardingState({ loading: false, result: null, error: error.message });
    }
  }

  async function autoCreateAllAlertDocuments(alertRow) {
    if (!alertRow || alertOnboardingState.loading) {
      return;
    }
    setAlertOnboardingState({ loading: true, result: null, error: "" });
    try {
      const results = [];
      for (const kind of ALERT_DOC_KIND_OPTIONS) {
        const draft = await buildAlertDocumentDraftWithAnalysis(alertRow, kind);
        const existingDoc = findMatchingRagDocument(alertRow, kind);
        const payload = buildDocPayloadFromDraft(draft);
        const response = await fetchJson("/api-gateway/rag/documents", authenticatedOptions({
          method: existingDoc?.path ? "PUT" : "POST",
          body: JSON.stringify(existingDoc?.path ? { ...payload, path: existingDoc.path } : payload),
        }));
        results.push({ kind, path: response?.data?.path || response?.path || existingDoc?.path || "" });
      }
      await Promise.all([loadRagDocs(), loadRecentAlerts()]);
      setAlertOnboardingState({
        loading: false,
        error: "",
        result: {
          message: `Created/updated ${results.length} document types: ${results.map((item) => item.kind).join(", ")}`,
          results,
        },
      });
      if (docPromptAlert) {
        const refreshedByKind = {};
        ALERT_DOC_KIND_OPTIONS.forEach((kind) => {
          const matched = findMatchingRagDocument(docPromptAlert, kind);
          if (matched) {
            refreshedByKind[kind] = matched;
          }
        });
        setDocPromptDocsByKind(refreshedByKind);
        setDocPromptExistingDoc(refreshedByKind[docPromptKind] || null);
        setDocPromptMode(refreshedByKind[docPromptKind]?.path ? "update" : "create");
      }
    } catch (error) {
      setAlertOnboardingState({ loading: false, result: null, error: error.message });
    }
  }

  async function addRuleFromAlertPrompt() {
    const row = docPromptAlert;
    const requirement = String(alertRuleDraft.requirement || "").trim();
    if (!row || !requirement) {
      setAlertRuleState({ loading: false, result: null, error: "Provide a rule requirement first." });
      return;
    }
    setAlertRuleState({ loading: true, result: null, error: "" });
    try {
      const service = String(row?.service || "unknown-service").trim();
      const projectName = String(row?.application || row?.project_name || service || "alert-onboarding").trim();
      const platform = String(alertRuleDraft.platform || "prometheus").trim().toLowerCase();
      const payload = {
        project: {
          project_name: projectName,
          environment: String(row?.environment || onboardingForm.environment || "prod").trim().toLowerCase(),
          criticality: String(row?.severity || "high").trim().toLowerCase() === "critical" ? "high" : "medium",
          support_team: String(onboardingForm.owner_team || "platform-ops").trim(),
          region: String(onboardingForm.region || "us-east-1").trim(),
          cloud_provider: onboardingForm.deployment_mode === "azure_cloud" ? "azure" : "on_prem",
          monitoring_platforms: [platform],
          notification_platforms: ["slack", "teams"],
        },
        monitoring_requirements: [requirement],
        target_platforms: [platform],
        discovery_inputs: {
          source_alert_id: String(row?.alert_id || row?.id || "").trim(),
          alert_type: String(row?.name || row?.alert_name || "").trim(),
          service,
          severity: String(row?.severity || "high").trim().toLowerCase(),
          endpoint_url: simplifyMonitoringUrl(onboardingForm.monitoring_url),
          generated_from_alert_analysis: true,
        },
      };
      const response = await fetchJson("/api-gateway/onboarding/rules/pipeline/create", authenticatedOptions({
        method: "POST",
        body: JSON.stringify(payload),
      }));
      const data = unwrap(response);
      const workflowId = String(data?.workflow_id || "").trim();
      if (workflowId) {
        setOnboardingRuleLookup((current) => ({ ...current, workflow_id: workflowId }));
      }
      setAlertRuleState({ loading: false, result: data, error: "" });
    } catch (error) {
      setAlertRuleState({ loading: false, result: null, error: error.message });
    }
  }

  async function submitAlertOnboarding(event) {
    event.preventDefault();
    setAlertOnboardingState({ loading: true, result: null, error: "" });
    try {
      const payload = {
        ...buildDocPayloadFromDraft(alertOnboarding),
        kind: String(alertOnboarding.kind || "incident").trim(),
        title: String(alertOnboarding.title || "").trim(),
        content: String(alertOnboarding.content || "").trim(),
        severity: String(alertOnboarding.severity || "").trim(),
      };
      const isUpdate = docPromptMode === "update" && Boolean(docPromptExistingDoc?.path);
      const response = await fetchJson("/api-gateway/rag/documents", authenticatedOptions({
        method: isUpdate ? "PUT" : "POST",
        body: JSON.stringify(isUpdate ? { ...payload, path: docPromptExistingDoc.path } : payload),
      }));
      const responseData = response?.data || response || {};
      const normalizedKind = String(payload.kind || docPromptKind || "runbook").trim().toLowerCase();
      const mergedDoc = {
        ...(docPromptExistingDoc || {}),
        ...(typeof responseData === "object" && responseData ? responseData : {}),
        kind: normalizedKind,
        alert_id: payload.alert_id,
        alert_type: payload.alert_type,
        services: payload.services,
        path: responseData?.path || docPromptExistingDoc?.path,
      };
      setAlertOnboardingState({
        loading: false,
        result: {
          ...response,
          message: isUpdate ? `${normalizedKind} document updated.` : `${normalizedKind} document created.`,
        },
        error: "",
      });
      setDocPromptDocsByKind((curr) => ({ ...curr, [normalizedKind]: mergedDoc }));
      setDocPromptExistingDoc(mergedDoc);
      setDocPromptMode(mergedDoc?.path ? "update" : "create");
      await Promise.all([loadRagDocs(), loadRecentAlerts()]);
      await refreshViewsAfterSubmit();
    } catch (error) {
      setAlertOnboardingState({ loading: false, result: null, error: error.message });
    }
  }

  async function autoGenerateAlertKnowledgeFromSourceDocs({ projectName, onboardingPath }) {
    const sourceRows = onboardingSourceDocRows;
    if (!sourceRows.length) {
      return false;
    }

    const safeProject = String(projectName || onboardingForm.name || "").trim() || "Project";
    const summary = `Auto-generated from ${sourceRows.length} uploaded source document(s).`;
    const evidenceLines = sourceRows.slice(0, 8).map((row) => {
      const label = onboardingSourceDocCategoryLabel(row?.category);
      const excerpt = String(row?.excerpt || "").trim();
      return `- [${label}] ${String(row?.name || "uploaded-document").trim()}${excerpt ? `: ${excerpt}` : ""}`;
    });
    const requirementLines = onboardingDerivedRequirements.slice(0, 8).map((line) => `- ${line}`);
    const content = [
      `Auto-generated alert onboarding for ${safeProject}.`,
      "",
      "Source evidence:",
      ...evidenceLines,
      "",
      "Derived requirements:",
      ...(requirementLines.length ? requirementLines : ["- No derived requirements captured."]),
      "",
      "Use this draft to refine final triage and remediation guidance.",
    ].join("\n");

    const autoDraft = {
      kind: "runbook",
      title: `${safeProject} Alert Knowledge Onboarding`,
      summary,
      content,
      services: safeProject,
      severity: "high",
      alert_type: onboardingPath === "setup_monitoring" ? "configuration" : "availability",
      alert_id: "",
      root_cause: "",
      impact: "",
      execution_plan: "",
      remediation_commands_text: "",
      remediation_scripts_text: "",
      remediation_queries_text: "",
      recommended_action: "Review generated draft and finalize onboarding knowledge.",
    };

    try {
      const response = await fetchJson("/api-gateway/rag/documents", authenticatedOptions({
        method: "POST",
        body: JSON.stringify(buildDocPayloadFromDraft(autoDraft)),
      }));
      setAlertOnboarding((curr) => ({ ...curr, ...autoDraft }));
      setAlertOnboardingState({
        loading: false,
        result: {
          ...response,
          message: "Alert Knowledge Onboarding auto-generated from Service Knowledge.",
        },
        error: "",
      });
      setAlertKnowledgeView("onboarding");
      return true;
    } catch (error) {
      setAlertOnboardingState({
        loading: false,
        result: null,
        error: `Automatic Alert Knowledge generation failed: ${String(error?.message || "Unknown error")}`,
      });
      setAlertKnowledgeView("onboarding");
      return false;
    }
  }

  function openDocumentPrompt(row) {
    if (!canProvideAlertDocuments) {
      setDocPromptAlert(null);
      return;
    }
    const byKind = {};
    ALERT_DOC_KIND_OPTIONS.forEach((kind) => {
      const doc = findMatchingRagDocument(row, kind);
      if (doc) {
        byKind[kind] = doc;
      }
    });
    setDocPromptDocsByKind(byKind);
    setDocPromptAlert(row);
    // If documents already exist for this alert, open on the first available
    // one so the real saved content is shown; otherwise default to runbook
    // for creating a new document.
    const initialKind = ALERT_DOC_KIND_OPTIONS.find((kind) => byKind[kind]) || "runbook";
    setDocPromptDraftForKind(row, initialKind);
    const defaultRequirement = `Create a ${String(row?.severity || "high").toLowerCase()} alert rule for ${String(row?.service || "this service").trim()} based on ${String(row?.name || row?.alert_name || "service degradation").trim()} and route incidents to on-call.`;
    setAlertRuleDraft({ platform: String(onboardingForm.monitoring_tool || "prometheus").trim().toLowerCase(), requirement: defaultRequirement });
    setAlertRuleState({ loading: false, result: null, error: "" });
    setAlertOnboardingState({ loading: false, result: null, error: "" });
    setTimeout(() => {
      docPromptRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 50);
  }

  function closeDocumentPrompt() {
    setDocPromptAlert(null);
    setDocPromptExistingDoc(null);
    setDocPromptDocsByKind({});
    setDocPromptKind("runbook");
    setDocPromptMode("create");
    setAlertRuleState({ loading: false, result: null, error: "" });
  }


  async function refreshAll() {
    await Promise.all([
      checkHealth(),
      loadRecentAlerts(),
      loadAlertSeverityOverrides(),
      loadFlows(),
      loadMonitorApplications(),
      loadGatewaySummary(),
      loadGatewayRecent(),
      loadLandingPadRecent(),
      loadIncidentMetadata(),
      loadClosedIncidents(),
      loadRagDocs(),
    ]);
  }

  async function refreshViewsAfterSubmit() {
    await Promise.allSettled([
      refreshAll(),
      loadOnboardingAdminData(),
      loadMonitoringApplications(),
    ]);
    if (selectedMonitoringAppId) {
      await loadMonitoringApplicationDetails(selectedMonitoringAppId);
    }
  }

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      const raw = window.localStorage.getItem(PREFERENCE_STORAGE_KEY);
      if (!raw) {
        return;
      }
      const prefs = JSON.parse(raw);
      if (prefs && typeof prefs === "object") {
        if (typeof prefs.applicationToMonitor === "string" && prefs.applicationToMonitor.trim()) {
          setApplicationToMonitor(prefs.applicationToMonitor);
        }
        if (prefs.uiDensity === "comfortable" || prefs.uiDensity === "compact") {
          setUiDensity(prefs.uiDensity);
        }
        if (typeof prefs.uiTheme === "string" && UI_THEME_VALUES.has(prefs.uiTheme)) {
          setUiTheme(prefs.uiTheme);
        }
        if (typeof prefs.selectedFlow === "string" && prefs.selectedFlow.trim()) {
          setSelectedFlow(prefs.selectedFlow);
        }
        if (typeof prefs.activeTab === "string" && VALID_TABS.has(prefs.activeTab)) {
          setActiveTab(prefs.activeTab);
        }
        if (prefs.metadataFilters && typeof prefs.metadataFilters === "object") {
          setMetadataFilters((current) => ({ ...current, ...prefs.metadataFilters }));
        }
        if (prefs.closedFilters && typeof prefs.closedFilters === "object") {
          setClosedFilters((current) => ({ ...current, ...prefs.closedFilters }));
        }
      }
    } catch (_error) {
      // Ignore malformed preference payloads and continue with defaults.
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const root = window.document?.documentElement;
    if (!root) {
      return;
    }
    root.classList.remove("dm-theme-light", "dm-theme-dark");
    if (uiTheme === "light") {
      root.classList.add("dm-theme-light");
    } else if (uiTheme === "dark") {
      root.classList.add("dm-theme-dark");
    }
    root.setAttribute("data-ui-theme", uiTheme);
  }, [uiTheme]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const payload = {
      applicationToMonitor,
      uiDensity,
      uiTheme,
      selectedFlow,
      activeTab,
      metadataFilters,
      closedFilters,
    };
    window.localStorage.setItem(PREFERENCE_STORAGE_KEY, JSON.stringify(payload));
  }, [applicationToMonitor, uiDensity, uiTheme, selectedFlow, activeTab, metadataFilters, closedFilters]);

  useEffect(() => {
    const onKeyDown = (event) => {
      const authenticated = Boolean(String(adminSession.accessToken || "").trim());
      if (!authenticated) {
        return;
      }
      const roleName = normalizeRoleName(adminSession?.user?.role_name);
      const roleTabs = ROLE_ALLOWED_TABS[roleName] || ["home"];
      if (!event.altKey) {
        return;
      }
      const target = event.target;
      const tagName = String(target?.tagName || "").toLowerCase();
      if (tagName === "input" || tagName === "textarea" || tagName === "select" || target?.isContentEditable) {
        return;
      }
      const tabId = TAB_SHORTCUT_MAP[event.code];
      if (!tabId) {
        return;
      }
      if (!roleTabs.includes(tabId)) {
        return;
      }
      event.preventDefault();
      setActiveTab(tabId);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [adminSession.accessToken, adminSession?.user?.role_name]);

  useEffect(() => {
    refreshAll();
  }, []);

  useEffect(() => {
    if (alertsLimit === 50) {
      return;
    }
    loadRecentAlerts();
  }, [alertsLimit]);

  useEffect(() => {
    if (activeTab !== "summary") {
      return;
    }
    loadIncidentMetadata();
  }, [
    activeTab,
    metadataFilters.risk_tier,
    metadataFilters.execution_mode,
    metadataFilters.transport_provider,
    metadataFilters.status,
    metadataFilters.service,
  ]);

  useEffect(() => {
    if (activeTab !== "admin") {
      return;
    }
    loadOnboardingAdminData();
  }, [activeTab]);

  useEffect(() => {
    if (activeTab !== "admin" || adminWorkspace !== "project") {
      return;
    }
    loadOnboardingRuleCapabilities();
  }, [activeTab, adminWorkspace]);

  useEffect(() => {
    const stressAlertPresent = alerts.rows.some((row) => {
      return String(row?.application || row?.project || row?.project_name || row?.source || "")
        .trim()
        .toLowerCase() === "stress-lab"
        || String(row?.source || "").trim().toLowerCase() === "stress-harness"
        || String(row?.labels?.workload || "").trim().toLowerCase() === "20k-stress";
    });

    if (stressAlertPresent && applicationToMonitor !== "stress-lab") {
      setApplicationToMonitor("stress-lab");
      return;
    }

    if (monitorApplications.includes(applicationToMonitor)) {
      return;
    }
    setApplicationToMonitor(monitorApplications[0] || "kaiops-core1");
  }, [alerts.rows, monitorApplications, applicationToMonitor]);

  useEffect(() => {
    if (!adminSession.accessToken || activeTab !== "admin") {
      return;
    }
    loadAdminUsersAndRoles();
  }, [adminSession.accessToken, activeTab]);

  useEffect(() => {
    loadMonitorApplications();
  }, [alerts.rows]);

  const latestWorkflow = useMemo(() => {
    return workflowState?.result?.data || {};
  }, [workflowState]);

  const latestIncidentId = useMemo(() => {
    return String(latestWorkflow?.incident?.id || latestWorkflow?.incident_id || "").trim();
  }, [latestWorkflow]);

  const latestRecommendationId = useMemo(() => {
    return String(latestWorkflow?.recommendation?.id || latestWorkflow?.recommendation_id || "").trim();
  }, [latestWorkflow]);

  const monitorScopedAlerts = useMemo(() => {
    return filterAlertsForMonitor(alerts.rows, applicationToMonitor);
  }, [alerts.rows, applicationToMonitor]);

  const visibleAlerts = useMemo(() => {
    return monitorScopedAlerts;
  }, [monitorScopedAlerts]);

  const dashboardAlertSummary = useMemo(() => {
    const summary = { total: visibleAlerts.length, ops: 0, test: 0, critical: 0, high: 0, awaiting: 0, active: 0 };
    visibleAlerts.forEach((row) => {
      const severity = String(row?.severity || "").toLowerCase();
      const status = String(row?.status || row?.state || "open").toLowerCase();
      if (isGeneratedOrTestAlert(row)) {
        summary.test += 1;
      } else {
        summary.ops += 1;
      }
      if (severity === "critical") {
        summary.critical += 1;
      }
      if (severity === "high") {
        summary.high += 1;
      }
      if (status === "awaiting_approval") {
        summary.awaiting += 1;
      }
      if (status === "open" || status === "pending" || status === "investigating") {
        summary.active += 1;
      }
    });
    return summary;
  }, [visibleAlerts]);

  const dashboardVisibleAlerts = useMemo(() => {
    const query = String(dashboardAlertQuery || "").trim().toLowerCase();
    return visibleAlerts.filter((row) => {
      const severity = String(row?.severity || "").toLowerCase();
      const status = String(row?.status || row?.state || "open").toLowerCase();
      const generatedOrTest = isGeneratedOrTestAlert(row);
      if (dashboardAlertFocus === "ops" && generatedOrTest) {
        return false;
      }
      if (dashboardAlertFocus === "test" && !generatedOrTest) {
        return false;
      }
      if (dashboardAlertFocus === "critical" && severity !== "critical") {
        return false;
      }
      if (dashboardAlertFocus === "high" && severity !== "high") {
        return false;
      }
      if (dashboardAlertFocus === "awaiting" && status !== "awaiting_approval") {
        return false;
      }
      if (dashboardAlertFocus === "active" && !["open", "pending", "investigating"].includes(status)) {
        return false;
      }
      if (!query) {
        return true;
      }
      const haystack = [
        row?.alert_id,
        row?.id,
        row?.incident_id,
        row?.name,
        row?.alert_name,
        row?.service,
        row?.application,
        row?.project_name,
        row?.project,
      ]
        .map((value) => String(value || "").toLowerCase())
        .join(" ");
      return haystack.includes(query);
    });
  }, [visibleAlerts, dashboardAlertFocus, dashboardAlertQuery]);

  const monitorScopedIncidentMetadata = useMemo(() => {
    return filterRowsForMonitor(incidentMetadata.rows, applicationToMonitor);
  }, [incidentMetadata.rows, applicationToMonitor]);

  const selectedAlertRow = useMemo(() => {
    return visibleAlerts.find((row) => String(row?.alert_id || row?.id || row?.incident_id || "") === selectedAlertId) || null;
  }, [visibleAlerts, selectedAlertId]);

  const selectedAlertPayload = useMemo(() => {
    return selectedAlertData?.payload?.data || selectedAlertData?.payload || {};
  }, [selectedAlertData]);

  const selectedAlertWorkflow = useMemo(() => {
    return selectedAlertPayload?.workflow || selectedAlertPayload || {};
  }, [selectedAlertPayload]);

  const selectedAlertEvents = useMemo(() => {
    const events =
      selectedAlertWorkflow?.events
      || selectedAlertWorkflow?.workflow_events
      || selectedAlertWorkflow?.agent_events
      || [];
    return Array.isArray(events) ? events : [];
  }, [selectedAlertWorkflow]);

  const selectedAlertEventTrace = useMemo(() => {
    const rows =
      selectedAlertWorkflow?.event_trace
      || selectedAlertWorkflow?.trace_events
      || selectedAlertWorkflow?.trace?.events
      || [];
    if (!Array.isArray(rows)) {
      return [];
    }
    return rows
      .filter((row) => row && typeof row === "object")
      .sort((a, b) => {
        const aTime = parseUtcTimestamp(a.timestamp)?.getTime() || 0;
        const bTime = parseUtcTimestamp(b.timestamp)?.getTime() || 0;
        return aTime - bTime;
      })
      .slice(-300);
  }, [selectedAlertWorkflow]);

  const selectedAlertEventsDisplay = useMemo(() => {
    const buildBackgroundDetailText = (event) => {
      const items = [
        ["event_type", event?.event_type],
        ["event_stage", event?.event_stage],
        ["status", event?.status],
        ["source_channel", event?.source_channel],
        ["transport_channel", event?.transport_channel],
        ["transport_provider", event?.transport_provider],
        ["risk_tier", event?.risk_tier],
        ["execution_mode", event?.execution_mode],
        ["policy_reason", event?.policy_reason],
        ["trace_id", event?.trace_id],
      ]
        .map(([key, value]) => [key, String(value || "").trim()])
        .filter(([, value]) => value && value !== "-")
        .map(([key, value]) => `${key}: ${value}`);
      return items.join("\n");
    };

    const mappedEvents = selectedAlertEvents.map((event, index) => {
      const decision = event?.decision;
      const inputValue = extractEventInput(event);
      const outputValue = extractEventOutput(event);
      const input = typeof inputValue === "object" && inputValue ? inputValue : {};
      return {
        sequence: event?.sequence || index + 1,
        agent: displayAgentName(event?.agent || normalizeTraceServiceName(event) || "-"),
        action: event?.action || event?.event_type || event?.status || "-",
        eventType: event?.event_type || "",
        timestamp: event?.timestamp || "",
        decision: decision && typeof decision === "object" ? JSON.stringify(decision) : String(decision || "-"),
        output: stringifyTimelineValue(outputValue) || String(event?.event_type || "-"),
        communicates_to: event?.communicates_to || event?.transport_channel || input?.transport_channel || "-",
        inputValueText: stringifyTimelineValue(inputValue),
        outputValueText: stringifyTimelineValue(outputValue),
        errorValueText: extractEventError(event),
        backgroundDetailText: buildBackgroundDetailText(event),
      };
    });

    const traceRows = selectedAlertEventTrace.map((row, index) => {
      const inputValue = extractEventInput(row);
      const outputValue = extractEventOutput(row);
      return {
        sequence: index + 1,
        agent: displayAgentName(normalizeTraceServiceName(row)),
        action: summarizeEventType(row?.event_type),
        eventType: row?.event_type || "",
        timestamp: row?.timestamp || "",
        decision: row?.policy_reason || row?.status || row?.event_stage || "-",
        output: stringifyTimelineValue(outputValue) || row?.event_type || "-",
        communicates_to: row?.transport_channel || "-",
        inputValueText: stringifyTimelineValue(inputValue),
        outputValueText: stringifyTimelineValue(outputValue),
        errorValueText: extractEventError(row),
        backgroundDetailText: buildBackgroundDetailText(row),
      };
    });

    if (!traceRows.length) {
      return mappedEvents.map((row, index) => ({
        ...row,
        sequence: index + 1,
      }));
    }

    const mergedRows = [...mappedEvents];
    const seen = new Set(
      mappedEvents.map((row) => `${String(row.agent || "").toLowerCase()}|${String(row.action || "").toLowerCase()}|${String(row.decision || "").toLowerCase()}`)
    );

    traceRows.forEach((row) => {
      const key = `${String(row.agent || "").toLowerCase()}|${String(row.action || "").toLowerCase()}|${String(row.decision || "").toLowerCase()}`;
      if (!seen.has(key)) {
        seen.add(key);
        mergedRows.push(row);
      }
    });

    return mergedRows
      .map((row, index) => ({ ...row, sequence: index + 1 }))
      .slice(0, 300);
  }, [selectedAlertEvents, selectedAlertEventTrace]);

  const selectedAlertRagDocuments = useMemo(
    () => {
      if (Array.isArray(selectedAlertDocumentLinks.rows) && selectedAlertDocumentLinks.rows.length) {
        return selectedAlertDocumentLinks.rows;
      }
      return findAlertRagDocuments(selectedAlertRow);
    },
    [selectedAlertDocumentLinks.rows, selectedAlertRow, ragDocs.rows],
  );

  const selectedAlertKnowledgeDocument = useMemo(() => {
    const seen = new Set();
    const docs = selectedAlertRagDocuments.filter((doc) => {
      const key = String(doc?.path || doc?.title || doc?.document_id || "").trim().toLowerCase();
      if (!key) {
        return true;
      }
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
    if (!docs.length) {
      return null;
    }
    const first = docs[0] || {};
    const service = Array.isArray(first.services) ? first.services.join(", ") : String(first.services || selectedAlertRow?.service || "-");
    const severity = String(first.severity || selectedAlertRow?.severity || "-").toLowerCase();
    const kinds = Array.from(new Set(docs.map((doc) => String(doc?.kind || doc?.document_kind || "document").trim()).filter(Boolean)));
    const reasons = Array.from(new Set(docs.map((doc) => String(doc?.match_reason || "").trim()).filter(Boolean)));
    const confidence = docs
      .map((doc) => Number(doc?.match_confidence || 0))
      .filter((value) => Number.isFinite(value) && value > 0)
      .sort((a, b) => b - a)[0];
    return {
      title: docs.length === 1
        ? String(first.title || first.path || "Alert Knowledge Document").trim()
        : `${selectedAlertRow?.service || service || "Alert"} Knowledge Document`,
      summary: docs.length === 1
        ? String(first.summary || first.recommended_action || "Backend-linked document is available for download.").trim()
        : `Single dashboard document composed from ${docs.length} backend-linked knowledge source(s).`,
      service,
      severity,
      kinds,
      reasons,
      confidence,
      docs,
    };
  }, [selectedAlertRagDocuments, selectedAlertRow]);

  const selectedAlertDocumentContract = selectedAlertDocumentLinks.contract;

  const selectedAlertDetailsSource = useMemo(() => {
    if (selectedAlertData.loading) {
      return "Loading processed result from monitoring adapter.";
    }
    if (selectedAlertData.payload) {
      return "Processed workflow result from monitoring-adapter; no LLM call required for this view.";
    }
    if (selectedAlertData.error) {
      return "Processed workflow result unavailable; showing alert-stream fallback fields only.";
    }
    return "Alert-stream row selected; processed workflow result has not loaded yet.";
  }, [selectedAlertData.loading, selectedAlertData.payload, selectedAlertData.error]);

  const selectedAlertUsage = useMemo(() => {
    const rows = [];
    const appendUsage = (candidate) => {
      if (!Array.isArray(candidate)) {
        return;
      }
      candidate.forEach((item) => rows.push(normalizeUsageRow(item)));
    };

    const appendErrorUsage = (candidate) => {
      if (!Array.isArray(candidate)) {
        return;
      }
      candidate
        .filter((item) => item && typeof item === "object")
        .forEach((item) => {
          rows.push(normalizeUsageRow({
            task: item.task || item.agent || "llm-error",
            provider: item.provider || item.model_provider || "router",
            model: item.model || item.model_name || "-",
            note: item.error || item.message || item.reason || JSON.stringify(item),
            estimated: true,
          }));
        });
    };

    appendUsage(selectedAlertWorkflow?.recommendation?.metadata?.model_usage);
    appendUsage(selectedAlertWorkflow?.finops?.calls);
    appendUsage(selectedAlertWorkflow?.recommendation?.metadata?.llm_calls);
    appendErrorUsage(selectedAlertWorkflow?.finops?.errors);

    selectedAlertEventTrace.forEach((event) => {
      const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
      appendUsage(payload?.model_usage);
      appendUsage(payload?.llm_calls);
      appendUsage(payload?.finops?.calls);
      appendErrorUsage(payload?.finops?.errors);
    });

    return rows.filter((row) => isMeaningfulUsageRow(row));
  }, [selectedAlertWorkflow, selectedAlertEventTrace]);

  const selectedFinopsDiagnostics = useMemo(() => {
    const workflowCalls = Array.isArray(selectedAlertWorkflow?.finops?.calls)
      ? selectedAlertWorkflow.finops.calls.length
      : 0;
    const workflowErrors = Array.isArray(selectedAlertWorkflow?.finops?.errors)
      ? selectedAlertWorkflow.finops.errors.length
      : 0;
    const recommendationUsage = Array.isArray(selectedAlertWorkflow?.recommendation?.metadata?.model_usage)
      ? selectedAlertWorkflow.recommendation.metadata.model_usage.length
      : 0;

    let traceCalls = 0;
    let traceErrors = 0;
    selectedAlertEventTrace.forEach((row) => {
      const payload = row?.payload && typeof row.payload === "object" ? row.payload : {};
      traceCalls += Array.isArray(payload?.finops?.calls) ? payload.finops.calls.length : 0;
      traceErrors += Array.isArray(payload?.finops?.errors) ? payload.finops.errors.length : 0;
    });

    return {
      usageRows: selectedAlertUsage.length,
      workflowCalls,
      workflowErrors,
      recommendationUsage,
      traceCalls,
      traceErrors,
    };
  }, [selectedAlertWorkflow, selectedAlertEventTrace, selectedAlertUsage]);

  const selectedAlertRouting = useMemo(() => extractObservedRoutingMetrics(selectedAlertWorkflow), [selectedAlertWorkflow]);

  const selectedAlertEvaluation = useMemo(() => {
    const recommendation = selectedAlertWorkflow?.recommendation && typeof selectedAlertWorkflow.recommendation === "object"
      ? selectedAlertWorkflow.recommendation
      : {};
    const metadata = recommendation?.metadata && typeof recommendation.metadata === "object" ? recommendation.metadata : {};
    const evaluation = metadata?.evaluation && typeof metadata.evaluation === "object" ? metadata.evaluation : {};
    const ragMatches = Array.isArray(metadata.rag_matches) ? metadata.rag_matches : [];
    const bestRagMatch = ragMatches.reduce((best, row) => {
      const value = Number(row?.match_confidence ?? row?._similarity ?? row?.similarity ?? row?.score ?? 0);
      return Number.isFinite(value) ? Math.max(best, value) : best;
    }, Number(metadata.rag_top_similarity || 0) || 0);
    const citations = Array.isArray(metadata.citations) ? metadata.citations : [];
    return normalizeEvaluationEnvelope(evaluation, {
      confidence: recommendation?.confidence,
      ragMatchScore: bestRagMatch,
      citationCoverage: Math.min(citations.length / 3, 1),
      evidenceCoverage: Math.min(
        (metadata.runbook_found ? 0.35 : 0)
        + (ragMatches.length ? 0.4 : 0)
        + (selectedAlertRagDocuments.length ? 0.25 : 0),
        1,
      ),
    });
  }, [selectedAlertWorkflow, selectedAlertRagDocuments.length]);

  const selectedIncidentId = useMemo(() => {
    return String(selectedAlertWorkflow?.incident?.id || selectedAlertWorkflow?.incident_id || "").trim();
  }, [selectedAlertWorkflow]);

  const selectedIncidentMetadataRow = useMemo(() => {
    if (!selectedIncidentId) {
      return null;
    }
    const scoped = monitorScopedIncidentMetadata.find(
      (row) => String(row?.incident_id || "").trim() === selectedIncidentId
    );
    if (scoped) {
      return scoped;
    }
    return incidentMetadata.rows.find((row) => String(row?.incident_id || "").trim() === selectedIncidentId) || null;
  }, [selectedIncidentId, monitorScopedIncidentMetadata, incidentMetadata.rows]);

  const selectedExecutionPlan = useMemo(() => {
    const recommendation =
      typeof selectedAlertWorkflow?.recommendation === "object" && selectedAlertWorkflow.recommendation
        ? selectedAlertWorkflow.recommendation
        : {};
    const recommendationMetadata =
      typeof recommendation?.metadata === "object" && recommendation.metadata
        ? recommendation.metadata
        : {};
    const decision =
      (typeof selectedAlertWorkflow?.decision === "object" && selectedAlertWorkflow.decision)
      || (typeof selectedAlertWorkflow?.orchestration_decision === "object" && selectedAlertWorkflow.orchestration_decision)
      || (typeof recommendationMetadata?.orchestration_decision === "object" && recommendationMetadata.orchestration_decision)
      || {};
    const remediationAction =
      typeof selectedAlertWorkflow?.remediation_action === "object" && selectedAlertWorkflow.remediation_action
        ? selectedAlertWorkflow.remediation_action
        : {};
    const commands = deriveExecutionCommands(selectedAlertWorkflow, selectedAlertEventTrace);

    return {
      action:
        recommendation?.recommended_action
        || remediationAction?.action
        || selectedAlertRouting?.next_action
        || selectedAlertWorkflow?.next_step
        || "-",
      rationale:
        recommendation?.rationale
        || remediationAction?.reason
        || selectedAlertRouting?.policy_reason
        || recommendation?.policy_reason
        || "-",
      requiresApproval:
        selectedAlertRouting?.requires_approval
        ?? decision?.requires_approval
        ?? selectedAlertWorkflow?.approval?.required
        ?? "-",
      workflow: selectedAlertRouting?.workflow || decision?.workflow || selectedAlertWorkflow?.scenario?.id || "-",
      executionMode: selectedAlertRouting?.execution_mode || decision?.execution_mode || "-",
      riskTier: selectedAlertRouting?.risk_tier || decision?.risk_tier || "-",
      provider: selectedAlertRouting?.message_bus_provider || decision?.message_bus_provider || "-",
      incidentStatus: selectedAlertWorkflow?.incident?.status || selectedIncidentMetadataRow?.status || "-",
      approvalStatus: selectedAlertWorkflow?.approval?.status || "pending",
      commands,
    };
  }, [selectedAlertWorkflow, selectedAlertRouting, selectedAlertEventTrace, selectedIncidentMetadataRow]);
  const selectedExecutionBreakdown = useMemo(() => {
    const grouped = { commands: [], scripts: [], queries: [] };
    (Array.isArray(selectedExecutionPlan.commands) ? selectedExecutionPlan.commands : []).forEach((item) => {
      const line = String(item || "").trim();
      if (!line) {
        return;
      }
      const normalized = line
        .replace(/^\s*(cmd|command)\s*:/i, "")
        .replace(/^\s*script\s*:/i, "script: ")
        .replace(/^\s*query\s*:/i, "query: ")
        .trim();
      if (!normalized || /^#/.test(normalized) || /^preview only/i.test(normalized) || /^recommended_action/i.test(normalized)) {
        return;
      }
      if (/^script\s*:/i.test(normalized)) {
        grouped.scripts.push(normalized.replace(/^script\s*:/i, "").trim());
        return;
      }
      if (/^query\s*:/i.test(normalized)) {
        grouped.queries.push(normalized.replace(/^query\s*:/i, "").trim());
        return;
      }
      grouped.commands.push(normalized);
    });
    const hasPlan = grouped.commands.length > 0 || grouped.scripts.length > 0 || grouped.queries.length > 0;
    return {
      ...grouped,
      hasPlan,
      incidentStatus: String(selectedExecutionPlan.incidentStatus || "-").trim().toLowerCase(),
      approvalStatus: normalizeApprovalStatus(selectedExecutionPlan.approvalStatus || "pending"),
    };
  }, [selectedExecutionPlan]);

  const selectedApplicationConnection = useMemo(() => {
    const workflowContext = typeof selectedAlertWorkflow?.context === "object" && selectedAlertWorkflow.context
      ? selectedAlertWorkflow.context
      : {};
    const incident = typeof selectedAlertWorkflow?.incident === "object" && selectedAlertWorkflow.incident
      ? selectedAlertWorkflow.incident
      : {};
    const recommendation = typeof selectedAlertWorkflow?.recommendation === "object" && selectedAlertWorkflow.recommendation
      ? selectedAlertWorkflow.recommendation
      : {};
    const metadata = typeof recommendation?.metadata === "object" && recommendation.metadata ? recommendation.metadata : {};
    const service = String(
      selectedAlertRow?.service
      || incident?.service
      || selectedIncidentMetadataRow?.service
      || metadata?.service
      || workflowContext?.service
      || ""
    ).trim();
    const application = String(
      selectedAlertRow?.application
      || selectedAlertRow?.project_name
      || selectedAlertRow?.project
      || selectedIncidentMetadataRow?.application
      || applicationToMonitor
      || ""
    ).trim();
    const appRow = monitoringApps.rows.find((row) => {
      const rowName = String(row?.name || "").trim().toLowerCase();
      const rowService = String(row?.service || row?.labels?.service || "").trim().toLowerCase();
      return (application && rowName === application.toLowerCase()) || (service && rowService === service.toLowerCase());
    }) || {};
    const endpoint = String(
      metadata?.connection_url
      || metadata?.endpoint_url
      || workflowContext?.deployment
      || workflowContext?.observability?.metrics_endpoint
      || appRow?.metrics_endpoint
      || onboardingForm.monitoring_url
      || onboardingForm.prometheus_url
      || ""
    ).trim();
    const environment = String(
      selectedAlertRow?.environment
      || incident?.environment
      || selectedIncidentMetadataRow?.environment
      || metadata?.environment
      || appRow?.environment
      || "prod"
    ).trim();
    const namespace = String(metadata?.namespace || appRow?.namespace || environment || "prod").trim();
    return {
      application: application || "-",
      service: service || "-",
      environment: environment || "prod",
      namespace,
      endpoint: endpoint || "Not configured",
      connection_type: endpoint ? "metrics/application endpoint" : "missing connection details",
      source: endpoint ? "onboarding/application metadata" : "missing",
    };
  }, [
    selectedAlertWorkflow,
    selectedAlertRow,
    selectedIncidentMetadataRow,
    monitoringApps.rows,
    onboardingForm.monitoring_url,
    onboardingForm.prometheus_url,
    applicationToMonitor,
  ]);

  useEffect(() => {
    setRemediationPlanEditor({
      commands: selectedExecutionBreakdown.commands.join("\n"),
      scripts: selectedExecutionBreakdown.scripts.join("\n"),
      queries: selectedExecutionBreakdown.queries.join("\n"),
      connection_url: selectedApplicationConnection.endpoint === "Not configured" ? "" : selectedApplicationConnection.endpoint,
      connection_type: selectedApplicationConnection.connection_type || "application",
      namespace: selectedApplicationConnection.namespace || "",
      notes: "",
    });
    setRemediationExecutionState({ loading: false, result: null, error: "" });
  }, [
    selectedAlertId,
    selectedExecutionBreakdown.commands,
    selectedExecutionBreakdown.scripts,
    selectedExecutionBreakdown.queries,
    selectedApplicationConnection.endpoint,
    selectedApplicationConnection.connection_type,
    selectedApplicationConnection.namespace,
  ]);

  const selectedAlertTimelineRows = useMemo(() => {
    const ingestAt =
      selectedAlertWorkflow?.alert?.created_at ||
      selectedAlertRow?.created_at ||
      selectedAlertRow?.starts_at ||
      "";
    const incidentCreatedAt = selectedAlertWorkflow?.incident?.created_at || selectedIncidentMetadataRow?.created_at || "";

    const workflowRows = selectedAlertEvents
      .filter((event) => event && typeof event === "object")
      .sort((a, b) => {
        const aSeq = Number(a.sequence || 0);
        const bSeq = Number(b.sequence || 0);
        if (aSeq && bSeq && aSeq !== bSeq) {
          return aSeq - bSeq;
        }
        const aTime = parseUtcTimestamp(a.timestamp)?.getTime() || 0;
        const bTime = parseUtcTimestamp(b.timestamp)?.getTime() || 0;
        return aTime - bTime;
      })
      .map((event, index) => {
        const route = routeForAgent(event.agent);
        const inputPayload = extractEventInput(event);
        const outputPayload = extractEventOutput(event);
        const inputObject = typeof inputPayload === "object" && inputPayload ? inputPayload : {};
        const outputObject = typeof outputPayload === "object" && outputPayload ? outputPayload : {};
        const tableHints = [
          ...(Array.isArray(outputObject.table_hints) ? outputObject.table_hints : []),
          ...(Array.isArray(event?.metrics?.table_hints) ? event.metrics.table_hints : []),
        ].filter(Boolean);
        const consumes =
          String(inputObject.source_channel || inputObject.topic || inputObject.from_topic || route?.consumes || "").trim() || "-";
        const publishes =
          String(
            event.communicates_to
            || inputObject.transport_channel
            || inputObject.to_topic
            || outputObject.transport_channel
            || route?.publishes
            || ""
          ).trim() || "-";
        const actionLabel = String(event.action || event.event_type || "").trim();
        const stageName = actionLabel ? summarizeEventType(actionLabel) : `Workflow Event ${index + 1}`;
        const detailParts = [
          compactText(event.status, 40),
          compactText(
            event.decision && typeof event.decision === "object"
              ? JSON.stringify(event.decision)
              : event.decision,
            120
          ),
        ].filter(Boolean);

        return {
          stage: stageName,
          sequence: event.sequence || index + 1,
          agent: displayAgentName(event.agent || "-"),
          service: route?.service || event.service || "-",
          consumes,
          publishes,
          timestamp: event.timestamp || "",
          elapsed: elapsedSeconds(ingestAt || incidentCreatedAt, event.timestamp || ""),
          detail: detailParts.join(" | ") || "Workflow event recorded.",
          tables: tableHints.length ? tableHints.join(", ") : "-",
          inputValueText: stringifyTimelineValue(inputPayload),
          outputValueText: stringifyTimelineValue(outputPayload),
          errorValueText: extractEventError(event),
          backendEvents: [String(event?.event_type || "").trim()].filter(Boolean),
        };
      });

    const traceRows = selectedAlertEventTrace.map((event, index) => {
      const stageName = summarizeEventType(event.event_type);
      const tableHints = Array.isArray(event.table_hints) ? event.table_hints.filter(Boolean) : [];
      const detailParts = [
        compactText(event.event_stage, 40),
        compactText(event.status, 40),
        compactText(event.policy_reason, 120),
      ].filter(Boolean);
      return {
        stage: `${stageName}${index + 1 <= 9 ? ` (${index + 1})` : ""}`,
        sequence: index + 1,
        agent: displayAgentName(normalizeTraceServiceName(event)),
        service: normalizeTraceServiceName(event),
        consumes: event.source_channel || "-",
        publishes: event.transport_channel || "-",
        timestamp: event.timestamp || "",
        elapsed: elapsedSeconds(ingestAt, event.timestamp || ""),
        detail: detailParts.join(" | ") || "Trace event recorded.",
        tables: tableHints.join(", ") || "-",
        inputValueText: stringifyTimelineValue(
          hasMeaningfulValue(event.input_value)
            ? event.input_value
            : {
                source_channel: event.source_channel,
                transport_provider: event.transport_provider,
                risk_tier: event.risk_tier,
                execution_mode: event.execution_mode,
                trace_id: event.trace_id,
              }
        ),
        outputValueText: stringifyTimelineValue(
          hasMeaningfulValue(event.output_value)
            ? { trace_id: event.trace_id, ...event.output_value }
            : {
                event_type: event.event_type,
                event_stage: event.event_stage,
                status: event.status,
                transport_channel: event.transport_channel,
                table_hints: event.table_hints,
                query_hint: event.query_hint,
                trace_id: event.trace_id,
              }
        ),
        errorValueText: stringifyTimelineValue(event.error) || extractEventError(event),
        backendEvents: [String(event?.event_type || "").trim()].filter(Boolean),
      };
    });

    const syntheticRows = buildSyntheticFlowRows({
      workflow: selectedAlertWorkflow,
      events: selectedAlertEvents,
      traceRows: selectedAlertEventTrace,
      ingestAt,
      incidentCreatedAt,
    });

    const baseRows = traceRows.length ? traceRows : workflowRows;
    const orderedRows = [...syntheticRows, ...baseRows]
      .map((row, index) => ({ ...row, __rowIndex: index }))
      .sort((left, right) => {
        const leftPhase = timelinePhaseOrder(left);
        const rightPhase = timelinePhaseOrder(right);
        if (leftPhase !== rightPhase) {
          return leftPhase - rightPhase;
        }

        const leftTime = parseUtcTimestamp(left.timestamp)?.getTime();
        const rightTime = parseUtcTimestamp(right.timestamp)?.getTime();
        const leftHasTime = Number.isFinite(leftTime);
        const rightHasTime = Number.isFinite(rightTime);

        if (leftHasTime && rightHasTime && leftTime !== rightTime) {
          return leftTime - rightTime;
        }

        if (leftHasTime !== rightHasTime) {
          return leftHasTime ? -1 : 1;
        }

        const leftSeq = Number(left.sequence || 0);
        const rightSeq = Number(right.sequence || 0);
        if (leftSeq && rightSeq && leftSeq !== rightSeq) {
          return leftSeq - rightSeq;
        }

        return Number(left.__rowIndex || 0) - Number(right.__rowIndex || 0);
      });

    const rows = orderedRows.filter(
      (row, index, allRows) => {
        const stage = String(row.stage || "").trim();
        const agent = String(row.agent || "").trim();
        const timestamp = String(row.timestamp || "").trim();
        const key = `${stage}|${agent}|${timestamp}`;
        return allRows.findIndex((candidate) => {
          const cStage = String(candidate.stage || "").trim();
          const cAgent = String(candidate.agent || "").trim();
          const cTime = String(candidate.timestamp || "").trim();
          return `${cStage}|${cAgent}|${cTime}` === key;
        }) === index;
      }
    ).map((row) => {
      const { __rowIndex, ...rest } = row;
      return rest;
    });

    if (rows.length) {
      return rows;
    }

    const fallbackStatus = String(selectedIncidentMetadataRow?.status || selectedAlertWorkflow?.incident?.status || "").trim();
    if (!fallbackStatus) {
      return [];
    }

    return [
      {
        stage: "Current Incident Status",
        agent: "incident-projection",
        service: "monitoring-adapter",
        consumes: "-",
        publishes: "-",
        timestamp: selectedIncidentMetadataRow?.updated_at || selectedIncidentMetadataRow?.latest_event_at || incidentCreatedAt || ingestAt,
        elapsed: "-",
        detail: fallbackStatus,
        tables: "-",
        inputValueText: "",
        outputValueText: stringifyTimelineValue(selectedIncidentMetadataRow),
        errorValueText: "",
      },
    ];
  }, [selectedAlertWorkflow, selectedAlertRow, selectedIncidentMetadataRow, selectedAlertEvents, selectedAlertEventTrace]);

  const selectedWorkflowFlowStages = useMemo(
    () => buildWorkflowFlowStages(selectedAlertWorkflow, selectedAlertTimelineRows),
    [selectedAlertWorkflow, selectedAlertTimelineRows],
  );

  const hasSelectedWorkflowData = useMemo(() => {
    if (!selectedAlertWorkflow || typeof selectedAlertWorkflow !== "object") {
      return false;
    }
    const events = Array.isArray(selectedAlertWorkflow.events) ? selectedAlertWorkflow.events : [];
    return Boolean(events.length || selectedAlertWorkflow.incident || selectedAlertWorkflow.recommendation);
  }, [selectedAlertWorkflow]);

  const panelWorkflow = useMemo(() => {
    return hasSelectedWorkflowData ? selectedAlertWorkflow : latestWorkflow;
  }, [hasSelectedWorkflowData, selectedAlertWorkflow, latestWorkflow]);

  const panelWorkflowEvents = useMemo(() => {
    const events = panelWorkflow?.events || [];
    return Array.isArray(events) ? events : [];
  }, [panelWorkflow]);

  const panelWorkflowUsage = useMemo(() => {
    const directUsage = panelWorkflow?.recommendation?.metadata?.model_usage;
    if (Array.isArray(directUsage) && directUsage.length) {
      return directUsage;
    }
    const finopsCalls = panelWorkflow?.finops?.calls;
    if (Array.isArray(finopsCalls)) {
      return finopsCalls;
    }
    return [];
  }, [panelWorkflow]);

  const allUsageRows = useMemo(() => {
    const merged = [];

    const appendUsage = (candidate) => {
      if (!Array.isArray(candidate)) {
        return;
      }
      candidate.forEach((row) => {
        merged.push(normalizeUsageRow(row));
      });
    };

    appendUsage(panelWorkflowUsage);
    appendUsage(selectedAlertUsage);
    appendUsage(latestWorkflow?.finops?.calls);
    appendUsage(latestWorkflow?.recommendation?.metadata?.model_usage);
    appendUsage(latestWorkflow?.recommendation?.metadata?.llm_calls);

    monitorScopedIncidentMetadata.forEach((row) => {
      appendUsage(row?.finops?.calls);
      appendUsage(row?.model_usage);
      appendUsage(row?.llm_usage);

      const synthetic = normalizeUsageRow({
        task: row?.latest_event_type || "incident",
        provider: row?.provider || row?.llm_provider,
        model: row?.model || row?.llm_model,
        input_tokens: row?.input_tokens,
        output_tokens: row?.output_tokens,
        total_tokens: row?.total_tokens,
        total_cost_usd: row?.total_cost_usd || row?.cost_usd,
      });
      if (isMeaningfulUsageRow(synthetic)) {
        merged.push(synthetic);
      }
    });

    gatewayRecent.rows.forEach((row) => {
      appendUsage(row?.finops?.calls);
      appendUsage(row?.model_usage);
      appendUsage(row?.llm_usage);
    });

    return merged.filter((row) => isMeaningfulUsageRow(row));
  }, [panelWorkflowUsage, selectedAlertUsage, latestWorkflow, monitorScopedIncidentMetadata, gatewayRecent.rows]);

  useEffect(() => {
    if (activeTab !== "home" || homeDetailTab !== "diagnostics" || diagnosticsDetailTab !== "api") {
      return;
    }
    loadGatewayRecent();
  }, [activeTab, homeDetailTab, diagnosticsDetailTab]);

  const workflowEventRows = useMemo(() => {
    const mapped = panelWorkflowEvents
      .filter((event) => event && typeof event === "object")
      .sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0))
      .map((event) => {
        const decisionValue = event.decision;
        const outputValue = event.output;
        return {
          sequence: event.sequence || "-",
            agent: displayAgentName(event.agent || "-"),
          action: event.action || "-",
          decision: typeof decisionValue === "object" ? JSON.stringify(decisionValue) : String(decisionValue || "-"),
          output: typeof outputValue === "object" ? JSON.stringify(outputValue) : String(outputValue || "-"),
          communicates_to: event.communicates_to || "-",
        };
      });
    if (mapped.length) {
      return mapped;
    }
    return gatewayRecent.rows.slice(0, 80).map((event, index) => ({
      sequence: index + 1,
      agent: displayAgentName("API Gateway"),
      action: event.path || "gateway.event",
      decision: event?.safety?.decision || "-",
      output: String(event.status_code || "-") + (event.trace_id ? ` | trace ${event.trace_id}` : ""),
      communicates_to: event.target_url || "monitoring-adapter",
    }));
  }, [panelWorkflowEvents, gatewayRecent.rows]);

  const observedRouting = useMemo(() => extractObservedRoutingMetrics(panelWorkflow), [panelWorkflow]);

  const messageBusTopicRows = useMemo(() => {
    return SERVICE_TOPIC_FLOW.map((row) => ({
      service: row.service,
      consumes: row.consumes === "-" ? "-" : `${row.consumes} (enabled transports)`,
      publishes: row.publishes,
    }));
  }, []);

  const messageBusActual = useMemo(() => {
    const workflow = panelWorkflow;
    const events = Array.isArray(workflow.events) ? workflow.events : [];
    const traceRows = Array.isArray(workflow.event_trace) ? workflow.event_trace : [];
    const observedAgents = new Set(events.map((item) => String(item?.agent || "").trim()));
    const observedServices = new Set(traceRows.map((item) => String(item?.service || "").trim()));
    const observedProvider = String(observedRouting?.message_bus_provider || "").trim().toUpperCase() || "N/A";
    const approval = typeof workflow.approval === "object" ? workflow.approval : {};
    const remediation = typeof workflow.remediation_action === "object" ? workflow.remediation_action : {};
    const closure = typeof workflow.closure_report === "object" ? workflow.closure_report : {};
    const hasWorkflow = Boolean(workflow.alert || workflow.incident || events.length);
    const observedChannels = new Set();
    traceRows.forEach((row) => {
      const source = String(row?.source_channel || "").trim();
      const transport = String(row?.transport_channel || "").trim();
      if (source) {
        observedChannels.add(source);
      }
      if (transport) {
        observedChannels.add(transport);
      }
    });

    const published = [];
    const consumed = [];
    const rows = SERVICE_TOPIC_FLOW.map((row) => {
      let isObserved = false;
      if (row.agent === "alert") {
        isObserved = hasWorkflow;
      } else if (observedAgents.has(row.agent)) {
        isObserved = true;
      } else if (observedServices.has(row.service)) {
        isObserved = true;
      } else if (row.agent === "Human Approval Layer" && Object.keys(approval).length) {
        isObserved = true;
      } else if (row.agent === "Remediation Automation Engine" && Object.keys(remediation).length) {
        isObserved = true;
      } else if (row.agent === "Closure & Validation" && Object.keys(closure).length) {
        isObserved = true;
      }

      if (isObserved) {
        if (row.consumes !== "-" && !consumed.includes(row.consumes)) {
          consumed.push(row.consumes);
        }
        if (!published.includes(row.publishes)) {
          published.push(row.publishes);
        }
      }

      return {
        service: row.service,
        consumed: isObserved ? row.consumes : "-",
        published: isObserved ? row.publishes : "-",
        provider: observedProvider,
        status: isObserved ? "Observed" : "Not reached",
      };
    });

    observedChannels.forEach((channel) => {
      if (!published.includes(channel)) {
        published.push(channel);
      }
      if (!consumed.includes(channel)) {
        consumed.push(channel);
      }
    });

    return { published, consumed, rows };
  }, [panelWorkflow, observedRouting]);

  const executiveMetrics = useMemo(() => {
    const rows = Array.isArray(gatewayRecent.rows) ? gatewayRecent.rows : [];
    const summaryTotal = toFiniteNumber(gatewaySummary.data?.window_events || gatewaySummary.data?.total_events || 0);
    const recentSuccess = rows.filter((row) => {
      const status = Number(row?.status_code || 0);
      return status >= 200 && status < 400;
    }).length;
    const recentFailure = rows.filter((row) => Number(row?.status_code || 0) >= 400).length;
    const totalRequests = rows.length || summaryTotal;
    const successRequests = rows.length ? recentSuccess : toFiniteNumber(gatewaySummary.data?.allowed || 0);
    const failedRequests = rows.length
      ? recentFailure
      : toFiniteNumber(gatewaySummary.data?.blocked || 0) + toFiniteNumber(gatewaySummary.data?.review || 0);
    const latencyValues = rows
      .map((row) => Number(row?.latency_ms ?? row?.gateway?.latency_ms ?? row?.latency ?? 0))
      .filter((value) => Number.isFinite(value) && value > 0);
    const avgLatencyMs = latencyValues.length
      ? latencyValues.reduce((sum, value) => sum + value, 0) / latencyValues.length
      : 0;
    const p95LatencyMs = percentile(latencyValues, 0.95);

    const latencyTrend = rows
      .slice(0, 12)
      .reverse()
      .map((row, index) => {
        const value = Number(row?.latency_ms ?? row?.gateway?.latency_ms ?? row?.latency ?? 0);
        const status = Number(row?.status_code || 0);
        return {
          label: `${index + 1}`,
          value: Number.isFinite(value) ? value : 0,
          displayValue: `${Number.isFinite(value) ? value.toFixed(1) : "0.0"} ms`,
          tone: status >= 400 ? "risk" : "ops",
        };
      });

    const finopsTotals =
      panelWorkflow?.finops?.totals
      || selectedAlertWorkflow?.finops?.totals
      || latestWorkflow?.finops?.totals
      || {};
    const finopsCalls = toFiniteNumber(finopsTotals?.calls || allUsageRows.length);
    const finopsTokens = toFiniteNumber(finopsTotals?.total_tokens || allUsageRows.reduce((sum, row) => sum + toFiniteNumber(row?.total_tokens), 0));
    const finopsCost = toFiniteNumber(finopsTotals?.total_cost_usd || allUsageRows.reduce((sum, row) => sum + toFiniteNumber(row?.total_cost_usd), 0));

    return {
      totalRequests,
      successRequests,
      failedRequests,
      avgLatencyMs,
      p95LatencyMs,
      latencyTrend,
      finopsCalls,
      finopsTokens,
      finopsCost,
    };
  }, [gatewayRecent.rows, gatewaySummary.data, panelWorkflow, selectedAlertWorkflow, latestWorkflow, allUsageRows]);

  const finopsByProvider = useMemo(() => {
    const grouped = new Map();
    allUsageRows.forEach((row) => {
      const key = String(row?.provider || "unknown");
      const current = grouped.get(key) || { provider: key, calls: 0, total_tokens: 0, total_cost_usd: 0 };
      current.calls += 1;
      current.total_tokens += Number(row?.total_tokens || 0);
      current.total_cost_usd += Number(row?.total_cost_usd || 0);
      grouped.set(key, current);
    });
    return Array.from(grouped.values());
  }, [allUsageRows]);

  const closedRiskOptions = useMemo(() => {
    return Array.from(
      new Set(closedIncidents.rows.map((row) => String(row?.risk_tier || row?.risk || "unknown").toLowerCase()))
    ).sort();
  }, [closedIncidents.rows]);

  const closedModeOptions = useMemo(() => {
    return Array.from(
      new Set(closedIncidents.rows.map((row) => String(row?.execution_mode || "unknown").toLowerCase()))
    ).sort();
  }, [closedIncidents.rows]);

  const filteredClosedRows = useMemo(() => {
    return closedIncidents.rows.filter((row) => {
      const risk = String(row?.risk_tier || row?.risk || "unknown").toLowerCase();
      const mode = String(row?.execution_mode || "unknown").toLowerCase();
      const riskPass = closedFilters.risk === "all" || closedFilters.risk === risk;
      const modePass = closedFilters.mode === "all" || closedFilters.mode === mode;
      return riskPass && modePass;
    });
  }, [closedIncidents.rows, closedFilters]);

  const executiveClosedSummary = useMemo(() => {
    const rows = Array.isArray(closedIncidents.rows) ? closedIncidents.rows : [];
    const restored = rows.filter((row) => row?.health_restored === true).length;
    const byRisk = new Map();
    const byMode = new Map();

    rows.forEach((row) => {
      const risk = String(row?.risk_tier || row?.risk || row?.severity || "unknown").toLowerCase();
      const mode = String(row?.execution_mode || "unknown").toLowerCase();
      byRisk.set(risk, (byRisk.get(risk) || 0) + 1);
      byMode.set(mode, (byMode.get(mode) || 0) + 1);
    });

    const riskItems = Array.from(byRisk.entries()).map(([label, value]) => ({ label, value, tone: "risk" }));
    const modeItems = Array.from(byMode.entries()).map(([label, value]) => ({ label, value, tone: "meta" }));

    return {
      total: rows.length,
      restored,
      closureRate: rows.length ? (restored / rows.length) * 100 : 0,
      riskItems,
      modeItems,
      recentRows: rows.slice(0, 15),
    };
  }, [closedIncidents.rows]);

  useEffect(() => {
    if (!latestIncidentId && !latestRecommendationId) {
      return;
    }
    setApprovalForm((current) => ({
      ...current,
      incident_id: latestIncidentId || current.incident_id,
      recommendation_id: latestRecommendationId || current.recommendation_id,
    }));
  }, [latestIncidentId, latestRecommendationId]);

  function approvalIncidentId(row) {
    return String(row?.incident_id || row?.id || row?.alert_id || "").trim();
  }

  function approvalRecommendationId(row) {
    const candidates = [
      row?.recommendation_id,
      row?.recommendation?.id,
      row?.remediation_recommendation_id,
      row?.recommended_action_id,
    ];
    for (const candidate of candidates) {
      const token = String(candidate || "").trim();
      if (looksLikeUuid(token)) {
        return token;
      }
    }
    return "";
  }

  function approvalFlowId(row) {
    return String(row?.flow_id || row?.workflow_id || row?.flow || "").trim();
  }

  function approvalTraceId(row) {
    return String(row?.trace_id || row?.correlation_id || "").trim();
  }

  function approvalRecommendationFromPayload(payload) {
    const normalized = payload && typeof payload === "object" ? payload : {};
    const data = normalized.data && typeof normalized.data === "object" ? normalized.data : {};
    const recommendation = normalized.recommendation && typeof normalized.recommendation === "object"
      ? normalized.recommendation
      : data.recommendation && typeof data.recommendation === "object"
        ? data.recommendation
        : {};
    const approval = normalized.approval && typeof normalized.approval === "object"
      ? normalized.approval
      : data.approval && typeof data.approval === "object"
        ? data.approval
        : {};
    const sourcePayload = normalized.source_payload && typeof normalized.source_payload === "object"
      ? normalized.source_payload
      : data.source_payload && typeof data.source_payload === "object"
        ? data.source_payload
        : {};
    const sourceRecommendation = sourcePayload.recommendation && typeof sourcePayload.recommendation === "object"
      ? sourcePayload.recommendation
      : {};
    const candidates = [
      normalized.recommendation_id,
      data.recommendation_id,
      recommendation.id,
      approval.recommendation_id,
      normalized.remediation_recommendation_id,
      data.remediation_recommendation_id,
      normalized.recommended_action_id,
      data.recommended_action_id,
      sourcePayload.recommendation_id,
      sourceRecommendation.id,
    ];
    for (const candidate of candidates) {
      const token = String(candidate || "").trim();
      if (looksLikeUuid(token)) {
        return token;
      }
    }
    return "";
  }

  function mergeRecommendationIdIntoApprovalRow(incidentId, recommendationId) {
    const normalizedIncidentId = String(incidentId || "").trim();
    const normalizedRecommendationId = String(recommendationId || "").trim();
    if (!normalizedIncidentId || !looksLikeUuid(normalizedRecommendationId)) {
      return;
    }
    const patchRow = (row) => {
      const rowIncidentId = approvalIncidentId(row);
      if (rowIncidentId !== normalizedIncidentId) {
        return row;
      }
      return {
        ...row,
        recommendation_id: normalizedRecommendationId,
        remediation_recommendation_id: row?.remediation_recommendation_id || normalizedRecommendationId,
      };
    };
    setIncidentMetadata((prev) => ({
      ...prev,
      rows: Array.isArray(prev.rows) ? prev.rows.map(patchRow) : prev.rows,
    }));
    setAlerts((prev) => ({
      ...prev,
      rows: Array.isArray(prev.rows) ? prev.rows.map(patchRow) : prev.rows,
    }));
  }

  function approvalFlowFromPayload(payload) {
    const normalized = payload && typeof payload === "object" ? payload : {};
    const decision = normalized.decision && typeof normalized.decision === "object" ? normalized.decision : {};
    const recommendation = normalized.recommendation && typeof normalized.recommendation === "object"
      ? normalized.recommendation
      : {};
    return String(
      normalized.flow_id
      || decision.flow_id
      || recommendation.flow_id
      || normalized.trace_id
      || recommendation.trace_id
      || normalized.correlation_id
      || recommendation.correlation_id
      || ""
    ).trim();
  }

  async function loadApprovalIncidentContext(incidentId, options = {}) {
    const forceRefresh = Boolean(options?.force);
    const normalized = String(incidentId || "").trim();
    if (!normalized) {
      return;
    }
    const now = Date.now();
    const requestState = approvalIncidentRequestRef.current;
    if (requestState.inFlight && requestState.incidentId === normalized) {
      return;
    }
    if (!forceRefresh && (
      approvalIncidentContext.incident_id === normalized
      && approvalIncidentContext.payload
      && now - requestState.lastFetchedAt < 10000
    )) {
      return;
    }

    approvalIncidentRequestRef.current = { ...requestState, incidentId: normalized, inFlight: true };
    setApprovalIncidentContext((current) => ({
      loading: true,
      incident_id: normalized,
      payload: current.incident_id === normalized ? current.payload : null,
      error: "",
    }));
    try {
      const response = await fetchJson(`/api-gateway/approval/incident/${encodeURIComponent(normalized)}`);
      const payload = unwrap(response);
      const recommendationId = approvalRecommendationFromPayload(payload);
      setApprovalIncidentContext({ loading: false, incident_id: normalized, payload, error: "" });
      approvalIncidentRequestRef.current = {
        incidentId: normalized,
        inFlight: false,
        lastFetchedAt: Date.now(),
      };
      if (recommendationId) {
        mergeRecommendationIdIntoApprovalRow(normalized, recommendationId);
        setApprovalForm((current) => ({
          ...current,
          incident_id: normalized || current.incident_id,
          recommendation_id: recommendationId || current.recommendation_id,
        }));
      }
    } catch (error) {
      const raw = String(error?.message || "");
      const brief = raw.includes("HTTP 502") || raw.includes("500 Internal Server Error")
        ? "Approval context service is temporarily unavailable. You can continue using selected incident details."
        : raw;
      approvalIncidentRequestRef.current = {
        incidentId: normalized,
        inFlight: false,
        lastFetchedAt: Date.now(),
      };
      setApprovalIncidentContext({ loading: false, incident_id: normalized, payload: null, error: brief });
    }
  }

  const pendingApprovals = useMemo(() => {
    return monitorScopedIncidentMetadata.filter((row) => {
      const mode = String(row?.execution_mode || "").toLowerCase();
      const status = String(row?.status || "").toLowerCase();
      if (isApprovalPendingStatus(status)) {
        return true;
      }
      return mode === "human-approval" && !isApprovalResolvedStatus(status);
    });
  }, [monitorScopedIncidentMetadata]);

  const filteredPendingApprovals = useMemo(() => {
    return pendingApprovals.filter((row) => {
      if (approvalFilter === "all") {
        return true;
      }
      const severity = String(row?.severity || row?.risk_tier || "").toLowerCase();
      const status = String(row?.status || "").toLowerCase();
      if (approvalFilter === "awaiting_approval") {
        return status === "awaiting_approval";
      }
      return severity === approvalFilter;
    });
  }, [pendingApprovals, approvalFilter]);

  const pendingApprovalByIncidentId = useMemo(() => {
    const index = new Map();
    pendingApprovals.forEach((row) => {
      const incidentId = approvalIncidentId(row);
      if (incidentId) {
        index.set(incidentId, row);
      }
    });
    return index;
  }, [pendingApprovals]);

  const executiveInsights = useMemo(() => {
    const openRows = monitorScopedIncidentMetadata.filter((row) => !isApprovalResolvedStatus(row?.status || row?.state));
    const slaAtRisk = openRows.filter((row) => {
      const risk = String(row?.risk_tier || row?.risk || row?.severity || "").toLowerCase();
      const mode = String(row?.execution_mode || "").toLowerCase();
      return risk === "high" || risk === "critical" || mode.includes("manual");
    }).length;

    const pendingApprovalAges = pendingApprovals
      .map((row) => parseUtcTimestamp(row?.created_at || row?.updated_at || row?.timestamp)?.getTime() || 0)
      .filter((value) => value > 0)
      .map((time) => Math.max(0, (Date.now() - time) / 60000));
    const avgApprovalWaitMinutes = pendingApprovalAges.length
      ? pendingApprovalAges.reduce((sum, value) => sum + value, 0) / pendingApprovalAges.length
      : 0;

    const closedRows = Array.isArray(closedIncidents.rows) ? closedIncidents.rows : [];
    const autoClosed = closedRows.filter((row) => String(row?.execution_mode || "").toLowerCase().includes("auto")).length;
    const automationRate = closedRows.length ? (autoClosed / closedRows.length) * 100 : 0;

    const dayBuckets = Array.from({ length: 7 }).map((_, idx) => {
      const date = new Date();
      date.setHours(0, 0, 0, 0);
      date.setDate(date.getDate() - (6 - idx));
      const key = date.toISOString().slice(0, 10);
      return { key, label: date.toLocaleDateString(undefined, { month: "short", day: "numeric" }), open: 0, closed: 0 };
    });
    const bucketMap = new Map(dayBuckets.map((item) => [item.key, item]));

    monitorScopedAlerts.forEach((row) => {
      const parsed = parseUtcTimestamp(row?.created_at || row?.starts_at);
      if (!parsed) {
        return;
      }
      const key = parsed.toISOString().slice(0, 10);
      const bucket = bucketMap.get(key);
      if (bucket) {
        bucket.open += 1;
      }
    });

    closedRows.forEach((row) => {
      const parsed = parseUtcTimestamp(row?.closed_at || row?.updated_at || row?.created_at);
      if (!parsed) {
        return;
      }
      const key = parsed.toISOString().slice(0, 10);
      const bucket = bucketMap.get(key);
      if (bucket) {
        bucket.closed += 1;
      }
    });

    const weeklyOpenTrend = dayBuckets.map((item) => ({ label: item.label, value: item.open, tone: "risk" }));
    const weeklyClosedTrend = dayBuckets.map((item) => ({ label: item.label, value: item.closed, tone: "ops" }));

    return {
      openIncidents: openRows.length,
      slaAtRisk,
      avgApprovalWaitMinutes,
      automationRate,
      weeklyOpenTrend,
      weeklyClosedTrend,
    };
  }, [monitorScopedIncidentMetadata, pendingApprovals, closedIncidents.rows, monitorScopedAlerts]);

  const selectedApprovalRow = useMemo(() => {
    return filteredPendingApprovals.find((row) => approvalIncidentId(row) === selectedApprovalIncidentId) || null;
  }, [filteredPendingApprovals, selectedApprovalIncidentId]);

  const selectedApprovalRecommendationId = useMemo(() => {
    if (selectedApprovalRow) {
      const rowRecommendationId = approvalRecommendationId(selectedApprovalRow);
      if (rowRecommendationId) {
        return rowRecommendationId;
      }
    }
    if (approvalIncidentContext.incident_id && approvalIncidentContext.incident_id === selectedApprovalIncidentId) {
      return approvalRecommendationFromPayload(approvalIncidentContext.payload);
    }
    return "";
  }, [selectedApprovalRow, approvalIncidentContext, selectedApprovalIncidentId]);

  const selectedApprovalFlowContext = useMemo(() => {
    if (selectedApprovalRow) {
      const rowFlow = approvalFlowId(selectedApprovalRow) || approvalTraceId(selectedApprovalRow);
      if (rowFlow) {
        return rowFlow;
      }
    }
    if (approvalIncidentContext.incident_id && approvalIncidentContext.incident_id === selectedApprovalIncidentId) {
      return approvalFlowFromPayload(approvalIncidentContext.payload);
    }
    return "";
  }, [selectedApprovalRow, approvalIncidentContext, selectedApprovalIncidentId]);

  useEffect(() => {
    if (!selectedApprovalIncidentId) {
      return;
    }
    setApprovalForm((current) => {
      const nextIncidentId = String(selectedApprovalIncidentId || "").trim() || current.incident_id;
      const nextRecommendationId = String(selectedApprovalRecommendationId || "").trim() || current.recommendation_id;
      if (nextIncidentId === current.incident_id && nextRecommendationId === current.recommendation_id) {
        return current;
      }
      return {
        ...current,
        incident_id: nextIncidentId,
        recommendation_id: nextRecommendationId,
      };
    });
  }, [selectedApprovalIncidentId, selectedApprovalRecommendationId]);

  useEffect(() => {
    if (!filteredPendingApprovals.length) {
      if (selectedApprovalIncidentId) {
        setSelectedApprovalIncidentId("");
      }
      return;
    }
    const selectedExists = filteredPendingApprovals.some((row) => approvalIncidentId(row) === selectedApprovalIncidentId);
    if (selectedExists) {
      return;
    }
    setSelectedApprovalIncidentId(approvalIncidentId(filteredPendingApprovals[0]));
  }, [filteredPendingApprovals, selectedApprovalIncidentId]);

  useEffect(() => {
    if (!selectedApprovalIncidentId) {
      return;
    }
    loadApprovalIncidentContext(selectedApprovalIncidentId);
  }, [selectedApprovalIncidentId]);

  function selectApprovalIncident(row) {
    const incidentId = approvalIncidentId(row);
    const recommendationId = approvalRecommendationId(row);
    if (!incidentId) {
      return;
    }
    setSelectedApprovalIncidentId(incidentId);
    setApprovalForm((current) => ({
      ...current,
      incident_id: incidentId || current.incident_id,
      recommendation_id: recommendationId || current.recommendation_id,
    }));
    setApprovalState({ loading: false, result: null, error: "" });
    loadApprovalIncidentContext(incidentId);
  }

  function resolvePendingApprovalFromAlertRow(alertRow) {
    const directIncidentId = approvalIncidentId(alertRow);
    if (directIncidentId && pendingApprovalByIncidentId.has(directIncidentId)) {
      return pendingApprovalByIncidentId.get(directIncidentId) || null;
    }

    const service = String(alertRow?.service || "").trim().toLowerCase();
    const severity = String(alertRow?.severity || "").trim().toLowerCase();
    if (!service) {
      return null;
    }

    const byServiceAndSeverity = pendingApprovals.find((row) => {
      const rowService = String(row?.service || "").trim().toLowerCase();
      const rowSeverity = String(row?.severity || row?.risk_tier || "").trim().toLowerCase();
      return rowService === service && (!severity || !rowSeverity || rowSeverity === severity);
    });
    if (byServiceAndSeverity) {
      return byServiceAndSeverity;
    }

    return pendingApprovals.find((row) => String(row?.service || "").trim().toLowerCase() === service) || null;
  }

  function selectApprovalFromAlertRow(alertRow) {
    const matchedRow = resolvePendingApprovalFromAlertRow(alertRow);
    if (!matchedRow) {
      setApprovalState((current) => ({
        ...current,
        error: "No pending approval incident matched this alert. Open incident details or adjust the pending filter.",
      }));
      return null;
    }
    selectApprovalIncident(matchedRow);
    approvalQueueRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    return matchedRow;
  }

  function applyApprovalResolutionToUi(incidentId, nextStatus, comment = "") {
    const normalizedIncidentId = String(incidentId || "").trim();
    const normalizedStatus = String(nextStatus || "").trim().toLowerCase();
    if (!normalizedIncidentId || !normalizedStatus) {
      return;
    }

    const patchIncidentRow = (row) => {
      const rowIncidentId = String(row?.incident_id || row?.id || "").trim();
      if (rowIncidentId !== normalizedIncidentId) {
        return row;
      }
      return {
        ...row,
        status: normalizedStatus,
        approval_status: normalizedStatus,
        updated_at: new Date().toISOString(),
        latest_comment: comment || row?.latest_comment || "",
      };
    };

    setIncidentMetadata((prev) => ({
      ...prev,
      rows: Array.isArray(prev.rows) ? prev.rows.map(patchIncidentRow) : prev.rows,
    }));

    setAlerts((prev) => ({
      ...prev,
      rows: Array.isArray(prev.rows)
        ? prev.rows.map((row) => {
            const rowIncidentId = String(row?.incident_id || "").trim();
            if (rowIncidentId !== normalizedIncidentId) {
              return row;
            }
            return {
              ...row,
              status: normalizedStatus,
              state: normalizedStatus,
              updated_at: new Date().toISOString(),
            };
          })
        : prev.rows,
    }));

    setSelectedAlertData((prev) => {
      const payloadRoot = prev?.payload?.data || prev?.payload;
      if (!payloadRoot || typeof payloadRoot !== "object") {
        return prev;
      }
      const workflow = payloadRoot?.workflow || payloadRoot;
      const workflowIncidentId = String(workflow?.incident?.id || workflow?.incident_id || "").trim();
      if (workflowIncidentId !== normalizedIncidentId) {
        return prev;
      }

      const nextWorkflow = {
        ...(workflow || {}),
        incident: {
          ...(workflow?.incident || {}),
          status: normalizedStatus,
          updated_at: new Date().toISOString(),
        },
        approval: {
          ...(workflow?.approval || {}),
          status: normalizedStatus,
          comment: comment || workflow?.approval?.comment || "",
        },
      };

      if (prev?.payload?.data && typeof prev.payload === "object") {
        return {
          ...prev,
          payload: {
            ...prev.payload,
            data: {
              ...payloadRoot,
              workflow: nextWorkflow,
            },
          },
        };
      }

      return {
        ...prev,
        payload: {
          ...payloadRoot,
          workflow: nextWorkflow,
        },
      };
    });

    setApprovalIncidentContext((prev) => {
      if (String(prev?.incident_id || "").trim() !== normalizedIncidentId) {
        return prev;
      }
      const root = prev?.payload && typeof prev.payload === "object" ? prev.payload : {};
      const data = root?.data && typeof root.data === "object" ? root.data : root;
      const patched = {
        ...data,
        status: normalizedStatus,
        state: normalizedStatus,
        approval_status: normalizedStatus,
        updated_at: new Date().toISOString(),
      };
      return {
        ...prev,
        payload: root?.data ? { ...root, data: patched } : patched,
        error: "",
      };
    });
  }

  const approvalReady = useMemo(() => {
    const hasBase = String(approvalForm.incident_id || selectedApprovalIncidentId || "").trim() && String(approvalForm.approver || "").trim();
    if (!hasBase) {
      return false;
    }
    if (approvalForm.action !== "modify") {
      return true;
    }
    return String(approvalForm.modified_action || "").trim().length > 0;
  }, [approvalForm]);

  async function executeApprovalAction({
    incidentId,
    recommendationId,
    action,
    approver,
    channel,
    comment,
    modifiedAction,
  }) {
    const normalizedIncidentId = String(incidentId || "").trim();
    const normalizedRecommendationId = String(recommendationId || "").trim();
    const normalizedAction = String(action || "approve").trim().toLowerCase() || "approve";

    if (!looksLikeUuid(normalizedIncidentId) || !looksLikeUuid(normalizedRecommendationId)) {
      throw new Error("Approval requires valid UUID incident_id and recommendation_id. Select a pending row and sync context first.");
    }

    const payload = {
      incident_id: normalizedIncidentId,
      recommendation_id: normalizedRecommendationId,
      approver: String(approver || "").trim(),
      channel: String(channel || "web").trim(),
      comment: String(comment || "").trim() || null,
    };

    if (normalizedAction === "modify") {
      payload.modified_action = String(modifiedAction || "").trim();
    }

    return fetchJson(`/api-gateway/approval/${normalizedAction}`, authenticatedOptions({
      method: "POST",
      body: JSON.stringify(payload),
    }));
  }

  async function resolveRecommendationIdForIncident(incidentId, preferredRecommendationId = "") {
    const normalizedIncidentId = String(incidentId || "").trim();
    const preferred = String(preferredRecommendationId || "").trim();
    if (looksLikeUuid(preferred)) {
      return preferred;
    }

    if (approvalIncidentContext.incident_id === normalizedIncidentId) {
      const fromContext = approvalRecommendationFromPayload(approvalIncidentContext.payload);
      if (looksLikeUuid(fromContext)) {
        return fromContext;
      }
    }

    const response = await fetchJson(`/api-gateway/approval/incident/${encodeURIComponent(normalizedIncidentId)}`);
    const payload = unwrap(response);
    const resolved = approvalRecommendationFromPayload(payload);
    if (looksLikeUuid(resolved)) {
      setApprovalIncidentContext({ loading: false, incident_id: normalizedIncidentId, payload, error: "" });
      mergeRecommendationIdIntoApprovalRow(normalizedIncidentId, resolved);
      setApprovalForm((current) => ({
        ...current,
        incident_id: normalizedIncidentId || current.incident_id,
        recommendation_id: resolved || current.recommendation_id,
      }));
      return resolved;
    }
    return "";
  }

  async function approveIncidentRow(row) {
    const incidentId = approvalIncidentId(row);
    const rowRecommendationId = approvalRecommendationId(row);
    setSelectedApprovalIncidentId(incidentId);
    setApprovalState({ loading: true, result: null, error: "" });

    try {
      const recommendationId = await resolveRecommendationIdForIncident(incidentId, rowRecommendationId);
      if (!looksLikeUuid(recommendationId)) {
        throw new Error("Recommendation ID is still unavailable after syncing approval context. Re-run the incident workflow or open the incident details to regenerate the recommendation.");
      }
      const response = await executeApprovalAction({
        incidentId,
        recommendationId,
        action: "approve",
        approver: approvalForm.approver,
        channel: approvalForm.channel,
        comment: approvalForm.comment,
      });
      setApprovalForm((current) => ({
        ...current,
        action: "approve",
        incident_id: incidentId || current.incident_id,
        recommendation_id: recommendationId || current.recommendation_id,
      }));
      applyApprovalResolutionToUi(incidentId, "remediating", approvalForm.comment);
      setApprovalState({ loading: false, result: response, error: "" });
      loadApprovalIncidentContext(incidentId, { force: true });
      refreshApprovalDrivenViewsSoon(incidentId);
    } catch (error) {
      const raw = String(error?.message || "");
      const concise = raw.includes("HTTP 422")
        ? "Inline approve could not submit because the approval service rejected the recommendation_id. I synced the context automatically; if this persists, rerun the incident workflow."
        : raw;
      setApprovalState({ loading: false, result: null, error: concise });
    }
  }

  async function rejectIncidentRow(row) {
    const incidentId = approvalIncidentId(row);
    const rowRecommendationId = approvalRecommendationId(row);
    setSelectedApprovalIncidentId(incidentId);
    setApprovalState({ loading: true, result: null, error: "" });

    try {
      const recommendationId = await resolveRecommendationIdForIncident(incidentId, rowRecommendationId);
      if (!looksLikeUuid(recommendationId)) {
        throw new Error("Recommendation ID is still unavailable after syncing approval context. Re-run the incident workflow or open the incident details to regenerate the recommendation.");
      }
      const response = await executeApprovalAction({
        incidentId,
        recommendationId,
        action: "reject",
        approver: approvalForm.approver,
        channel: approvalForm.channel,
        comment: inlineRejectState.comment,
      });
      setApprovalForm((current) => ({
        ...current,
        action: "reject",
        incident_id: incidentId || current.incident_id,
        recommendation_id: recommendationId || current.recommendation_id,
        comment: inlineRejectState.comment || current.comment,
      }));
      applyApprovalResolutionToUi(incidentId, "failed", inlineRejectState.comment);
      setInlineRejectState({ incidentId: "", comment: "" });
      setApprovalState({ loading: false, result: response, error: "" });
      loadApprovalIncidentContext(incidentId, { force: true });
      refreshApprovalDrivenViewsSoon(incidentId);
    } catch (error) {
      const raw = String(error?.message || "");
      const concise = raw.includes("HTTP 422")
        ? "Inline reject could not submit because the approval service rejected the recommendation_id. I synced the context automatically; if this persists, rerun the incident workflow."
        : raw;
      setApprovalState({ loading: false, result: null, error: concise });
    }
  }

  async function submitApproval(event) {
    event.preventDefault();
    setApprovalState({ loading: true, result: null, error: "" });
    try {
      const incidentId = String(approvalForm.incident_id || selectedApprovalIncidentId || "").trim();
      const approver = String(approvalForm.approver || adminSession?.user?.username || "admin").trim();
      if (!looksLikeUuid(incidentId)) {
        throw new Error("Select a valid incident first (UUID). Use the incident row selector or Sync From Approval API.");
      }
      if (!approver) {
        throw new Error("Approver is required.");
      }
      const recommendationIdCandidate = String(
        approvalForm.recommendation_id
        || selectedApprovalRecommendationId
        || approvalRecommendationFromPayload(approvalIncidentContext.payload)
        || ""
      ).trim();
      const recommendationId = await resolveRecommendationIdForIncident(incidentId, recommendationIdCandidate);
      const response = await executeApprovalAction({
        incidentId,
        recommendationId,
        action: approvalForm.action,
        approver,
        channel: approvalForm.channel,
        comment: approvalForm.comment,
        modifiedAction: approvalForm.modified_action,
      });
      const actionStatus = approvalForm.action === "reject" ? "failed" : "remediating";
      applyApprovalResolutionToUi(incidentId, actionStatus, approvalForm.comment);
      setApprovalState({ loading: false, result: response, error: "" });
      loadApprovalIncidentContext(incidentId, { force: true });
      refreshApprovalDrivenViewsSoon(incidentId);
    } catch (error) {
      const raw = String(error?.message || "");
      const concise = raw.includes("HTTP 422")
        ? "Approval payload was rejected (422). Confirm incident_id and recommendation_id are valid UUIDs from the selected pending incident."
        : raw;
      setApprovalState({ loading: false, result: null, error: concise });
    }
  }

  async function executeApprovedRemediationPlan() {
    const incidentId = String(approvalForm.incident_id || selectedIncidentId || selectedApprovalIncidentId || "").trim();
    const recommendationIdCandidate = String(
      approvalForm.recommendation_id
      || selectedApprovalRecommendationId
      || approvalRecommendationFromPayload(approvalIncidentContext.payload)
      || selectedAlertWorkflow?.recommendation?.id
      || ""
    ).trim();
    const approver = String(approvalForm.approver || adminSession?.user?.username || "admin").trim();
    const approvalStatus = normalizeApprovalStatus(selectedExecutionPlan.approvalStatus || approvalForm.action);
    const editedPlan = {
      commands: toPlanLines(remediationPlanEditor.commands),
      scripts: toPlanLines(remediationPlanEditor.scripts),
      queries: toPlanLines(remediationPlanEditor.queries),
    };
    const hasPlan = editedPlan.commands.length || editedPlan.scripts.length || editedPlan.queries.length;

    setRemediationExecutionState({ loading: true, result: null, error: "" });
    try {
      if (!looksLikeUuid(incidentId)) {
        throw new Error("Remediation execution requires a valid incident_id. Select an alert with an incident or sync approval context.");
      }
      const recommendationId = await resolveRecommendationIdForIncident(incidentId, recommendationIdCandidate);
      if (!looksLikeUuid(recommendationId)) {
        throw new Error("Remediation execution requires a valid recommendation_id from the approved incident.");
      }
      if (!hasPlan) {
        throw new Error("Add at least one command, script, or validation query before executing.");
      }
      if (!["approved", "modified"].includes(approvalStatus) && approvalForm.action !== "approve" && approvalForm.action !== "modify") {
        throw new Error("Approve or modify the remediation first, then execute the approved plan.");
      }

      const planText = [
        editedPlan.commands.length ? `Commands:\n${editedPlan.commands.map((item) => `- ${item}`).join("\n")}` : "",
        editedPlan.scripts.length ? `Scripts:\n${editedPlan.scripts.map((item) => `- ${item}`).join("\n")}` : "",
        editedPlan.queries.length ? `Queries:\n${editedPlan.queries.map((item) => `- ${item}`).join("\n")}` : "",
      ].filter(Boolean).join("\n\n");
      const payload = {
        incident_id: incidentId,
        recommendation_id: recommendationId,
        decision: approvalForm.action === "modify" ? "modified" : "approved",
        approver,
        channel: approvalForm.channel || "web",
        comment: String(approvalForm.comment || remediationPlanEditor.notes || "approved remediation execution").trim(),
        modified_action: planText,
        metadata: {
          recommended_action: selectedExecutionPlan.action,
          recommended_commands: [
            ...editedPlan.commands,
            ...editedPlan.scripts.map((item) => `script: ${item}`),
            ...editedPlan.queries.map((item) => `query: ${item}`),
          ],
          execution_plan: editedPlan,
          service: selectedApplicationConnection.service !== "-" ? selectedApplicationConnection.service : undefined,
          environment: selectedApplicationConnection.environment,
          remediation_target: selectedApplicationConnection.service !== "-" ? selectedApplicationConnection.service : selectedApplicationConnection.application,
          connection_profile: {
            application: selectedApplicationConnection.application,
            service: selectedApplicationConnection.service,
            environment: selectedApplicationConnection.environment,
            namespace: String(remediationPlanEditor.namespace || selectedApplicationConnection.namespace || "").trim(),
            endpoint_url: String(remediationPlanEditor.connection_url || "").trim(),
            connection_type: String(remediationPlanEditor.connection_type || selectedApplicationConnection.connection_type || "").trim(),
            source: selectedApplicationConnection.source,
          },
          ui_edited: true,
        },
      };
      const response = await fetchJson("/api-gateway/remediation/execute", authenticatedOptions({
        method: "POST",
        body: JSON.stringify(payload),
      }));
      setRemediationExecutionState({ loading: false, result: response, error: "" });
      applyApprovalResolutionToUi(incidentId, "remediating", approvalForm.comment);
      await refreshApprovalDrivenViews(incidentId);
    } catch (error) {
      setRemediationExecutionState({ loading: false, result: null, error: String(error?.message || error) });
    }
  }

  const tabs = [
    { id: "home", label: "Dashboard" },
    { id: "copilot", label: "Copilot Studio" },
    { id: "executive", label: "Executive Dashboard" },
    { id: "admin", label: "Admin Center" },
    { id: "trace", label: "Agent Flow" },
    { id: "safety", label: "Gateway Safety" },
    { id: "rag", label: "Message Bus" },
    { id: "closed", label: "Closed Tickets" },
    { id: "summary", label: "Incident Metadata Explorer" },
    { id: "approval", label: "Approval Queue (Legacy)" },
  ];

  const sidebarSections = [
    { id: "home", icon: "DB", shortLabel: "Dashboard", label: "Dashboard", tone: "ops" },
    { id: "approval", icon: "AL", shortLabel: "Approval", label: "Human Approval", tone: "risk" },
    { id: "executive", icon: "EX", shortLabel: "Executive", label: "Executive Dashboard", tone: "meta" },
    { id: "admin", icon: "AD", shortLabel: "Admin", label: "Admin Center", tone: "bus" },
  ];

  const currentRole = useMemo(() => normalizeRoleName(adminSession?.user?.role_name), [adminSession?.user?.role_name]);
  const projectOnboardingRows = useMemo(
    () => (onboardingState.rows || []).filter((row) => String(row?.provider_name || "").trim().toLowerCase() === "project"),
    [onboardingState.rows],
  );
  const onboardingProjectRowOptions = useMemo(() => {
    const names = new Set();
    (onboardingState.rows || []).forEach((row) => {
      const name = extractOnboardingProjectName(row);
      if (name) {
        names.add(name);
      }
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [onboardingState.rows]);
  const monitoringProjectOptions = useMemo(() => {
    const names = new Set();
    (monitoringApps.rows || []).forEach((row) => {
      const name = String(row?.name || "").trim();
      if (name) {
        names.add(name);
      }
    });
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [monitoringApps.rows]);
  const onboardingProjectOptions = useMemo(() => {
    const names = new Set();
    onboardingProjectRowOptions.forEach((name) => names.add(name));
    monitoringProjectOptions.forEach((name) => names.add(name));
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [onboardingProjectRowOptions, monitoringProjectOptions]);
  const ruleOnboardingRows = useMemo(
    () => (onboardingState.rows || []).filter((row) => {
      const provider = String(row?.provider_name || "").trim().toLowerCase();
      return provider === "existing_rule_sync" || provider === "new_rule_onboarding";
    }),
    [onboardingState.rows],
  );
  const allowedTabs = useMemo(() => ROLE_ALLOWED_TABS[currentRole] || ["home"], [currentRole]);
  const visibleSidebarSections = useMemo(
    () => sidebarSections.filter((tab) => {
      if (!allowedTabs.includes(tab.id)) {
        return false;
      }
      if (tab.id === "approval" && !APPROVAL_NAV_PRIMARY_ROLES.has(currentRole)) {
        return false;
      }
      return true;
    }),
    [sidebarSections, allowedTabs, currentRole],
  );
  const isAuthenticated = Boolean(String(adminSession.accessToken || "").trim());
  const isAdministrator = currentRole === "administrator";
  const canUseApprovalActions = allowedTabs.includes("approval");
  const canManageSeverityOverride = ["administrator", "l2_engineer", "l3_engineer", "p2", "p3"].includes(currentRole);
  const canProvideAlertDocuments = DOCUMENT_PROVIDER_ROLES.has(currentRole);
  const onboardingSourceDocRows = useMemo(
    () => (Array.isArray(onboardingSourceDocs.rows) ? onboardingSourceDocs.rows : []).filter((row) => {
      const text = String(row?.text || "").trim();
      const warning = String(row?.warning || "").trim();
      return Boolean(text) && !warning;
    }),
    [onboardingSourceDocs.rows],
  );
  const onboardingSourceDocCount = onboardingSourceDocRows.length;
  const severityOverrideByKey = useMemo(() => {
    const map = new Map();
    (alertSeverityOverrides.rows || []).forEach((row) => {
      const key = severityOverrideKey(row?.name, row?.service, row?.environment);
      if (key) {
        map.set(key, row);
      }
    });
    return map;
  }, [alertSeverityOverrides.rows]);
  const selectedAlertActionContext = useMemo(() => {
    if (!selectedAlertRow) {
      return null;
    }
    const status = String(selectedAlertRow?.status || selectedAlertRow?.state || "open");
    const alertName = String(selectedAlertRow?.name || selectedAlertRow?.alert_name || "").trim();
    const service = String(selectedAlertRow?.service || "").trim();
    const environment = String(selectedAlertRow?.environment || "").trim();
    const overrideKey = severityOverrideKey(alertName, service, environment);
    const overrideRow = severityOverrideByKey.get(overrideKey);
    return {
      status,
      alertName,
      overrideKey,
      overrideRow,
      documentAvailable: hasAlertDocuments(selectedAlertRow),
      alertClosed: isApprovalResolvedStatus(status),
      draftSeverity: String(
        alertSeverityDrafts[overrideKey]
          || overrideRow?.severity
          || String(selectedAlertRow?.severity || "warning").toLowerCase()
      ).toLowerCase(),
      overrideSaving: alertSeverityOverrides.savingKey === overrideKey,
    };
  }, [selectedAlertRow, severityOverrideByKey, alertSeverityDrafts, alertSeverityOverrides.savingKey]);
  const selectedAlertRuleSummary = useMemo(
    () => summarizeAlertRuleContext(selectedAlertRow, selectedAlertWorkflow),
    [selectedAlertRow, selectedAlertWorkflow],
  );
  const onboardingValidationErrors = useMemo(() => {
    const errors = [];
    if (!String(onboardingForm.name || "").trim()) {
      errors.push("Project name is required.");
    }
    if (!String(onboardingForm.owner_team || "").trim()) {
      errors.push("Owner team is required.");
    }
    if (!String(onboardingForm.region || "").trim()) {
      errors.push("Region is required.");
    }
    if (String(onboardingForm.deployment_mode || "").trim() === "azure_cloud") {
      if (!String(onboardingForm.azure_subscription_id || "").trim()) {
        errors.push("Azure Subscription ID is required for Azure Cloud deployment.");
      }
      if (!String(onboardingForm.azure_service_bus_namespace || "").trim()) {
        errors.push("Azure Service Bus Namespace is required for Azure Cloud deployment.");
      }
      if (!String(onboardingForm.azure_service_bus_topic || "").trim()) {
        errors.push("Azure Service Bus Topic is required for Azure Cloud deployment.");
      }
      if (!String(onboardingForm.azure_service_bus_subscription || "").trim()) {
        errors.push("Azure Service Bus Subscription is required for Azure Cloud deployment.");
      }
    }
    const isSetupMonitoringPath = String(onboardingForm.onboarding_path || "existing_monitoring").trim() === "setup_monitoring";
    const derivedRequirementCount = (Array.isArray(onboardingSourceDocs.rows) ? onboardingSourceDocs.rows : []).reduce(
      (count, row) => count + (Array.isArray(row?.derived_requirements) ? row.derived_requirements.length : 0),
      0,
    );
    if (isSetupMonitoringPath && !String(onboardingForm.rule_onboarding_plain_language || "").trim() && derivedRequirementCount === 0) {
      errors.push("Add plain-English rule intent or upload one Service Knowledge file that produces derived requirements.");
    }
    if (isSetupMonitoringPath && !String(onboardingForm.monitoring_url || "").trim()) {
      errors.push("Prometheus endpoint URL is required for Configure Prometheus Monitoring path.");
    }
    return errors;
  }, [
    onboardingForm.name,
    onboardingForm.owner_team,
    onboardingForm.region,
    onboardingForm.deployment_mode,
    onboardingForm.azure_subscription_id,
    onboardingForm.azure_service_bus_namespace,
    onboardingForm.azure_service_bus_topic,
    onboardingForm.azure_service_bus_subscription,
    onboardingForm.onboarding_path,
    onboardingForm.monitoring_url,
    onboardingForm.rule_onboarding_plain_language,
    onboardingSourceDocs.rows,
    onboardingSourceDocCount,
  ]);
  const onboardingAdvisory = useMemo(() => {
    const onboardingPath = String(onboardingForm.onboarding_path || "existing_monitoring").trim();
    if (onboardingPath === "existing_monitoring") {
      return "Existing monitoring path: upload one Service Knowledge file, save project, then send alerts to /alerts/alertmanager to trigger workflow.";
    }
    if (String(onboardingForm.deployment_mode || "").trim() !== "on_prem") {
      return "";
    }
    if (String(onboardingForm.monitoring_url || "").trim()) {
      return "";
    }
    return "Tool endpoint URL is optional now, but recommended for connectivity and rule simulation quality.";
  }, [onboardingForm.deployment_mode, onboardingForm.monitoring_url, onboardingForm.onboarding_path]);
  const onboardingLandingPadDetails = useMemo(() => {
    const summary = onboardingLandingPadSummary && typeof onboardingLandingPadSummary === "object" ? onboardingLandingPadSummary : {};
    const landingPadPath = String(summary?.landing_pad_endpoint || "/alerts/alertmanager").trim() || "/alerts/alertmanager";
    const selectedTool = String(summary?.selected_monitoring_tool || onboardingForm.monitoring_tool || "prometheus").trim().toLowerCase();
    const configuredEndpoint = String(summary?.configured_monitoring_endpoint || onboardingForm.monitoring_url || "").trim();
    const projectName = String(summary?.project_name || onboardingForm.name || "").trim() || "<project-name>";
    const browserOrigin = typeof window !== "undefined" && window?.location?.origin ? window.location.origin : "http://localhost:8501";
    const onboardingPath = String(onboardingForm.onboarding_path || "existing_monitoring").trim().toLowerCase();
    const routeMessage = String(summary?.message || "").trim() || "Send alerts from your monitoring platform to this landing pad endpoint to trigger workflow execution.";

    const samplePayload = {
      receiver: "kaiops",
      status: "firing",
      alerts: [
        {
          status: "firing",
          labels: {
            alertname: `${projectName}-high-latency`,
            severity: "critical",
            service: projectName,
          },
          annotations: {
            summary: "P95 latency exceeded threshold",
            description: "Checkout latency above 2s for 5 minutes",
          },
          startsAt: "2026-01-01T00:00:00Z",
        },
      ],
    };

    return {
      onboardingPath,
      routeMessage,
      selectedTool,
      configuredEndpoint: configuredEndpoint || "Not set",
      externalIngestionEndpoint: `${browserOrigin}/api-gateway${landingPadPath}`,
      internalIngestionEndpoint: `http://monitoring-adapter:8000${landingPadPath}`,
      method: "POST",
      contentType: "application/json",
      traceHeader: "x-trace-id (optional)",
      samplePayload: JSON.stringify(samplePayload, null, 2),
    };
  }, [onboardingLandingPadSummary, onboardingForm.monitoring_tool, onboardingForm.monitoring_url, onboardingForm.name, onboardingForm.onboarding_path]);
  const onboardingHasPendingDocumentApproval = useMemo(
    () => onboardingGeneratedDocs.length > 0 && !onboardingDocApprovalState.approved,
    [onboardingGeneratedDocs.length, onboardingDocApprovalState.approved],
  );
  const onboardingDocumentSummary = useMemo(
    () => ({
      total: onboardingGeneratedDocs.length,
      approved: onboardingDocApprovalState.approved,
    }),
    [onboardingGeneratedDocs.length, onboardingDocApprovalState.approved],
  );
  const onboardingWizardSteps = useMemo(() => {
    const docsUploaded = onboardingSourceDocCount > 0;
    const requirementsDerived = onboardingDerivedRequirements.length > 0
      || String(onboardingForm.rule_onboarding_plain_language || "").trim().length > 0;
    const ruleGenerated = Boolean(
      onboardingRuleRunState?.result
      || onboardingRuleLookup?.result
      || String(onboardingRuleLookup?.workflow_id || "").trim(),
    );
    const docsApproved = Boolean(onboardingDocApprovalState.approved);
    const metadataStored = String(onboardingState.success || "").toLowerCase().includes("saved")
      || projectOnboardingRows.some((row) => {
        const name = String(row?.project_name || "").trim();
        return name && name === String(selectedOnboardingProject || onboardingForm.name || "").trim();
      });

    return [
      { id: "docs_uploaded", label: "Docs Uploaded", complete: docsUploaded },
      { id: "requirements", label: "Requirements Derived", complete: requirementsDerived },
      { id: "rules", label: "Rules Generated", complete: ruleGenerated },
      { id: "docs_approved", label: "Docs Approved", complete: docsApproved },
      { id: "metadata", label: "Metadata Stored", complete: metadataStored },
    ];
  }, [
    onboardingSourceDocCount,
    onboardingDerivedRequirements.length,
    onboardingForm.rule_onboarding_plain_language,
    onboardingRuleRunState?.result,
    onboardingRuleLookup?.result,
    onboardingRuleLookup?.workflow_id,
    onboardingDocApprovalState.approved,
    onboardingState.success,
    projectOnboardingRows,
    selectedOnboardingProject,
    onboardingForm.name,
  ]);
  const onboardingGeneratedRuleRows = useMemo(() => {
    const primary = normalizeGeneratedRuleRows(onboardingRuleRunState?.result);
    if (primary.length) {
      return primary;
    }
    return normalizeGeneratedRuleRows(onboardingRuleLookup?.result);
  }, [onboardingRuleRunState?.result, onboardingRuleLookup?.result]);
  const onboardingRulePromptLines = useMemo(
    () => String(onboardingForm.rule_onboarding_plain_language || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean),
    [onboardingForm.rule_onboarding_plain_language],
  );
  const onboardingRulePromptVisible = onboardingSourceDocCount > 0 || onboardingRulePromptLines.length > 0 || onboardingGeneratedRuleRows.length > 0;
  const onboardingMetadataRows = useMemo(() => {
    const currentProject = String(selectedOnboardingProject || onboardingForm.name || "").trim();
    const rows = Array.isArray(onboardingState.rows) ? onboardingState.rows : [];
    return rows
      .filter((row) => {
        const projectName = String(row?.project_name || "").trim();
        return currentProject ? projectName === currentProject : true;
      })
      .map((row, index) => ({
        id: `${String(row?.provider_name || "provider")}-${index}`,
        provider: String(row?.provider_name || "-").trim(),
        project: String(row?.project_name || "-").trim(),
        status: String(row?.test_status || row?.status || "-").trim(),
        updated_at: String(row?.updated_at || row?.created_at || "-").trim(),
      }));
  }, [onboardingState.rows, selectedOnboardingProject, onboardingForm.name]);
  const onboardingReviewGate = useMemo(() => {
    const needsRules = onboardingGeneratedRuleRows.length > 0;
    const needsDocs = onboardingGeneratedDocs.length > 0;
    const needsMetadata = onboardingMetadataRows.length > 0;
    const rulesOk = !needsRules || onboardingReviewAck.rules;
    const docsOk = !needsDocs || onboardingReviewAck.docs;
    const metadataOk = !needsMetadata || onboardingReviewAck.metadata;
    return {
      needsRules,
      needsDocs,
      needsMetadata,
      allReviewed: rulesOk && docsOk && metadataOk,
    };
  }, [
    onboardingGeneratedRuleRows.length,
    onboardingGeneratedDocs.length,
    onboardingMetadataRows.length,
    onboardingReviewAck.rules,
    onboardingReviewAck.docs,
    onboardingReviewAck.metadata,
  ]);
  const onboardingNextAction = useMemo(() => {
    const onboardingPath = String(onboardingForm.onboarding_path || "existing_monitoring").trim();
    if (onboardingState.loading) {
      return "Saving setup and generating onboarding artifacts...";
    }
    if (onboardingHasPendingDocumentApproval) {
      return "Review generated documents below, then click Approve Documents.";
    }
    if (onboardingDocumentSummary.approved) {
      return "Documents approved. You can continue with another update or proceed to advanced workflow management.";
    }
    return onboardingPath === "setup_monitoring"
      ? "Step 1: save monitoring setup. Step 2: add Service Knowledge and generate rules."
      : "Step 1: save monitoring setup and landing pad. Step 2: add Service Knowledge and generate documents.";
  }, [
    onboardingState.loading,
    onboardingHasPendingDocumentApproval,
    onboardingDocumentSummary.approved,
    onboardingForm.onboarding_path,
  ]);

  const adminWorkspaceCaptions = useMemo(() => ({
    users: "Manage users, roles, and credentials.",
    monitoring: "Setup monitoring foundations, landing pad routing, and rule/doc generation.",
    project: "Two-step setup: connect monitoring first, then add documents and rules.",
    alerts: "Alert knowledge onboarding and bulk document ingestion.",
  }), []);
  const adminJourneyStep = useMemo(() => {
    if (adminWorkspace === "users") {
      return "access";
    }
    if (adminWorkspace === "alerts" || (adminWorkspace === "project" && projectSetupStep === "knowledge")) {
      return "knowledge";
    }
    return "setup";
  }, [adminWorkspace, projectSetupStep]);
  const adminJourneyCards = useMemo(() => {
    const setupSaved = Boolean(String(onboardingState.success || "").trim()) && !onboardingState.loading && !onboardingState.error;
    const setupComplete = Boolean(onboardingDocumentSummary.approved) || setupSaved || onboardingWorkflowSteps.length > 0;
    const knowledgeComplete = Boolean(alertOnboardingState.result);
    const setupTone = onboardingState.error
      ? "error"
      : onboardingHasPendingDocumentApproval
          ? "warning"
          : setupComplete
            ? "success"
            : "info";
    const knowledgeHasError = Boolean(alertOnboardingState.error);
    const knowledgeTone = knowledgeHasError
      ? "error"
      : knowledgeComplete
        ? "success"
        : "info";
    return [
      {
        id: "access",
        title: "1. Access",
        hint: "Users, roles, session security",
        status: adminUsers.loading
          ? "Loading users and roles..."
          : adminUsers.error
            ? "Unable to load users"
            : adminUsers.rows.length
              ? `${adminUsers.rows.length} users loaded`
              : "No users returned yet. Click Refresh.",
        complete: Boolean(adminUsers.rows.length),
        tone: adminUsers.error ? "error" : adminUsers.rows.length ? "success" : adminUsers.loading ? "warning" : "info",
        cta: "Open access controls",
      },
      {
        id: "setup",
        title: "2. Setup",
        hint: "Unified monitoring + landing pad",
        status: onboardingHasPendingDocumentApproval
          ? "Setup saved. Review generated documents to finalize."
          : onboardingDocumentSummary.approved
            ? "Project docs approved"
            : (setupSaved || onboardingWorkflowSteps.length > 0)
              ? "Project setup saved and synced."
              : onboardingNextAction,
        complete: setupComplete,
        tone: setupTone,
        cta: onboardingHasPendingDocumentApproval
          ? "Review generated artifacts"
          : setupComplete
            ? "Open workflow status"
            : "Continue setup",
      },
      {
        id: "knowledge",
        title: "3. Knowledge",
        hint: "Alert docs onboarding",
        status: knowledgeComplete ? "Knowledge artifacts created" : "Pending knowledge curation",
        complete: knowledgeComplete,
        tone: knowledgeTone,
        cta: knowledgeComplete ? "Review stored knowledge" : "Open knowledge onboarding",
      },
    ];
  }, [
    adminUsers.rows.length,
    adminUsers.loading,
    adminUsers.error,
    onboardingDocumentSummary.approved,
    onboardingNextAction,
    onboardingState.error,
    onboardingState.loading,
    onboardingState.success,
    onboardingHasPendingDocumentApproval,
    onboardingWorkflowSteps.length,
    alertOnboardingState.result,
    alertOnboardingState.error,
  ]);
  const projectStepCards = useMemo(() => {
    const setupSaved = Boolean(String(onboardingState.success || "").trim()) && !onboardingState.loading && !onboardingState.error;
    const monitoringDone = Boolean(String(onboardingForm.name || "").trim())
      && Boolean(String(onboardingForm.owner_team || "").trim())
      && Boolean(String(onboardingForm.region || "").trim());
    const docsRulesDone = Boolean(onboardingSourceDocCount > 0 || onboardingRulePromptLines.length > 0 || onboardingGeneratedDocs.length > 0 || setupSaved);
    return [
      { id: "setup", label: "1. Setup Monitoring", hint: "Project, tool, endpoint, landing pad", complete: monitoringDone },
      { id: "docs_rules", label: "2. Documents & Rules", hint: "Service Knowledge, confidence, rule prompt", complete: docsRulesDone },
    ];
  }, [
    onboardingForm.name,
    onboardingForm.owner_team,
    onboardingForm.region,
    onboardingSourceDocCount,
    onboardingRulePromptLines.length,
    onboardingState.success,
    onboardingState.loading,
    onboardingState.error,
    onboardingGeneratedDocs.length,
  ]);
  const showProjectStep = (stepId) => adminWorkspace !== "project" || projectSetupShowAll || projectSetupStep === stepId;
  const navigateAdminJourney = (stepId) => {
    if (stepId === "access") {
      setAdminWorkspace("users");
      return;
    }
    if (stepId === "knowledge") {
      setAdminWorkspace("alerts");
      setProjectSetupShowAll(false);
      setAlertKnowledgeView("onboarding");
      return;
    }
    setAdminWorkspace("project");
    setProjectSetupShowAll(false);
  };
  const triggerAdminJourneyCta = (stepId) => {
    if (stepId === "setup") {
      setAdminWorkspace("project");
      setProjectSetupShowAll(false);
      if (onboardingHasPendingDocumentApproval) {
        setProjectSetupStep("review");
        return;
      }
      if (onboardingDocumentSummary.approved) {
        setProjectSetupStep("status");
        return;
      }
      setProjectSetupStep("setup");
      return;
    }
    navigateAdminJourney(stepId);
  };

  useEffect(() => {
    if (adminWorkspace !== "project" || projectSetupShowAll) {
      return;
    }
    if (projectSetupStep !== "setup") {
      return;
    }
    if (onboardingState.loading || onboardingState.error) {
      return;
    }
    const success = String(onboardingState.success || "").trim();
    if (!success) {
      return;
    }
    if (success.toLowerCase().includes("documents approved")) {
      return;
    }
    if (onboardingGeneratedDocs.length > 0) {
      setProjectSetupStep("review");
      return;
    }
    if (onboardingSourceDocCount === 0) {
      setProjectSetupStep("setup");
      setAlertKnowledgeView("onboarding");
      alertKnowledgeRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    setProjectSetupStep("status");
  }, [
    adminWorkspace,
    projectSetupShowAll,
    projectSetupStep,
    onboardingState.loading,
    onboardingState.error,
    onboardingState.success,
    onboardingGeneratedDocs.length,
    onboardingSourceDocCount,
  ]);

  useEffect(() => {
    if (adminWorkspace !== "project" || projectSetupShowAll) {
      return;
    }
    if (projectSetupStep !== "review") {
      return;
    }
    if (onboardingDocApprovalState.approved) {
      setProjectSetupStep("status");
    }
  }, [adminWorkspace, projectSetupShowAll, projectSetupStep, onboardingDocApprovalState.approved]);

  useEffect(() => {
    if (!isAuthenticated || (adminWorkspace !== "monitoring" && adminWorkspace !== "project")) {
      return;
    }
    loadMonitoringApplications();
  }, [isAuthenticated, adminWorkspace]);

  useEffect(() => {
    if (!selectedMonitoringAppId) {
      return;
    }
    loadMonitoringApplicationDetails(selectedMonitoringAppId);
  }, [selectedMonitoringAppId]);

  useEffect(() => {
    if (!selectedMonitoringAppId || adminWorkspace !== "monitoring") {
      return;
    }
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(() => {
      monitoringInspectRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [selectedMonitoringAppId, adminWorkspace]);

  useEffect(() => {
    if (activeTab !== "admin" || adminWorkspace !== "alerts") {
      return;
    }
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(() => {
      alertKnowledgeRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [activeTab, adminWorkspace]);

  useEffect(() => {
    if (onboardingProjectMode === "new" || selectedOnboardingProject || !onboardingProjectOptions.length) {
      return;
    }
    const firstProjectName = onboardingProjectRowOptions[0] || onboardingProjectOptions[0];
    const firstProjectRow = (onboardingState.rows || []).find((row) => extractOnboardingProjectName(row) === firstProjectName);
    if (firstProjectRow) {
      applyProjectOnboardingRow(firstProjectRow);
      return;
    }
    setSelectedOnboardingProject(firstProjectName);
    setOnboardingForm((curr) => ({
      ...curr,
      name: firstProjectName,
      assignment_project: firstProjectName,
    }));
  }, [onboardingProjectMode, selectedOnboardingProject, onboardingProjectOptions, onboardingProjectRowOptions, onboardingState.rows]);

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }
    if (allowedTabs.includes(activeTab)) {
      return;
    }
    setActiveTab(allowedTabs[0] || "approval");
  }, [isAuthenticated, allowedTabs, activeTab]);

  function openSection(tabId) {
    if (!allowedTabs.includes(tabId)) {
      return;
    }
    setActiveTab(tabId);
  }

  function openCopilotWorkspace(workspace) {
    if (workspace === "users" && !isAdministrator) {
      return;
    }
    if (workspace === "users") {
      setAdminWorkspace("users");
    } else if (workspace === "monitoring") {
      setAdminWorkspace("project");
    } else if (workspace === "project") {
      setAdminWorkspace("project");
    } else if (workspace === "alerts") {
      setAdminWorkspace("alerts");
      setAlertKnowledgeView("onboarding");
    }
    setActiveTab("admin");
  }

  const reportConfig = useMemo(() => {
    const config = {
      home: {
        title: "Dashboard",
        caption: "Operational dashboard with alert stream and incident overview.",
        metrics: [
          ["Recent Alerts", monitorScopedAlerts.length],
          ["Flows", flows.rows.length],
          ["Gateway Events", gatewayRecent.rows.length],
          ["Health", health.ok ? "OK" : "CHECK"],
        ],
        refresh: refreshAll,
      },
      copilot: {
        title: "Copilot Studio",
        caption: "Guided workspace for project onboarding, alert docs, and user management.",
        metrics: [
          ["Projects", onboardingState.rows.length],
          ["Alert Docs", ragDocs.rows.length],
          ["Users", adminUsers.rows.length],
          ["Ready", health.ok ? "Yes" : "Check"],
        ],
        refresh: refreshAll,
      },
      executive: {
        title: "Executive Dashboard",
        caption: "Leadership KPIs for reliability posture, risk, and closure outcomes.",
        metrics: [
          ["Open Alerts", monitorScopedAlerts.length],
          [
            "Critical Open",
            monitorScopedAlerts.filter((row) => String(row?.severity || "").toLowerCase() === "critical").length,
          ],
          ["Closed Incidents", closedIncidents.rows.length],
          ["Health Restored", closedIncidents.rows.filter((row) => row?.health_restored === true).length],
          ["SLA At Risk", executiveInsights.slaAtRisk],
          ["Avg Approval Wait", `${executiveInsights.avgApprovalWaitMinutes.toFixed(1)} min`],
          ["Auto Remediation Rate", `${executiveInsights.automationRate.toFixed(1)}%`],
          ["LLM Cost (USD)", executiveMetrics.finopsCost.toFixed(6)],
        ],
        refresh: refreshAll,
      },
      admin: {
        title: "Admin Center",
        caption: "Administrative controls, system health, and approval operations.",
        metrics: [
          ["Pending Approvals", pendingApprovals.length],
          ["Gateway", health.ok ? "Healthy" : "Check"],
          ["Metadata Rows", incidentMetadata.rows.length],
          ["Monitoring Target", applicationToMonitor],
        ],
        refresh: async () => {
          await Promise.all([checkHealth(), loadIncidentMetadata(), loadGatewaySummary(), loadGatewayRecent()]);
        },
      },
      summary: {
        title: "Incident Metadata Explorer",
        caption: "Filter the incident projection layer across policy, transport, and operational dimensions.",
        metrics: [
          ["Incidents", incidentMetadata.rows.length],
          ["Human Approval", pendingApprovals.length],
          ["Closed", closedIncidents.rows.length],
          ["Monitoring", applicationToMonitor],
        ],
        refresh: loadIncidentMetadata,
      },
      approval: {
        title: "Human Approval & Alerts",
        caption: "Pending approvals, live incident feed, and quick guidance workspace.",
        metrics: [
          ["Recent Alerts", monitorScopedAlerts.length],
          ["Pending", pendingApprovals.length],
          ["Guidance Matches", guidanceState.rows.length],
          ["Last Incident", latestIncidentId || "-"],
        ],
        refresh: async () => {
          await Promise.all([loadIncidentMetadata(), loadGatewayRecent(), loadGatewaySummary()]);
        },
      },
      trace: {
        title: "Agent Flow",
        caption: "Agent execution timeline, decisions, outputs, and handoffs.",
        metrics: [
          ["Workflow Events", workflowEventRows.length],
          ["Gateway Events", gatewayRecent.rows.length],
          ["Latest Incident", latestIncidentId || "-"],
          ["Latest Flow", selectedFlow || "-"],
        ],
        refresh: async () => {
          await Promise.all([loadGatewayRecent(), loadGatewaySummary()]);
        },
      },
      finops: {
        title: "LLM FinOps",
        caption: "Token usage, provider costs, and model-level breakdown.",
        metrics: [
          ["LLM Calls", allUsageRows.length],
          [
            "Total Cost (USD)",
            allUsageRows
              .reduce((sum, row) => sum + Number(row?.total_cost_usd || 0), 0)
              .toFixed(6),
          ],
          ["Providers", new Set(allUsageRows.map((row) => row.provider).filter(Boolean)).size],
          ["Models", new Set(allUsageRows.map((row) => row.model).filter(Boolean)).size],
        ],
        refresh: async () => {
          await Promise.all([loadIncidentMetadata(), loadGatewaySummary(), loadGatewayRecent(), loadClosedIncidents(), loadRecentAlerts()]);
        },
      },
      rag: {
        title: "Message Bus",
        caption: "Configured routing plus latest observed published versus consumed topics.",
        metrics: [
          ["Published Topics", messageBusActual.published.length],
          ["Consumed Topics", messageBusActual.consumed.length],
          ["Observed Provider", observedRouting?.message_bus_provider || "N/A"],
          ["Workflow", observedRouting?.workflow || "N/A"],
        ],
        refresh: () => runWorkflow(selectedFlow),
      },
      safety: {
        title: "Gateway Safety",
        caption: "Review gateway decision, policy reasons, and safety metrics before closure.",
        metrics: [
          ["Events", gatewaySummary.data.total_events || 0],
          ["Allowed", gatewaySummary.data.allowed || 0],
          ["Review", gatewaySummary.data.review || 0],
          ["Blocked", gatewaySummary.data.blocked || 0],
        ],
        refresh: async () => {
          await Promise.all([loadGatewaySummary(), loadGatewayRecent()]);
        },
      },
      closed: {
        title: "Closed Tickets",
        caption: "Closed tickets plus current closure report details.",
        metrics: [
          ["Closed", closedIncidents.rows.length],
          [
            "Health Restored",
            closedIncidents.rows.filter((row) => row?.health_restored === true).length,
          ],
          ["Monitoring", applicationToMonitor],
          ["Gateway", health.ok ? "OK" : "CHECK"],
        ],
        refresh: loadClosedIncidents,
      },
    };

    return config[activeTab] || config.home;
  }, [
    activeTab,
    monitorScopedAlerts.length,
    flows.rows.length,
    gatewayRecent.rows,
    health.ok,
    monitorScopedIncidentMetadata.length,
    pendingApprovals.length,
    guidanceState.rows.length,
    closedIncidents.rows,
    applicationToMonitor,
    latestIncidentId,
    latestRecommendationId,
    approvalForm.action,
    workflowEventRows.length,
    selectedFlow,
    allUsageRows,
    messageBusActual,
    observedRouting,
    gatewaySummary.data,
    executiveMetrics.finopsCost,
    executiveInsights.slaAtRisk,
    executiveInsights.avgApprovalWaitMinutes,
    executiveInsights.automationRate,
  ]);

  const workflowGuide = useMemo(() => {
    const unresolvedAlerts = monitorScopedAlerts.filter((row) => !isApprovalResolvedStatus(row?.status || row?.state));
    const agentNames = new Set(
      (selectedAlertEventsDisplay || []).map((row) => String(row?.agent || "").trim().toLowerCase()).filter(Boolean),
    );
    const resolutionSeen = Array.from(agentNames).some((name) => name.includes("resolution intelligence") || name.includes("resolution-agent"));
    const remediationSeen = Array.from(agentNames).some((name) => name.includes("remediation automation") || name.includes("remediation-engine"));

    const cards = [
      {
        id: "alerts",
        label: "Alert Intake",
        status: unresolvedAlerts.length ? "active" : "idle",
        detail: unresolvedAlerts.length
          ? `${unresolvedAlerts.length} open alerts ready for triage.`
          : "No open alerts in the current monitoring scope.",
      },
      {
        id: "approval",
        label: "Approval Queue",
        status: pendingApprovals.length ? "attention" : "clear",
        detail: pendingApprovals.length
          ? `${pendingApprovals.length} incidents are waiting for a user decision.`
          : "No incidents are waiting for human approval.",
      },
      {
        id: "resolution",
        label: "Resolution Intelligence",
        status: resolutionSeen ? "active" : "attention",
        detail: resolutionSeen
          ? "Root-cause and recommendation evidence found for selected alert."
          : "No resolution trace detected for selected alert yet.",
      },
      {
        id: "remediation",
        label: "Remediation Automation",
        status: remediationSeen ? "active" : "attention",
        detail: remediationSeen
          ? "Remediation execution trace detected in agent timeline."
          : "No remediation execution trace detected yet.",
      },
    ];

    let nextAction = "Open an alert row to inspect timeline, then route to approval if required.";
    if (!unresolvedAlerts.length) {
      nextAction = "Generate or ingest a fresh alert to validate the end-to-end agent workflow.";
    } else if (pendingApprovals.length) {
      nextAction = "Use Human Approval to approve or reject pending recommendations and unblock remediation.";
    } else if (!resolutionSeen) {
      nextAction = "Inspect Cockpit and review Evidence or Timeline for Resolution Intelligence output.";
    } else if (!remediationSeen) {
      nextAction = "Approve the recommendation or verify auto-execution policy to trigger remediation.";
    }

    return { cards, nextAction };
  }, [monitorScopedAlerts, pendingApprovals.length, selectedAlertEventsDisplay]);

  function downloadFullHtmlReportPack() {
    const now = new Date();
    const generatedAt = now.toISOString();
    const homeMetrics = [
      ["Recent Alerts", monitorScopedAlerts.length],
      ["Flows", flows.rows.length],
      ["Gateway Events", gatewayRecent.rows.length],
      ["Health", health.ok ? "OK" : "CHECK"],
    ];
    const executiveMetrics = [
      ["Open Alerts", monitorScopedAlerts.length],
      ["Critical Open", monitorScopedAlerts.filter((row) => String(row?.severity || "").toLowerCase() === "critical").length],
      ["Closed Incidents", closedIncidents.rows.length],
      ["Health Restored", closedIncidents.rows.filter((row) => row?.health_restored === true).length],
      ["SLA At Risk", executiveInsights.slaAtRisk],
      ["Avg Approval Wait (min)", executiveInsights.avgApprovalWaitMinutes.toFixed(1)],
      ["Auto Remediation Rate", `${executiveInsights.automationRate.toFixed(1)}%`],
    ];
    const safetyMetrics = [
      ["Total", gatewaySummary.data.total_events || 0],
      ["Allowed", gatewaySummary.data.allowed || 0],
      ["Review", gatewaySummary.data.review || 0],
      ["Blocked", gatewaySummary.data.blocked || 0],
    ];

    const monitorAlertsRows = monitorScopedAlerts.slice(0, 200).map((row, index) => [
      row.alert_id || row.id || row.incident_id || index,
      formatUtcTimestamp(row.created_at || row.starts_at),
      row.name || row.alert_name || "-",
      row.application || row.project_name || row.project || row.service || "-",
      row.service || "-",
      String(row.severity || "-").toUpperCase(),
      row.status || row.state || "open",
    ]);
    const metadataRows = monitorScopedIncidentMetadata.slice(0, 250).map((row, index) => [
      row.incident_id || row.id || index,
      row.service || "-",
      row.risk_tier || "-",
      row.execution_mode || "-",
      row.transport_provider || "-",
      row.status || "-",
    ]);
    const pendingApprovalRows = pendingApprovals.slice(0, 200).map((row, index) => [
      row.incident_id || index,
      row.service || "-",
      row.severity || row.risk_tier || "-",
      row.execution_mode || "-",
      row.status || "pending",
    ]);
    const guidanceRows = guidanceState.rows.slice(0, 200).map((row, index) => [
      row.kind || row.document_kind || "-",
      row.score ?? "-",
      row.title || row.id || `match-${index}`,
      row.path || "-",
    ]);
    const traceRows = workflowEventRows.slice(0, 250).map((row) => [
      row.sequence,
      row.agent,
      row.action,
      row.decision,
      row.output,
      row.communicates_to,
    ]);
    const finopsProviderRows = finopsByProvider.map((row) => [
      row.provider,
      row.calls,
      row.total_tokens,
      Number(row.total_cost_usd || 0).toFixed(6),
    ]);
    const finopsUsageRows = panelWorkflowUsage.slice(0, 250).map((row) => [
      row.task || "-",
      row.provider || "-",
      row.model || "-",
      row.input_tokens || "-",
      row.output_tokens || "-",
      row.total_cost_usd || "-",
    ]);
    const gatewayRows = gatewayRecent.rows.slice(0, 250).map((row, index) => [
      row.created_at || row.timestamp || index,
      row.path || "-",
      row.status_code || "-",
      row?.safety?.decision || "-",
      row.trace_id || "-",
    ]);
    const busActualRows = messageBusActual.rows.map((row) => [
      row.service,
      row.consumed,
      row.published,
      row.provider,
      row.status,
    ]);
    const busConfigRows = messageBusTopicRows.map((row) => [row.service, row.consumes, row.publishes]);
    const closedRows = filteredClosedRows.slice(0, 300).map((row, index) => [
      row.incident_id || index,
      row.service || "-",
      row.severity || "-",
      row.status || "closed",
      row.closed_at || row.updated_at || "-",
    ]);

    const selectedSummaryRows = selectedAlertRow
      ? [
          ["Alert ID", selectedAlertId],
          ["Name", selectedAlertRow?.name || selectedAlertWorkflow?.alert?.name || "-"],
          ["Service", selectedAlertRow?.service || selectedAlertWorkflow?.alert?.service || "-"],
          ["Incident", selectedAlertWorkflow?.incident?.id || selectedAlertWorkflow?.incident_id || "-"],
          ["Root Cause", selectedAlertWorkflow?.recommendation?.root_cause || "-"],
          ["Recommended Action", selectedAlertWorkflow?.recommendation?.recommended_action || "-"],
          ["Impact", selectedAlertWorkflow?.recommendation?.impact || "-"],
        ]
      : [];
    const selectedEventsRows = selectedAlertEvents.slice(0, 250).map((event) => [
      event.sequence || "-",
      event.agent || "-",
      event.action || "-",
      typeof event.decision === "object" ? JSON.stringify(event.decision) : String(event.decision || "-"),
      typeof event.output === "object" ? JSON.stringify(event.output) : String(event.output || "-"),
      event.communicates_to || "-",
    ]);
    const selectedUsageRows = selectedAlertUsage.slice(0, 250).map((row) => [
      row.task || "-",
      row.provider || "-",
      row.model || "-",
      row.input_tokens || "-",
      row.output_tokens || "-",
      row.total_cost_usd || "-",
    ]);
    const selectedRoutingRows = selectedAlertRow
      ? [
          ["Observed Provider", (hasSelectedWorkflowData ? selectedAlertRouting?.message_bus_provider : observedRouting?.message_bus_provider) || "-"],
          ["Workflow", (hasSelectedWorkflowData ? selectedAlertRouting?.workflow : observedRouting?.workflow) || "-"],
          ["Next Action", (hasSelectedWorkflowData ? selectedAlertRouting?.next_action : observedRouting?.next_action) || "-"],
          ["Execution Mode", (hasSelectedWorkflowData ? selectedAlertRouting?.execution_mode : observedRouting?.execution_mode) || "-"],
          ["Risk Tier", (hasSelectedWorkflowData ? selectedAlertRouting?.risk_tier : observedRouting?.risk_tier) || "-"],
        ]
      : [];

    const sections = [
      `<section><h2>Report Context</h2>${renderHtmlTable(["Field", "Value"], [["Generated At", generatedAt], ["Application Scope", applicationToMonitor], ["Active Tab", activeTab], ["Health", health.message]])}</section>`,
      `<section><h2>Dashboard Metrics</h2>${renderHtmlTable(["Metric", "Value"], homeMetrics)}</section>`,
      `<section><h2>Alert Stream</h2>${renderHtmlTable(["Alert ID", "Time (UTC)", "Name", "Application", "Service", "Severity", "Status"], monitorAlertsRows)}</section>`,
      `<section><h2>Alert Details Cockpit</h2>${renderHtmlTable(["Field", "Value"], selectedSummaryRows)}${renderHtmlTable(["Step", "Agent", "Action", "Decision", "Output", "Communicates To"], selectedEventsRows)}${renderHtmlTable(["Task", "Provider", "Model", "Input", "Output", "Cost USD"], selectedUsageRows)}${renderHtmlTable(["Field", "Value"], selectedRoutingRows)}<h3>Raw Payload</h3><pre>${htmlEscape(JSON.stringify(selectedAlertData.payload || {}, null, 2))}</pre></section>`,
      `<section><h2>Executive Dashboard</h2>${renderHtmlTable(["Metric", "Value"], executiveMetrics)}${renderHtmlTable(["Incident", "Service", "Risk", "Execution Mode", "Provider", "Status"], metadataRows)}</section>`,
      `<section><h2>Incident Metadata Explorer</h2>${renderHtmlTable(["Incident", "Service", "Risk", "Execution Mode", "Provider", "Status"], metadataRows)}</section>`,
      `<section><h2>Alerts and Quick Docs</h2>${renderHtmlTable(["Incident", "Service", "Severity", "Execution Mode", "Status"], pendingApprovalRows)}${renderHtmlTable(["Kind", "Score", "Title", "Path"], guidanceRows)}</section>`,
      `<section><h2>Agent Flow</h2>${renderHtmlTable(["Step", "Agent", "Action", "Decision", "Output", "Handoff"], traceRows)}${renderHtmlTable(["Time", "Path", "Status", "Decision", "Trace"], gatewayRows)}</section>`,
      `<section><h2>FinOps</h2>${renderHtmlTable(["Provider", "Calls", "Tokens", "Cost USD"], finopsProviderRows)}${renderHtmlTable(["Task", "Provider", "Model", "Input Tokens", "Output Tokens", "Total Cost USD"], finopsUsageRows)}</section>`,
      `<section><h2>Message Bus</h2>${renderHtmlTable(["Service", "Consumed", "Published", "Provider", "Status"], busActualRows)}${renderHtmlTable(["Service", "Consumes", "Publishes"], busConfigRows)}<h3>Observed Topics</h3><p>Published: ${htmlEscape(messageBusActual.published.join(", ") || "none")}</p><p>Consumed: ${htmlEscape(messageBusActual.consumed.join(", ") || "none")}</p></section>`,
      `<section><h2>Gateway Safety</h2>${renderHtmlTable(["Metric", "Value"], safetyMetrics)}${renderHtmlTable(["Time", "Path", "Status", "Decision", "Trace"], gatewayRows)}</section>`,
      `<section><h2>Closed Incidents</h2>${renderHtmlTable(["Incident", "Service", "Severity", "Status", "Closed At"], closedRows)}</section>`,
      `<section><h2>Admin Snapshot</h2>${renderHtmlTable(["Field", "Value"], [["Signed In User", adminSession?.user?.username || "-"], ["Users Loaded", adminUsers.rows.length], ["Onboarding Rows", onboardingState.rows.length]])}</section>`,
      `<section><h2>Workflow Raw Result</h2><pre>${htmlEscape(JSON.stringify(workflowState.result || {}, null, 2))}</pre></section>`,
    ];

    const documentHtml = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>KaiOps Report Pack - ${htmlEscape(applicationToMonitor)}</title>
  <style>
    :root { color-scheme: light; }
    body { margin: 0; padding: 24px; font-family: "Segoe UI", Tahoma, sans-serif; background: #f5f8fb; color: #10233b; }
    h1, h2, h3 { margin: 0 0 10px; }
    h1 { font-size: 26px; }
    h2 { font-size: 19px; margin-top: 18px; }
    h3 { font-size: 15px; margin-top: 12px; }
    .meta { margin: 8px 0 18px; color: #42566e; }
    section { background: #fff; border: 1px solid #dbe7f3; border-radius: 14px; padding: 14px; margin-bottom: 12px; box-shadow: 0 8px 20px rgba(16, 35, 59, 0.06); }
    table { width: 100%; border-collapse: collapse; margin: 8px 0 14px; }
    th, td { border: 1px solid #dbe7f3; text-align: left; padding: 7px 8px; font-size: 12px; vertical-align: top; }
    th { background: #eef4fb; }
    pre { margin: 8px 0 0; padding: 10px; background: #0f172a; color: #e2e8f0; border-radius: 10px; overflow: auto; font-size: 11px; }
  </style>
</head>
<body>
  <h1>KaiOps Full HTML Report Pack</h1>
  <p class="meta">Application: ${htmlEscape(applicationToMonitor)} | Generated: ${htmlEscape(generatedAt)}</p>
  ${sections.join("\n")}
</body>
</html>`;

    const blob = new Blob([documentHtml], { type: "text/html;charset=utf-8" });
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `kaiops-report-pack-${String(applicationToMonitor || "all").replace(/[^a-zA-Z0-9_-]+/g, "-")}-${generatedAt.replace(/[:.]/g, "-")}.html`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  }

  if (!isAuthenticated) {
    return (
      <main className={`app-shell density-${uiDensity}`}>
        <section className="grid single-col">
          <article className="panel" style={{ maxWidth: 560, margin: "48px auto" }}>
            <div className="panel-head">
              <div>
                <h2>Login</h2>
                <p>Sign in to access role-based KaiOps workspaces.</p>
              </div>
            </div>
            <form className="form" onSubmit={adminLogin}>
              <label>Username<input value={adminAuthForm.username} onChange={(e) => setAdminAuthForm((curr) => ({ ...curr, username: e.target.value }))} /></label>
              <label>Password<input type="password" value={adminAuthForm.password} onChange={(e) => setAdminAuthForm((curr) => ({ ...curr, password: e.target.value }))} /></label>
              <button className="button-primary" type="submit" disabled={adminSession.loading}>{adminSession.loading ? "Signing in..." : "Sign In"}</button>
            </form>
            {adminSession.error ? <p className="error">{adminSession.error}</p> : null}
            <p className="subtitle">Role access: Admin = all screens and document provisioning, L3/L2 = investigations plus Provide Documents, L1 = monitoring dashboard and escalation.</p>
          </article>
        </section>
      </main>
    );
  }

  return (
    <main className={`app-shell density-${uiDensity}`}>
      <div className="app-layout">
        <aside className="sidebar panel sidebar-panel">
          <div className="sidebar-head">
            <h2>Control Panel</h2>
            <p className="subtitle">Essential navigation.</p>
          </div>

          <div className="sidebar-group">
            <h3>Monitor</h3>
            <label>
              Application
              <select value={applicationToMonitor} onChange={(e) => setApplicationToMonitor(e.target.value)}>
                {monitorApplications.map((app) => (
                  <option key={app} value={app}>{app}</option>
                ))}
              </select>
            </label>
            <HealthBadge ok={health.ok} label={health.message} />
          </div>

          <div className="sidebar-group">
            <h3>View Density</h3>
            <div className="density-switch" role="group" aria-label="Density options">
              <button
                type="button"
                className={`density-option ${uiDensity === "comfortable" ? "active" : ""}`}
                onClick={() => setUiDensity("comfortable")}
              >
                Comfortable
              </button>
              <button
                type="button"
                className={`density-option ${uiDensity === "compact" ? "active" : ""}`}
                onClick={() => setUiDensity("compact")}
              >
                Compact
              </button>
            </div>
            <h3 style={{ marginTop: 10 }}>Theme</h3>
            <div className="theme-switch" role="group" aria-label="Theme options">
              <button
                type="button"
                className={`density-option ${uiTheme === "auto" ? "active" : ""}`}
                onClick={() => setUiTheme("auto")}
              >
                Auto
              </button>
              <button
                type="button"
                className={`density-option ${uiTheme === "light" ? "active" : ""}`}
                onClick={() => setUiTheme("light")}
              >
                Light
              </button>
              <button
                type="button"
                className={`density-option ${uiTheme === "dark" ? "active" : ""}`}
                onClick={() => setUiTheme("dark")}
              >
                Dark
              </button>
            </div>
          </div>

          <div className="sidebar-group">
            <h3>Sections</h3>
            <div className="sidebar-sections-wrap">
              <div className="sidebar-sections">
                {visibleSidebarSections.map((tab) => (
                  <button
                    key={`sidebar-${tab.id}`}
                    type="button"
                    className={`sidebar-section ${activeTab === tab.id ? "active" : ""}`}
                    onClick={() => openSection(tab.id)}
                    title={tab.label}
                  >
                    <span className={`sidebar-icon sidebar-icon-${tab.tone || "ops"}`} aria-hidden="true">{tab.icon}</span>
                    <span>{tab.shortLabel}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="sidebar-group compact-tools">
            <button className="button-secondary" onClick={refreshAll}>Refresh</button>
            <button className="button-secondary" onClick={checkHealth} disabled={health.loading}>
              {health.loading ? "Checking..." : "Health"}
            </button>
          </div>
        </aside>

        <section className="content-area">
          <header className="hero">
            <p className="eyebrow">KaiMS</p>
            <h1>Operational Workspace</h1>
            <p className="subtitle">Business-level view of reliability, risk, and cost.</p>
            <div className="hero-actions">
              <HealthBadge ok={health.ok} label={health.message} />
              <span className="subtitle">Monitoring: {applicationToMonitor}</span>
              <span className="subtitle">Signed in: {adminSession?.user?.username || "-"} ({adminSession?.user?.role_name || "-"})</span>
              <button className="button-secondary" type="button" onClick={adminLogout}>Logout</button>
            </div>
          </header>

          <section className="report-banner panel">
            <div className="panel-head">
              <div>
                <h2>{reportConfig.title}</h2>
                <p>{reportConfig.caption}</p>
                <p className="scope-note">Scope: {applicationToMonitor}</p>
              </div>
            </div>
            <div className="report-tools">
              <button className="button-secondary" type="button" onClick={reportConfig.refresh}>
                Refresh Report
              </button>
              {activeTab === "home" ? (
                <button className="button-secondary" type="button" onClick={downloadFullHtmlReportPack}>
                  Export Incident Report
                </button>
              ) : null}
            </div>
            <div className="report-metrics">
              {reportConfig.metrics.map(([label, value]) => (
                <div className="report-metric" key={`metric-${label}`}>
                  <strong>{label}</strong>
                  <span>{String(value)}</span>
                </div>
              ))}
            </div>
            {!health.ok ? (
              <div className="health-advisory">
                <strong>Health needs attention</strong>
                <span>{health.message || "Gateway status is not available."}</span>
                <button className="button-secondary" type="button" onClick={checkHealth} disabled={health.loading}>
                  {health.loading ? "Checking..." : "Recheck"}
                </button>
              </div>
            ) : null}
          </section>

          {activeTab === "home" ? (
            <section className="grid single-col">
              <article className="panel workflow-guide-panel">
                <div className="panel-head">
                  <h2>Workflow Health & Next Action</h2>
                </div>
                <p className="subtitle">Fast status across intake, resolution, approval, and remediation.</p>
                <div className="workflow-guide-grid">
                  {workflowGuide.cards.map((card) => (
                    <div className="workflow-guide-card" key={card.id}>
                      <strong>{card.label}</strong>
                      <span className={`workflow-pill workflow-pill-${card.status}`}>{card.status.toUpperCase()}</span>
                      <p>{card.detail}</p>
                    </div>
                  ))}
                </div>
                <p className="scope-note">Recommended next step: {workflowGuide.nextAction}</p>
              </article>

              <article className="panel">
                <div className="panel-head">
                  <h2>Alert Stream</h2>
                  <label className="alerts-limit-select">
                    Show
                    <select
                      value={alertsLimit}
                      disabled={alerts.loading}
                      onChange={(event) => setAlertsLimit(Number(event.target.value))}
                    >
                      <option value={25}>25</option>
                      <option value={50}>50</option>
                      <option value={100}>100</option>
                      <option value={200}>200</option>
                      <option value={500}>500</option>
                    </select>
                    alerts
                  </label>
                  <button className="button-secondary" onClick={loadRecentAlerts} disabled={alerts.loading}>
                    {alerts.loading ? "Loading..." : "Refresh"}
                  </button>
                </div>
                {alerts.error ? <p className="error">{alerts.error}</p> : null}
                {alertSeverityOverrides.error ? <p className="error">{alertSeverityOverrides.error}</p> : null}
                <div className="dashboard-alert-toolbar">
                  <div className="dashboard-alert-focus" role="tablist" aria-label="Alert triage focus">
                    <button type="button" className={`dashboard-focus-chip ${dashboardAlertFocus === "ops" ? "active" : ""}`} onClick={() => setDashboardAlertFocus("ops")}>Ops {dashboardAlertSummary.ops}</button>
                    <button type="button" className={`dashboard-focus-chip ${dashboardAlertFocus === "all" ? "active" : ""}`} onClick={() => setDashboardAlertFocus("all")}>All {dashboardAlertSummary.total}</button>
                    <button type="button" className={`dashboard-focus-chip ${dashboardAlertFocus === "critical" ? "active" : ""}`} onClick={() => setDashboardAlertFocus("critical")}>Critical {dashboardAlertSummary.critical}</button>
                    <button type="button" className={`dashboard-focus-chip ${dashboardAlertFocus === "high" ? "active" : ""}`} onClick={() => setDashboardAlertFocus("high")}>High {dashboardAlertSummary.high}</button>
                    <button type="button" className={`dashboard-focus-chip ${dashboardAlertFocus === "awaiting" ? "active" : ""}`} onClick={() => setDashboardAlertFocus("awaiting")}>Awaiting {dashboardAlertSummary.awaiting}</button>
                    <button type="button" className={`dashboard-focus-chip ${dashboardAlertFocus === "active" ? "active" : ""}`} onClick={() => setDashboardAlertFocus("active")}>Active {dashboardAlertSummary.active}</button>
                    <button type="button" className={`dashboard-focus-chip ${dashboardAlertFocus === "test" ? "active" : ""}`} onClick={() => setDashboardAlertFocus("test")}>Test {dashboardAlertSummary.test}</button>
                  </div>
                  <div className="dashboard-alert-search">
                    <input
                      value={dashboardAlertQuery}
                      onChange={(event) => setDashboardAlertQuery(event.target.value)}
                      placeholder="Search alert name, service, app, id"
                    />
                    {dashboardAlertQuery ? (
                      <button type="button" className="button-secondary" onClick={() => setDashboardAlertQuery("")}>Clear</button>
                    ) : null}
                  </div>
                </div>
                <p className="subtitle">
                  Showing {dashboardVisibleAlerts.length} of {visibleAlerts.length} alerts for {applicationToMonitor}.
                  {dashboardAlertFocus === "ops" && dashboardAlertSummary.test > 0 ? ` ${dashboardAlertSummary.test} smoke/stress alerts are hidden in Ops view.` : ""}
                </p>
                {canManageSeverityOverride ? (
                  <p className="subtitle">L2/L3/Admin can set future severity overrides by alert name + service + environment.</p>
                ) : null}
                <div className="table-wrap table-wrap-scroll-x alert-stream-wrap">
                  <table className="alert-stream-table">
                    <thead>
                      <tr>
                        <th>Alert ID</th>
                        <th>Time (UTC)</th>
                        <th className="alert-name-col">Name</th>
                        <th>Rule</th>
                        <th>Application</th>
                        <th>Service</th>
                        <th>Severity</th>
                        <th>Status</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboardVisibleAlerts.map((row, index) => {
                        const rowId = String(row.alert_id || row.id || row.incident_id || index);
                        const fullAlertId = String(row.alert_id || row.id || row.incident_id || "-");
                        const compactAlertId = fullAlertId.length > 16 ? `${fullAlertId.slice(0, 8)}...${fullAlertId.slice(-6)}` : fullAlertId;
                        const severity = String(row.severity || "-").toUpperCase();
                        const status = String(row.status || row.state || "open");
                        const application = row.application || row.project_name || row.project || row.service || "-";
                        const alertRuleName = String(
                          row.rule_name
                          || row.rule
                          || row.alert_rule
                          || row.labels?.alertname
                          || row.name
                          || row.alert_name
                          || "-"
                        ).trim();
                        return (
                          <tr
                            key={rowId}
                            className={`alert-row ${selectedAlertId === rowId ? "row-selected" : ""}`}
                            onClick={() => openAlertDetails(row)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                openAlertDetails(row);
                              }
                            }}
                            tabIndex={0}
                            role="button"
                            aria-label={`Open alert ${rowId}`}
                          >
                            <td title={fullAlertId}>{compactAlertId}</td>
                            <td>{formatUtcTimestamp(row.created_at || row.starts_at)}</td>
                            <td className="alert-name-col">{row.name || row.alert_name || "-"}</td>
                            <td title={String(row.expression || row.expr || row.query || row.description || row.annotations?.description || "").trim()}>{alertRuleName}</td>
                            <td>{application}</td>
                            <td>{row.service || "-"}</td>
                            <td><span className={`pill severity-${severity.toLowerCase()}`}>{severity}</span></td>
                            <td><span className={`pill status-${status.toLowerCase()}`}>{status}</span></td>
                            <td>
                              <button
                                type="button"
                                className="button-secondary"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  openAlertDetails(row);
                                }}
                              >
                                Inspect
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                      {!dashboardVisibleAlerts.length && !alerts.loading ? (
                        <tr>
                          <td colSpan={9}>No alerts match current filters for {applicationToMonitor}.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </article>

              {selectedAlertRow ? (
                <article className="panel">
                  <div className="panel-head">
                    <h3>Guided Incident Cockpit</h3>
                    <p>Selected alert actions, evidence, documents, approval, and remediation stay in one workspace.</p>
                  </div>
                  <div className="filter-grid">
                    <label>Alert
                      <input value={String(selectedAlertRow?.name || selectedAlertRow?.alert_name || "-")} readOnly />
                    </label>
                    <label>Service
                      <input value={String(selectedAlertRow?.service || "-")} readOnly />
                    </label>
                    <label>Status
                      <input value={String(selectedAlertRow?.status || selectedAlertRow?.state || "open")} readOnly />
                    </label>
                    <label>Current Severity
                      <input value={String(selectedAlertRow?.severity || "-").toUpperCase()} readOnly />
                    </label>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                    <button type="button" className="button-primary" onClick={() => openAlertDetails(selectedAlertRow)}>Inspect Cockpit</button>
                    <span className="cockpit-action-note">
                      Evidence, documents, approval, remediation, and timeline are inside the cockpit.
                    </span>
                  </div>
                  <div className="alert-rule-summary-grid">
                    <article className="alert-rule-summary-card">
                      <span>Raised By Rule</span>
                      <strong>{selectedAlertRuleSummary.ruleName}</strong>
                      <small>{selectedAlertRuleSummary.expression}</small>
                    </article>
                    <article className="alert-rule-summary-card">
                      <span>Rule Source</span>
                      <strong>{selectedAlertRuleSummary.source}</strong>
                      <small>{selectedAlertRuleSummary.note}</small>
                    </article>
                    <article className="alert-rule-summary-card">
                      <span>Rule Severity</span>
                      <strong>{selectedAlertRuleSummary.severity.toUpperCase()}</strong>
                      <small>This rule context stays visible beside the live remediation actions.</small>
                    </article>
                  </div>
                  {selectedAlertActionContext ? (
                    <>
                      <p className="subtitle">
                        Docs: {selectedAlertActionContext.alertClosed ? "Closed" : selectedAlertActionContext.documentAvailable ? "Ready" : "Missing"}
                        {selectedAlertActionContext.overrideRow ? ` | Future Severity: ${String(selectedAlertActionContext.overrideRow.severity || "-").toUpperCase()}` : ""}
                      </p>
                      {canManageSeverityOverride ? (
                        <div className="filter-grid">
                          <label>Future Severity Override
                            <select
                              value={selectedAlertActionContext.draftSeverity}
                              onChange={(event) => {
                                const next = String(event.target.value || "warning").toLowerCase();
                                setAlertSeverityDrafts((current) => ({ ...current, [selectedAlertActionContext.overrideKey]: next }));
                              }}
                            >
                              <option value="info">info</option>
                              <option value="warning">warning</option>
                              <option value="high">high</option>
                              <option value="critical">critical</option>
                            </select>
                          </label>
                          <div style={{ display: "flex", alignItems: "end", gap: 8 }}>
                            <button
                              type="button"
                              className="button-secondary"
                              onClick={() => applyAlertSeverityOverrideRule(selectedAlertRow)}
                              disabled={selectedAlertActionContext.overrideSaving || alertSeverityOverrides.loading || !selectedAlertActionContext.alertName}
                            >
                              {selectedAlertActionContext.overrideSaving ? "Saving..." : "Apply Override"}
                            </button>
                            <button
                              type="button"
                              className="button-secondary"
                              onClick={() => clearAlertSeverityOverrideRule(selectedAlertRow)}
                              disabled={selectedAlertActionContext.overrideSaving || !selectedAlertActionContext.overrideRow}
                            >
                              Clear Override
                            </button>
                          </div>
                        </div>
                      ) : null}
                    </>
                  ) : null}
                </article>
              ) : null}

              {docPromptAlert && canProvideAlertDocuments ? (
                <article className="panel" role="dialog" aria-label="Provide documents for alert" ref={docPromptRef}>
                  <div className="panel-head">
                    <h3>Provide Documents</h3>
                    <button type="button" className="button-secondary" onClick={closeDocumentPrompt}>Close</button>
                  </div>
                  <p className="subtitle">
                    Configure documentation for alert{" "}
                    <strong>{String(docPromptAlert.name || docPromptAlert.alert_name || docPromptAlert.alert_id || docPromptAlert.id || "-")}</strong>.
                    All document types are available as tabs below.
                  </p>
                  <div className="detail-tabs sticky-controls" style={{ marginBottom: 10 }}>
                    {ALERT_DOC_KIND_OPTIONS.map((kind) => {
                      const existing = docPromptDocsByKind[kind];
                      const selected = docPromptKind === kind;
                      const label = existing?.path ? `${kind} *` : kind;
                      return (
                        <button
                          key={`doc-kind-${kind}`}
                          type="button"
                          className={selected ? "button-primary" : "button-secondary"}
                          onClick={() => setDocPromptDraftForKind(docPromptAlert, kind)}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                  <div className="filter-grid">
                    <label>
                      Mode
                      <select value={docPromptMode} onChange={(e) => setDocPromptMode(e.target.value)}>
                        <option value="create">Create New</option>
                        <option value="update" disabled={!docPromptExistingDoc?.path}>Update Existing</option>
                      </select>
                    </label>
                    <div style={{ display: "flex", alignItems: "end", gap: 8 }}>
                      <button
                        type="button"
                        className="button-secondary"
                        onClick={async () => {
                          const draft = await buildAlertDocumentDraftWithAnalysis(docPromptAlert, docPromptKind);
                          setAlertOnboarding((curr) => ({
                            ...curr,
                            kind: draft.kind,
                            title: draft.title,
                            summary: draft.summary,
                            content: draft.content,
                            services: draft.services,
                            severity: draft.severity,
                            alert_type: draft.alert_type,
                            alert_id: draft.alert_id,
                            execution_plan: String(draft.execution_plan || "").trim(),
                            remediation_commands_text: Array.isArray(draft.commands) ? draft.commands.join("\n") : "",
                            remediation_scripts_text: Array.isArray(draft.scripts) ? draft.scripts.join("\n") : "",
                            remediation_queries_text: Array.isArray(draft.queries) ? draft.queries.join("\n") : "",
                          }));
                        }}
                        disabled={alertOnboardingState.loading}
                      >
                        Re-Analyze Alert
                      </button>
                      <button
                        type="button"
                        className="button-secondary"
                        onClick={() => autoCreateAlertDocument(docPromptAlert, docPromptKind)}
                        disabled={alertOnboardingState.loading}
                      >
                        Create Selected Doc
                      </button>
                      <button
                        type="button"
                        className="button-secondary"
                        onClick={() => autoCreateAllAlertDocuments(docPromptAlert)}
                        disabled={alertOnboardingState.loading}
                      >
                        Create All Docs
                      </button>
                    </div>
                  </div>
                  {docPromptExistingDoc?.path ? <p className="subtitle">Existing document: {docPromptExistingDoc.path}</p> : null}
                  <form className="form" onSubmit={submitAlertOnboarding}>
                    <div className="filter-grid">
                      <label>Kind
                        <select value={alertOnboarding.kind} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, kind: e.target.value }))}>
                          <option value="incident">incident</option>
                          <option value="runbook">runbook</option>
                          <option value="deployment">deployment</option>
                          <option value="change">change</option>
                          <option value="dependency">dependency</option>
                          <option value="remediation">remediation</option>
                        </select>
                      </label>
                      <label>Title<input value={alertOnboarding.title} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, title: e.target.value }))} /></label>
                      <label>Severity<select value={alertOnboarding.severity} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, severity: e.target.value }))}><option value="critical">critical</option><option value="high">high</option><option value="medium">medium</option><option value="low">low</option></select></label>
                    </div>
                    <label>Services (comma separated)<input value={alertOnboarding.services} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, services: e.target.value }))} /></label>
                    <label>Summary<textarea rows={2} value={alertOnboarding.summary} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, summary: e.target.value }))} /></label>
                    <label>Content<textarea rows={5} value={alertOnboarding.content} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, content: e.target.value }))} /></label>
                    {String(alertOnboarding.kind || "").trim().toLowerCase() === "remediation" ? (
                      <>
                        <div style={{ display: "flex", alignItems: "end", gap: 8 }}>
                          <button
                            type="button"
                            className="button-secondary"
                            onClick={() => autoGenerateRemediationPlan(docPromptAlert)}
                            disabled={alertOnboardingState.loading}
                          >
                            Auto-Generate Commands/Scripts/Queries
                          </button>
                        </div>
                        <label>Execution Plan<textarea rows={4} value={alertOnboarding.execution_plan} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, execution_plan: e.target.value }))} /></label>
                        <div className="filter-grid">
                          <label>Remediation Commands (one per line)<textarea rows={5} value={alertOnboarding.remediation_commands_text} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, remediation_commands_text: e.target.value }))} /></label>
                          <label>Remediation Scripts (one per line)<textarea rows={5} value={alertOnboarding.remediation_scripts_text} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, remediation_scripts_text: e.target.value }))} /></label>
                          <label>Validation Queries (one per line)<textarea rows={5} value={alertOnboarding.remediation_queries_text} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, remediation_queries_text: e.target.value }))} /></label>
                        </div>
                      </>
                    ) : null}
                    <button className="button-primary" type="submit" disabled={alertOnboardingState.loading}>
                      {alertOnboardingState.loading ? "Saving..." : docPromptMode === "update" && docPromptExistingDoc?.path ? "Update Document" : "Upload Document"}
                    </button>
                  </form>
                  {alertOnboardingState.error ? <p className="error">{alertOnboardingState.error}</p> : null}
                  {alertOnboardingState.result ? <p className="subtitle">{alertOnboardingState.result?.message || "Document saved."}</p> : null}

                  <article className="panel" style={{ marginTop: 10 }}>
                    <div className="panel-head">
                      <h3>Add Rule From Alert</h3>
                    </div>
                    <p className="subtitle">Use plain language like earlier flow; the system generates and stores a rule workflow.</p>
                    <div className="filter-grid">
                      <label>
                        Monitoring Platform
                        <select value={alertRuleDraft.platform} onChange={(e) => setAlertRuleDraft((curr) => ({ ...curr, platform: e.target.value }))}>
                          <option value="prometheus">prometheus</option>
                          <option value="new_relic">new_relic</option>
                          <option value="datadog">datadog</option>
                        </select>
                      </label>
                    </div>
                    <label>
                      Rule Requirement (Plain English)
                      <textarea rows={3} value={alertRuleDraft.requirement} onChange={(e) => setAlertRuleDraft((curr) => ({ ...curr, requirement: e.target.value }))} />
                    </label>
                    <button type="button" className="button-primary" onClick={addRuleFromAlertPrompt} disabled={alertRuleState.loading}>
                      {alertRuleState.loading ? "Creating Rule..." : "Add Rule"}
                    </button>
                    {alertRuleState.error ? <p className="error">{alertRuleState.error}</p> : null}
                    {alertRuleState.result?.workflow_id ? <p className="subtitle">Rule workflow created: {alertRuleState.result.workflow_id}</p> : null}
                  </article>
                </article>
              ) : null}

              {selectedAlertRow ? (
                <article className="panel" ref={alertDetailsRef}>
                  <div className="panel-head">
                    <div>
                      <h2>Alert Details Cockpit</h2>
                      <p>One guided workspace for evidence, documents, approval, remediation, and timeline review.</p>
                    </div>
                  </div>
                  <div className="detail-context">
                    <span><strong>ID:</strong> {selectedAlertId}</span>
                    <span><strong>Service:</strong> {selectedAlertRow?.service || "-"}</span>
                    <span><strong>Severity:</strong> {String(selectedAlertRow?.severity || "-").toUpperCase()}</span>
                  </div>

                  {(() => {
                    const matchedApproval = resolvePendingApprovalFromAlertRow(selectedAlertRow);
                    const incidentId = approvalIncidentId(matchedApproval);
                    const status = normalizeApprovalStatus(
                      matchedApproval?.status
                      || selectedAlertRow?.status
                      || selectedAlertRow?.state
                      || selectedAlertWorkflow?.incident?.status
                    );
                    const isResolved = isApprovalResolvedStatus(status);
                    const requiresApproval = Boolean(
                      matchedApproval
                      || selectedExecutionPlan?.requiresApproval
                      || selectedAlertRouting?.requires_approval
                      || selectedAlertWorkflow?.approval?.required
                      || selectedAlertWorkflow?.decision?.requires_approval
                      || isApprovalPendingStatus(status)
                    );
                    const hasActionableApproval = Boolean(matchedApproval && !isResolved);

                    if (!requiresApproval) {
                      return null;
                    }

                    return (
                      <article
                        className="panel"
                        style={{
                          marginBottom: 10,
                          borderColor: hasActionableApproval ? "#ef9a9a" : "#c7d7ea",
                          boxShadow: hasActionableApproval ? "0 10px 24px rgba(183, 28, 28, 0.14)" : "none",
                        }}
                      >
                        <div className="panel-head">
                          <h3>Decision Gate</h3>
                        </div>
                        <p className="subtitle">
                          {hasActionableApproval
                            ? `Matched incident ${incidentId || "-"} with status ${status || "pending"}.`
                            : matchedApproval
                              ? `Approval is already ${status || "resolved"} for this incident.`
                              : "This workflow indicates approval may be required, but no active pending approval row is linked yet."}
                        </p>
                        <div className="table-wrap">
                          <table>
                            <tbody>
                              <tr><th>Incident</th><td>{incidentId || "-"}</td></tr>
                              <tr><th>Status</th><td>{status || (hasActionableApproval ? "pending" : "not active")}</td></tr>
                              <tr><th>Role Eligible</th><td>{canUseApprovalActions ? "yes" : "no"}</td></tr>
                            </tbody>
                          </table>
                        </div>
                        {hasActionableApproval ? (
                          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                          <button
                            type="button"
                            className="button-secondary"
                            onClick={() => {
                              const matched = selectApprovalFromAlertRow(selectedAlertRow);
                              if (matched) {
                                setActiveTab("approval");
                              }
                            }}
                          >
                            Open Queue
                          </button>
                          <button
                            type="button"
                            className="button-primary"
                            onClick={() => setHomeDetailTab("approval")}
                          >
                            Review Decision
                          </button>
                          {canUseApprovalActions ? (
                            <button
                              type="button"
                              className="button-secondary"
                              onClick={() => selectApprovalIncident(matchedApproval)}
                              disabled={approvalState.loading}
                            >
                              Load Decision Form
                            </button>
                          ) : null}
                          </div>
                        ) : null}
                      </article>
                    );
                  })()}

                  <div className="detail-tabs">
                    {["overview", "evidence", "documents", "approval", "remediation", "diagnostics"].map((tab) => (
                      <button
                        key={`detail-${tab}`}
                        type="button"
                        className={`detail-tab ${homeDetailTab === tab ? "active" : ""}`}
                        onClick={() => setHomeDetailTab(tab)}
                      >
                        {tab === "overview" ? "Overview" : tab === "evidence" ? "Evidence" : tab === "documents" ? "Documents" : tab === "approval" ? "Approval" : tab === "remediation" ? "Remediation" : "Timeline"}
                      </button>
                    ))}
                  </div>

                  {homeDetailTab === "diagnostics" ? (
                    <div className="detail-tabs" style={{ marginTop: 8 }}>
                      {["timeline", "events", "finops", "api", "topics", "raw"].map((tab) => (
                        <button
                          key={`diag-${tab}`}
                          type="button"
                          className={`detail-tab ${diagnosticsDetailTab === tab ? "active" : ""}`}
                          onClick={() => setDiagnosticsDetailTab(tab)}
                        >
                          {tab === "timeline" ? "Flow Timeline" : tab === "events" ? "Agent Events" : tab === "finops" ? "FinOps" : tab === "api" ? "API Gateway" : tab === "topics" ? "Message Bus" : "Raw Payload"}
                        </button>
                      ))}
                    </div>
                  ) : null}

                  {selectedAlertData.loading ? <p className="subtitle">Loading selected alert details...</p> : null}
                  {selectedAlertData.error ? <p className="error">{selectedAlertData.error}</p> : null}

                  {homeDetailTab === "overview" ? (
                    <>
                      <div className="table-wrap table-wrap-scroll-x">
                        <table>
                          <tbody>
                            <tr><th>Alert</th><td>{selectedAlertRow?.name || selectedAlertWorkflow?.alert?.name || "-"}</td></tr>
                            <tr><th>Details Source</th><td>{selectedAlertDetailsSource}</td></tr>
                            <tr><th>Incident</th><td>{selectedAlertWorkflow?.incident?.id || selectedAlertWorkflow?.incident_id || "-"}</td></tr>
                            <tr>
                              <th>Persisted Incident Status</th>
                              <td>
                                <span className={`pill ${statusPillClass(selectedStageCompleteness.data?.status || selectedAlertWorkflow?.incident?.status)}`}>
                                  {selectedStageCompleteness.data?.status || selectedAlertWorkflow?.incident?.status || "-"}
                                </span>
                              </td>
                            </tr>
                            <tr><th>Closed At</th><td>{selectedAlertWorkflow?.incident?.closed_at || "-"}</td></tr>
                            <tr><th>Service</th><td>{selectedAlertRow?.service || selectedAlertWorkflow?.alert?.service || "-"}</td></tr>
                            <tr><th>Root Cause</th><td>{selectedAlertWorkflow?.recommendation?.root_cause || "-"}</td></tr>
                            <tr><th>Recommended Action</th><td>{selectedAlertWorkflow?.recommendation?.recommended_action || "-"}</td></tr>
                            <tr><th>Impact</th><td>{selectedAlertWorkflow?.recommendation?.impact || "-"}</td></tr>
                          </tbody>
                        </table>
                      </div>

                      <h3>AI Evaluation Metrics</h3>
                      <div className="alert-rule-summary-grid">
                        <article className="alert-rule-summary-card">
                          <span>Overall Quality</span>
                          <strong>{formatQualityPercent(selectedAlertEvaluation.overallScore)}</strong>
                          <small>{selectedAlertEvaluation.qualityLabel} | {selectedAlertEvaluation.provider}</small>
                        </article>
                        <article className="alert-rule-summary-card">
                          <span>Confidence</span>
                          <strong>{formatQualityPercent(selectedAlertEvaluation.confidenceScore)}</strong>
                          <small>Recommendation certainty</small>
                        </article>
                        <article className="alert-rule-summary-card">
                          <span>Grounding</span>
                          <strong>{formatQualityPercent(selectedAlertEvaluation.groundingScore)}</strong>
                          <small>Evidence and context support</small>
                        </article>
                        <article className="alert-rule-summary-card">
                          <span>Hallucination Risk</span>
                          <strong>{formatQualityPercent(selectedAlertEvaluation.hallucinationRisk)}</strong>
                          <small>{selectedAlertEvaluation.requiresReview ? "review recommended" : "within guardrail"}</small>
                        </article>
                        <article className="alert-rule-summary-card">
                          <span>Citation Coverage</span>
                          <strong>{formatQualityPercent(selectedAlertEvaluation.citationCoverage)}</strong>
                          <small>{selectedAlertEvaluation.signals?.citations ?? "-"} citation(s)</small>
                        </article>
                        <article className="alert-rule-summary-card">
                          <span>Evidence Coverage</span>
                          <strong>{formatQualityPercent(selectedAlertEvaluation.evidenceCoverage)}</strong>
                          <small>{selectedAlertEvaluation.signals?.rag_matches ?? selectedAlertRagDocuments.length} RAG match(es)</small>
                        </article>
                      </div>

                      {selectedAlertDocumentContract ? (
                        <>
                          <h3>Enterprise Controls</h3>
                          <div className="alert-rule-summary-grid">
                            <article className="alert-rule-summary-card">
                              <span>Canonical Contract</span>
                              <strong>{selectedAlertDocumentContract.canonical_alert?.schema_version || "-"}</strong>
                              <small>{selectedAlertDocumentContract.canonical_alert?.alert_uid || selectedAlertId}</small>
                            </article>
                            <article className="alert-rule-summary-card">
                              <span>Governance</span>
                              <strong>{selectedAlertDocumentContract.governance?.agent_contract_version || "-"}</strong>
                              <small>Approval gate: {selectedAlertDocumentContract.governance?.approval_gate_required ? "required" : "not required"}</small>
                            </article>
                            <article className="alert-rule-summary-card">
                              <span>RBAC</span>
                              <strong>{selectedAlertDocumentContract.rbac?.risk_tier || "-"}</strong>
                              <small>Tenant: {selectedAlertDocumentContract.rbac?.tenant || "default"} | Env: {selectedAlertDocumentContract.rbac?.environment || "-"}</small>
                            </article>
                            <article className="alert-rule-summary-card">
                              <span>Trace Quality</span>
                              <strong>{selectedAlertDocumentContract.observability?.trace_id || "-"}</strong>
                              <small>{selectedAlertDocumentContract.observability?.quality_gate || "-"}</small>
                            </article>
                            <article className="alert-rule-summary-card">
                              <span>RAG Quality</span>
                              <strong>{selectedAlertDocumentContract.rag_quality?.contract_version || "-"}</strong>
                              <small>Linked docs: {selectedAlertDocumentContract.document_link_summary?.count ?? 0}</small>
                            </article>
                            <article className="alert-rule-summary-card">
                              <span>Remediation Safety</span>
                              <strong>{selectedAlertDocumentContract.remediation_safety?.contract_version || "-"}</strong>
                              <small>Dry run: {selectedAlertDocumentContract.remediation_safety?.dry_run_required ? "required" : "optional"}</small>
                            </article>
                          </div>
                        </>
                      ) : null}

                      <h3>Persisted Stage Completeness</h3>
                      {selectedStageCompleteness.loading ? <p className="subtitle">Loading stage completeness...</p> : null}
                      {selectedStageCompleteness.error ? <p className="error">{selectedStageCompleteness.error}</p> : null}
                      {selectedStageCompleteness.data ? (
                        <div className="table-wrap">
                          <table>
                            <thead>
                              <tr>
                                <th>Stage</th>
                                <th>Persisted</th>
                                <th>Matched Event Types</th>
                              </tr>
                            </thead>
                            <tbody>
                              {(selectedStageCompleteness.data?.stages || []).map((row, index) => (
                                <tr key={`stage-${row.stage || index}`}>
                                  <td>{row.label || row.stage || "-"}</td>
                                  <td>{row.persisted ? "yes" : "no"}</td>
                                  <td>{Array.isArray(row.matched_event_types) && row.matched_event_types.length ? row.matched_event_types.join(" | ") : "-"}</td>
                                </tr>
                              ))}
                              {!Array.isArray(selectedStageCompleteness.data?.stages) || !selectedStageCompleteness.data.stages.length ? (
                                <tr><td colSpan={3}>No persisted stage rows found for incident.</td></tr>
                              ) : null}
                            </tbody>
                          </table>
                        </div>
                      ) : null}

                      {selectedStageCompleteness.data ? (
                        <p className="subtitle">
                          Completion: {selectedStageCompleteness.data?.stage_completion?.completed ?? 0}/{selectedStageCompleteness.data?.stage_completion?.total ?? 0}
                          {" "}({selectedStageCompleteness.data?.stage_completion?.percentage ?? 0}%)
                        </p>
                      ) : null}
                    </>
                  ) : null}

                  {homeDetailTab === "evidence" ? (
                    <article className="panel">
                      <div className="panel-head">
                        <h3>Evidence Workspace</h3>
                        <p>Canonical alert identity, trace context, and document-link evidence.</p>
                      </div>
                      <div className="table-wrap table-wrap-scroll-x">
                        <table>
                          <tbody>
                            <tr><th>Canonical Alert UID</th><td>{selectedAlertDocumentContract?.canonical_alert?.alert_uid || selectedAlertId || "-"}</td></tr>
                            <tr><th>Alert Type</th><td>{selectedAlertDocumentContract?.canonical_alert?.alert_type || selectedAlertRow?.name || "-"}</td></tr>
                            <tr><th>Service</th><td>{selectedAlertDocumentContract?.canonical_alert?.service || selectedAlertRow?.service || "-"}</td></tr>
                            <tr><th>Tenant / Environment</th><td>{selectedAlertDocumentContract?.canonical_alert?.tenant || "default"} / {selectedAlertDocumentContract?.canonical_alert?.environment || selectedAlertRow?.environment || "-"}</td></tr>
                            <tr><th>Trace ID</th><td>{selectedAlertDocumentContract?.observability?.trace_id || selectedAlertRow?.trace_id || "-"}</td></tr>
                            <tr><th>Correlation ID</th><td>{selectedAlertDocumentContract?.canonical_alert?.correlation_id || selectedAlertRow?.correlation_id || "-"}</td></tr>
                            <tr><th>Document Link Contract</th><td>{selectedAlertDocumentContract?.document_link_summary?.contract_version || "-"}</td></tr>
                            <tr><th>Linked Document Count</th><td>{selectedAlertDocumentContract?.document_link_summary?.count ?? selectedAlertRagDocuments.length}</td></tr>
                            <tr><th>Evaluation Contract</th><td>{selectedAlertEvaluation.contractVersion}</td></tr>
                            <tr><th>Overall Evaluation</th><td>{formatQualityPercent(selectedAlertEvaluation.overallScore)} ({selectedAlertEvaluation.qualityLabel})</td></tr>
                            <tr><th>Confidence Score</th><td>{formatQualityPercent(selectedAlertEvaluation.confidenceScore)}</td></tr>
                            <tr><th>Grounding Score</th><td>{formatQualityPercent(selectedAlertEvaluation.groundingScore)}</td></tr>
                            <tr><th>Hallucination Risk</th><td>{formatQualityPercent(selectedAlertEvaluation.hallucinationRisk)}</td></tr>
                            <tr><th>Citation Coverage</th><td>{formatQualityPercent(selectedAlertEvaluation.citationCoverage)}</td></tr>
                            <tr><th>Evidence Coverage</th><td>{formatQualityPercent(selectedAlertEvaluation.evidenceCoverage)}</td></tr>
                            <tr><th>External Judge</th><td>{selectedAlertEvaluation.externalJudge?.metric ? `${selectedAlertEvaluation.externalJudge.metric}: ${formatQualityPercent(selectedAlertEvaluation.externalJudge.score)}` : "not configured"}</td></tr>
                          </tbody>
                        </table>
                      </div>
                    </article>
                  ) : null}

                  {homeDetailTab === "approval" ? (
                    <article className="panel">
                      <div className="panel-head">
                        <h3>Approval Workspace</h3>
                        <p>Directly approve/reject/modify for this alert incident.</p>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <tbody>
                            <tr><th>Incident</th><td>{approvalForm.incident_id || selectedAlertWorkflow?.incident?.id || "-"}</td></tr>
                            <tr><th>Recommendation</th><td>{approvalForm.recommendation_id || "-"}</td></tr>
                            <tr><th>Current Approval Status</th><td>{selectedAlertWorkflow?.approval?.status || "pending"}</td></tr>
                            <tr><th>Role Eligible</th><td>{canUseApprovalActions ? "yes" : "no"}</td></tr>
                            <tr><th>Evaluation Quality</th><td>{formatQualityPercent(selectedAlertEvaluation.overallScore)} ({selectedAlertEvaluation.qualityLabel})</td></tr>
                            <tr><th>Grounding / Hallucination Risk</th><td>{formatQualityPercent(selectedAlertEvaluation.groundingScore)} / {formatQualityPercent(selectedAlertEvaluation.hallucinationRisk)}</td></tr>
                            <tr><th>Review Required</th><td>{selectedAlertEvaluation.requiresReview ? "yes" : "no"}</td></tr>
                          </tbody>
                        </table>
                      </div>
                      {canUseApprovalActions ? (
                        <form className="form" onSubmit={submitApproval}>
                          <div className="filter-grid">
                            <label>Action
                              <select value={approvalForm.action} onChange={(e) => setApprovalForm({ ...approvalForm, action: e.target.value })}>
                                <option value="approve">approve</option>
                                <option value="reject">reject</option>
                                <option value="modify">modify</option>
                              </select>
                            </label>
                            <label>Channel
                              <select value={approvalForm.channel} onChange={(e) => setApprovalForm({ ...approvalForm, channel: e.target.value })}>
                                <option value="web">web</option>
                                <option value="slack">slack</option>
                                <option value="teams">teams</option>
                                <option value="email">email</option>
                              </select>
                            </label>
                          </div>
                          {approvalForm.action === "modify" ? (
                            <label>Modified Action<textarea rows={2} value={approvalForm.modified_action} onChange={(e) => setApprovalForm({ ...approvalForm, modified_action: e.target.value })} /></label>
                          ) : null}
                          <label>Comment<textarea rows={2} value={approvalForm.comment} onChange={(e) => setApprovalForm({ ...approvalForm, comment: e.target.value })} /></label>
                          <button className="button-primary" type="submit" disabled={!approvalReady || approvalState.loading}>
                            {approvalState.loading ? "Submitting..." : "Submit Approval Action"}
                          </button>
                        </form>
                      ) : (
                        <p className="subtitle">Login with an approval-eligible role to submit actions. You can still view full approval context here.</p>
                      )}
                    </article>
                  ) : null}

                  {homeDetailTab === "documents" ? (
                    <article className="panel alert-documents-panel">
                      <div className="panel-head">
                        <h3>Alert Documents</h3>
                        <p>Download backend-linked documents for the selected alert.</p>
                      </div>
                      {ragDocs.error ? <p className="error">{ragDocs.error}</p> : null}
                      {selectedAlertDocumentLinks.error ? (
                        <p className="subtitle">Backend document-link contract unavailable; using local fallback matcher. {selectedAlertDocumentLinks.error}</p>
                      ) : null}
                      {selectedAlertDocumentLinks.loading ? <p className="subtitle">Resolving linked documents from backend contract...</p> : null}
                      {selectedAlertDocumentContract?.document_link_summary ? (
                        <p className="subtitle">
                          Source: {selectedAlertDocumentContract.document_link_summary.source}
                          {" | "}Matches: {selectedAlertDocumentContract.document_link_summary.count}
                          {" | "}Reasons: {(selectedAlertDocumentContract.document_link_summary.match_reasons || []).join(", ") || "-"}
                        </p>
                      ) : null}
                      {selectedAlertKnowledgeDocument ? (
                        <article className="alert-document-download-card alert-document-download-card-single">
                          <div>
                            <span className="workflow-pill workflow-pill-clear">knowledge document</span>
                            <span className="workflow-pill workflow-pill-idle" style={{ marginLeft: 6 }}>
                              {selectedAlertKnowledgeDocument.docs.length} source{selectedAlertKnowledgeDocument.docs.length === 1 ? "" : "s"}
                            </span>
                            <h4>{selectedAlertKnowledgeDocument.title}</h4>
                            <p>{selectedAlertKnowledgeDocument.summary}</p>
                          </div>
                          <div className="alert-document-meta">
                            <span>Alert: {selectedAlertId || "-"}</span>
                            <span>Service: {selectedAlertKnowledgeDocument.service || "-"}</span>
                            <span>Severity: {selectedAlertKnowledgeDocument.severity !== "-" ? selectedAlertKnowledgeDocument.severity : "-"}</span>
                            <span>Types: {selectedAlertKnowledgeDocument.kinds.join(", ") || "document"}</span>
                            <span>Match: {selectedAlertKnowledgeDocument.reasons.join(", ") || "backend-linked"} {selectedAlertKnowledgeDocument.confidence ? `(${Math.round(Number(selectedAlertKnowledgeDocument.confidence) * 100)}%)` : ""}</span>
                          </div>
                          <details className="alert-document-source-list">
                            <summary>Included backend document metadata</summary>
                            <div className="table-wrap" style={{ marginTop: 8 }}>
                              <table>
                                <thead>
                                  <tr><th>Type</th><th>Title</th><th>Path</th></tr>
                                </thead>
                                <tbody>
                                  {selectedAlertKnowledgeDocument.docs.map((doc, index) => (
                                    <tr key={`${doc?.path || doc?.title || "doc"}-${index}`}>
                                      <td>{doc?.kind || doc?.document_kind || "document"}</td>
                                      <td>{doc?.title || "-"}</td>
                                      <td>{doc?.path || "-"}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </details>
                          <button
                            type="button"
                            className="button-primary"
                            onClick={() => downloadConsolidatedAlertDocument(selectedAlertKnowledgeDocument.docs)}
                          >
                            Download Single Document
                          </button>
                        </article>
                      ) : (
                        <div className="alert-documents-empty">
                          <div>
                            <strong>No alert documents linked yet.</strong>
                            <p className="subtitle">
                              Use the same Provide Documents workflow for this alert to review the generated draft, upload content,
                              and save downloadable documents back to this tab.
                            </p>
                          </div>
                          <div className="alert-documents-kind-row">
                            {ALERT_DOC_KIND_OPTIONS.map((kind) => (
                              <span key={`empty-doc-kind-${kind}`}>{kind}</span>
                            ))}
                          </div>
                          <div className="alert-documents-empty-actions">
                            {canProvideAlertDocuments ? (
                              <button
                                type="button"
                                className="button-primary"
                                onClick={() => selectedAlertRow && openDocumentPrompt(selectedAlertRow)}
                                disabled={!selectedAlertRow || selectedAlertActionContext?.alertClosed}
                              >
                                Provide Documents
                              </button>
                            ) : (
                              <button type="button" className="button-secondary" onClick={() => setHomeDetailTab("approval")}>
                                Escalate To L2/L3
                              </button>
                            )}
                          </div>
                          {selectedAlertActionContext?.alertClosed ? (
                            <p className="subtitle">This alert is closed, so document creation is disabled.</p>
                          ) : null}
                          {!canProvideAlertDocuments ? (
                            <p className="subtitle">L1 operators can monitor and escalate this alert. L2, L3, and Admin users can provide alert documents.</p>
                          ) : null}
                        </div>
                      )}
                    </article>
                  ) : null}

                  {homeDetailTab === "diagnostics" && diagnosticsDetailTab === "timeline" ? (
                    <FlowTimelineGraph rows={selectedAlertTimelineRows} />
                  ) : null}

                  {homeDetailTab === "diagnostics" && diagnosticsDetailTab === "events" ? (
                    <AgentEventsGraph rows={selectedAlertEventsDisplay} />
                  ) : null}

                  {homeDetailTab === "diagnostics" && diagnosticsDetailTab === "finops" ? (
                    <>
                      <div className="table-wrap table-wrap-scroll-x">
                        <table>
                          <thead>
                            <tr>
                              <th>Task</th>
                              <th>Provider</th>
                              <th>Model</th>
                              <th>Input</th>
                              <th>Output</th>
                              <th>Cost USD</th>
                              <th>Notes</th>
                            </tr>
                          </thead>
                          <tbody>
                            {selectedAlertUsage.map((row, index) => (
                              <tr key={`usage-${index}`}>
                                <td>{row.task || "-"}</td>
                                <td>{row.provider || "-"}</td>
                                <td>{row.model || "-"}</td>
                                <td>{row.input_tokens || "-"}</td>
                                <td>{row.output_tokens || "-"}</td>
                                <td>{row.total_cost_usd || "-"}</td>
                                <td>{compactText(row.note || (row.estimated ? "estimated usage" : ""), 140) || "-"}</td>
                              </tr>
                            ))}
                            {!selectedAlertUsage.length ? (
                              <tr>
                                <td colSpan={7}>No FinOps usage rows rendered for selected alert.</td>
                              </tr>
                            ) : null}
                          </tbody>
                        </table>
                      </div>
                      <p className="subtitle">
                        FinOps diagnostics: rendered={selectedFinopsDiagnostics.usageRows}, workflow_calls={selectedFinopsDiagnostics.workflowCalls}, workflow_errors={selectedFinopsDiagnostics.workflowErrors}, recommendation_usage={selectedFinopsDiagnostics.recommendationUsage}, trace_calls={selectedFinopsDiagnostics.traceCalls}, trace_errors={selectedFinopsDiagnostics.traceErrors}
                      </p>
                      {!selectedAlertUsage.length ? (
                        <p className="subtitle">No usage rows means upstream services did not persist model usage/cost entries for this alert payload.</p>
                      ) : null}
                    </>
                  ) : null}

                  {homeDetailTab === "diagnostics" && diagnosticsDetailTab === "api" ? (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Time</th>
                            <th>Path</th>
                            <th>Status</th>
                            <th>Decision</th>
                            <th>Trace</th>
                          </tr>
                        </thead>
                        <tbody>
                          {gatewayRecent.rows.slice(0, 20).map((row, index) => (
                            <tr key={`api-${index}`}>
                              <td>{row.created_at || "-"}</td>
                              <td>{row.path || "-"}</td>
                              <td>{row.status_code || "-"}</td>
                              <td>{row?.safety?.decision || "-"}</td>
                              <td>{row.trace_id || "-"}</td>
                            </tr>
                          ))}
                          {!gatewayRecent.rows.length ? (
                            <tr>
                              <td colSpan={5}>No API gateway events found. Refresh or invoke a gateway endpoint.</td>
                            </tr>
                          ) : null}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {homeDetailTab === "diagnostics" && diagnosticsDetailTab === "topics" ? (
                    <TopicFlowGraph routing={selectedAlertRouting} timelineRows={selectedAlertTimelineRows} />
                  ) : null}

                  {homeDetailTab === "remediation" ? (
                    <>
                      <article className="panel remediation-workspace">
                        <div className="panel-head">
                          <h3>Resolution & Remediation Workspace</h3>
                          <p>Step 1: confirm incident + approval status. Step 2: execute approved remediation steps.</p>
                        </div>
                        <div className="workflow-guide-grid remediation-flow-grid">
                          {selectedWorkflowFlowStages.map((stage) => (
                            <div className="workflow-guide-card remediation-flow-card" key={stage.id}>
                              <strong>{stage.label}</strong>
                              <span className={`workflow-pill workflow-pill-${stage.status}`}>{stage.status.toUpperCase()}</span>
                              <p>{stage.detail}</p>
                            </div>
                          ))}
                        </div>
                        <div className="table-wrap table-wrap-scroll-x remediation-service-flow">
                          <table>
                            <thead>
                              <tr>
                                <th>Backend Service</th>
                                <th>Consumes</th>
                                <th>Publishes</th>
                                <th>Processing Agent</th>
                              </tr>
                            </thead>
                            <tbody>
                              {SERVICE_TOPIC_FLOW.map((stage) => (
                                <tr key={`service-flow-${stage.service}`}>
                                  <td>{stage.service}</td>
                                  <td>{stage.consumes}</td>
                                  <td>{stage.publishes}</td>
                                  <td>{stage.agent}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <div className="filter-grid remediation-kpi-grid">
                          <div className="remediation-kpi">
                            <span>Incident</span>
                            <p>
                              <span className={`pill ${statusPillClass(selectedExecutionBreakdown.incidentStatus)}`}>
                                {selectedExecutionPlan.incidentStatus || "-"}
                              </span>
                            </p>
                          </div>
                          <div className="remediation-kpi">
                            <span>Approval</span>
                            <p>
                              <span className={`pill ${statusPillClass(selectedExecutionBreakdown.approvalStatus)}`}>
                                {selectedExecutionPlan.approvalStatus || "pending"}
                              </span>
                            </p>
                          </div>
                          <div className="remediation-kpi">
                            <span>Commands</span>
                            <p>{selectedExecutionBreakdown.commands.length}</p>
                          </div>
                          <div className="remediation-kpi">
                            <span>Scripts</span>
                            <p>{selectedExecutionBreakdown.scripts.length}</p>
                          </div>
                          <div className="remediation-kpi">
                            <span>Queries</span>
                            <p>{selectedExecutionBreakdown.queries.length}</p>
                          </div>
                        </div>
                        <p className="subtitle">
                          {selectedExecutionBreakdown.hasPlan
                            ? "Plan is ready. Modify commands, scripts, or validation queries before executing the approved run path."
                            : "No remediation plan is available yet. Ensure recommendation and workflow events have been generated."}
                        </p>
                        <article className="panel remediation-connection-panel">
                          <div className="panel-head">
                            <h3>Application Connection Details</h3>
                            <p>Execution target used for approval, dry-run context, and simulated remediation records.</p>
                          </div>
                          <div className="filter-grid">
                            <label>Application<input value={selectedApplicationConnection.application} readOnly /></label>
                            <label>Service<input value={selectedApplicationConnection.service} readOnly /></label>
                            <label>Environment<input value={selectedApplicationConnection.environment} readOnly /></label>
                            <label>Source<input value={selectedApplicationConnection.source} readOnly /></label>
                            <label>Connection Type<input value={remediationPlanEditor.connection_type} onChange={(e) => setRemediationPlanEditor((curr) => ({ ...curr, connection_type: e.target.value }))} /></label>
                            <label>Endpoint URL<input value={remediationPlanEditor.connection_url} placeholder="https://app-or-metrics-endpoint" onChange={(e) => setRemediationPlanEditor((curr) => ({ ...curr, connection_url: e.target.value }))} /></label>
                            <label>Namespace / Runtime<input value={remediationPlanEditor.namespace} placeholder="prod / namespace / resource group" onChange={(e) => setRemediationPlanEditor((curr) => ({ ...curr, namespace: e.target.value }))} /></label>
                          </div>
                        </article>
                        <article className="panel remediation-editor-panel">
                          <div className="panel-head">
                            <h3>Editable Remediation Command Plan</h3>
                            <p>One item per line. The approved edited plan is submitted to the remediation engine.</p>
                          </div>
                          <div className="remediation-editor-grid">
                            <label>Commands<textarea rows={6} value={remediationPlanEditor.commands} onChange={(e) => setRemediationPlanEditor((curr) => ({ ...curr, commands: e.target.value }))} /></label>
                            <label>Scripts<textarea rows={6} value={remediationPlanEditor.scripts} onChange={(e) => setRemediationPlanEditor((curr) => ({ ...curr, scripts: e.target.value }))} /></label>
                            <label>Validation Queries<textarea rows={6} value={remediationPlanEditor.queries} onChange={(e) => setRemediationPlanEditor((curr) => ({ ...curr, queries: e.target.value }))} /></label>
                          </div>
                          <label>Execution Notes<textarea rows={2} value={remediationPlanEditor.notes} onChange={(e) => setRemediationPlanEditor((curr) => ({ ...curr, notes: e.target.value }))} /></label>
                          <div className="remediation-execute-row">
                            <button
                              type="button"
                              className="button-primary"
                              onClick={executeApprovedRemediationPlan}
                              disabled={remediationExecutionState.loading || !canUseApprovalActions}
                              title={canUseApprovalActions ? "Execute the approved edited plan through remediation-engine" : "Approval-eligible role required"}
                            >
                              {remediationExecutionState.loading ? "Executing..." : "Execute Approved Plan"}
                            </button>
                            <button
                              type="button"
                              className="button-secondary"
                              onClick={() => setRemediationPlanEditor((curr) => ({
                                ...curr,
                                commands: selectedExecutionBreakdown.commands.join("\n"),
                                scripts: selectedExecutionBreakdown.scripts.join("\n"),
                                queries: selectedExecutionBreakdown.queries.join("\n"),
                              }))}
                              disabled={remediationExecutionState.loading}
                            >
                              Reset To Suggested Plan
                            </button>
                          </div>
                          {remediationExecutionState.error ? <p className="error">{remediationExecutionState.error}</p> : null}
                          {remediationExecutionState.result ? (
                            <pre className="result">{JSON.stringify(unwrap(remediationExecutionState.result), null, 2)}</pre>
                          ) : null}
                        </article>
                        <div className="table-wrap remediation-step-table" style={{ marginTop: 8 }}>
                          <table>
                            <thead>
                              <tr><th>Type</th><th>Step</th><th>Action</th></tr>
                            </thead>
                            <tbody>
                              {selectedExecutionBreakdown.commands.map((step, index) => (
                                <tr key={`summary-command-${index}`}>
                                  <td>Command</td>
                                  <td>{step}</td>
                                  <td><button type="button" className="button-secondary" onClick={() => copyPlanStep(step)}>Copy</button></td>
                                </tr>
                              ))}
                              {selectedExecutionBreakdown.scripts.map((step, index) => (
                                <tr key={`summary-script-${index}`}>
                                  <td>Script</td>
                                  <td>{step}</td>
                                  <td><button type="button" className="button-secondary" onClick={() => copyPlanStep(step)}>Copy</button></td>
                                </tr>
                              ))}
                              {selectedExecutionBreakdown.queries.map((step, index) => (
                                <tr key={`summary-query-${index}`}>
                                  <td>Query</td>
                                  <td>{step}</td>
                                  <td><button type="button" className="button-secondary" onClick={() => copyPlanStep(step)}>Copy</button></td>
                                </tr>
                              ))}
                              {!selectedExecutionBreakdown.hasPlan ? <tr><td colSpan={3}>No remediation steps available.</td></tr> : null}
                            </tbody>
                          </table>
                        </div>
                      </article>
                      <ExecutionPlanGraph plan={selectedExecutionPlan} />
                    </>
                  ) : null}

                  {homeDetailTab === "diagnostics" && diagnosticsDetailTab === "raw" ? (
                    <pre className="result">{JSON.stringify(selectedAlertData.payload || {}, null, 2)}</pre>
                  ) : null}
                </article>
              ) : (
                <article className="panel">
                  <p className="subtitle">Select an alert in Alert Stream to open the detail tabs workspace.</p>
                </article>
              )}
            </section>
          ) : null}

          {activeTab === "copilot" ? (
            <section className="grid single-col">
              <article className="panel copilot-panel">
                <div className="panel-head">
                  <h2>Copilot Studio</h2>
                  <p>One guided place to onboard projects, create alert documents, and manage users.</p>
                  <button className="button-secondary" onClick={refreshAll}>Refresh</button>
                </div>

                <div className="copilot-summary-grid">
                  <div className="copilot-summary-card copilot-tone-ops">
                    <strong>Project Onboarding</strong>
                    <span>Set project identity, environment, and monitoring endpoints.</span>
                    <button type="button" className="button-primary" onClick={() => openCopilotWorkspace("project")}>Open Unified Setup</button>
                  </div>
                  <div className="copilot-summary-card copilot-tone-bus">
                    <strong>Alert Documents</strong>
                    <span>Create onboarding docs and bulk alert knowledge from one place.</span>
                    <button type="button" className="button-primary" onClick={() => openCopilotWorkspace("alerts")}>Open Docs</button>
                  </div>
                  <div className={`copilot-summary-card ${isAdministrator ? "copilot-tone-meta" : "copilot-tone-muted"}`}>
                    <strong>User Management</strong>
                    <span>{isAdministrator ? "Create, edit, and reset users." : "Administrator-only control."}</span>
                    <button type="button" className="button-primary" onClick={() => openCopilotWorkspace("users")} disabled={!isAdministrator}>Open Users</button>
                  </div>
                </div>

                <div className="copilot-flow-grid">
                  <div className="copilot-flow-card">
                    <span className="copilot-step">1</span>
                    <div>
                      <strong>Start from a project</strong>
                      <p>Use the project onboarding form to register monitoring details and assignments.</p>
                    </div>
                  </div>
                  <div className="copilot-flow-card">
                    <span className="copilot-step">2</span>
                    <div>
                      <strong>Generate alert docs</strong>
                      <p>Write onboarding docs or bulk import runbook-style alert guidance.</p>
                    </div>
                  </div>
                  <div className="copilot-flow-card">
                    <span className="copilot-step">3</span>
                    <div>
                      <strong>Manage access</strong>
                      <p>Keep user roles, statuses, and passwords in the same workspace.</p>
                    </div>
                  </div>
                </div>

                <div className="copilot-shortcuts">
                  <button type="button" className="button-secondary" onClick={() => openCopilotWorkspace("project")}>Monitoring + Landing Pad Setup</button>
                  <button type="button" className="button-secondary" onClick={() => openCopilotWorkspace("alerts")}>Alert Documents</button>
                  <button type="button" className="button-secondary" onClick={() => openCopilotWorkspace("users")} disabled={!isAdministrator}>User Management</button>
                  <button type="button" className="button-secondary" onClick={() => setActiveTab("summary")}>Incident Metadata</button>
                </div>
              </article>
            </section>
          ) : null}

          {activeTab === "executive" ? (
            <section className="grid single-col">
              <article className="panel">
                <div className="panel-head">
                  <h2>Executive Dashboard</h2>
                  <p>Leadership-level snapshot of reliability, risk, and closure trend.</p>
                </div>
                <div className="stat-grid">
                  <div className="stat-card"><strong>Open Alerts</strong><span>{monitorScopedAlerts.length}</span></div>
                  <div className="stat-card"><strong>Total Requests</strong><span>{executiveMetrics.totalRequests}</span></div>
                  <div className="stat-card"><strong>Failures</strong><span>{executiveMetrics.failedRequests}</span></div>
                  <div className="stat-card"><strong>P95 Latency</strong><span>{executiveMetrics.p95LatencyMs.toFixed(1)} ms</span></div>
                  <div className="stat-card"><strong>Closed Tickets</strong><span>{executiveClosedSummary.total}</span></div>
                  <div className="stat-card"><strong>Closure Rate</strong><span>{executiveClosedSummary.closureRate.toFixed(1)}%</span></div>
                  <div className="stat-card"><strong>Pending Approvals</strong><span>{pendingApprovals.length}</span></div>
                  <div className="stat-card"><strong>SLA At Risk</strong><span>{executiveInsights.slaAtRisk}</span></div>
                  <div className="stat-card"><strong>Avg Approval Wait</strong><span>{executiveInsights.avgApprovalWaitMinutes.toFixed(1)} min</span></div>
                  <div className="stat-card"><strong>Auto Remediation</strong><span>{executiveInsights.automationRate.toFixed(1)}%</span></div>
                  <div className="stat-card"><strong>LLM Cost</strong><span>${executiveMetrics.finopsCost.toFixed(6)}</span></div>
                </div>

                <div className="executive-chart-grid">
                  <HorizontalBarChart
                    title="Request Volume"
                    subtitle="Observed API gateway events in current window"
                    items={[
                      { label: "Total", value: executiveMetrics.totalRequests, tone: "meta" },
                      { label: "Success", value: executiveMetrics.successRequests, tone: "ops" },
                      { label: "Failure", value: executiveMetrics.failedRequests, tone: "risk" },
                    ]}
                  />
                  <SuccessFailureDonut
                    success={executiveMetrics.successRequests}
                    failure={executiveMetrics.failedRequests}
                  />
                  <HorizontalBarChart
                    title="Latency Trend"
                    subtitle={`Avg ${executiveMetrics.avgLatencyMs.toFixed(1)} ms | P95 ${executiveMetrics.p95LatencyMs.toFixed(1)} ms`}
                    items={executiveMetrics.latencyTrend}
                  />
                  <HorizontalBarChart
                    title="FinOps Overview"
                    subtitle="Aggregated LLM usage and spend"
                    items={[
                      { label: "Model Calls", value: executiveMetrics.finopsCalls, tone: "meta" },
                      { label: "Tokens", value: executiveMetrics.finopsTokens, tone: "cost" },
                      {
                        label: "Cost USD",
                        value: executiveMetrics.finopsCost,
                        displayValue: `$${executiveMetrics.finopsCost.toFixed(6)}`,
                        tone: "bus",
                      },
                    ]}
                  />
                  <HorizontalBarChart
                    title="Closed Tickets by Risk"
                    subtitle="Recent closure distribution"
                    items={executiveClosedSummary.riskItems}
                  />
                  <HorizontalBarChart
                    title="Closed Tickets by Execution Mode"
                    subtitle="How incidents were handled"
                    items={executiveClosedSummary.modeItems}
                  />
                  <HorizontalBarChart
                    title="Weekly Open Incident Trend"
                    subtitle="Open incidents observed per day (7-day window)"
                    items={executiveInsights.weeklyOpenTrend}
                  />
                  <HorizontalBarChart
                    title="Weekly Closed Incident Trend"
                    subtitle="Closed incidents per day (7-day window)"
                    items={executiveInsights.weeklyClosedTrend}
                  />
                </div>

                <article className="panel executive-flow-panel">
                  <div className="panel-head">
                    <h3>End-to-End Processing + FinOps</h3>
                    <p>Landing pad ingestion, parallel worker processing, remediation execution, and cost visibility in one leadership view.</p>
                  </div>
                  <div className="workflow-guide-grid executive-flow-grid">
                    {selectedWorkflowFlowStages.map((stage) => (
                      <div className="workflow-guide-card executive-flow-card" key={`exec-flow-${stage.id}`}>
                        <strong>{stage.label}</strong>
                        <span className={`workflow-pill workflow-pill-${stage.status}`}>{stage.status.toUpperCase()}</span>
                        <p>{stage.detail}</p>
                      </div>
                    ))}
                  </div>
                  <div className="table-wrap table-wrap-scroll-x">
                    <table>
                      <thead>
                        <tr>
                          <th>Backend Service</th>
                          <th>Consumes</th>
                          <th>Publishes</th>
                          <th>Processing Agent</th>
                        </tr>
                      </thead>
                      <tbody>
                        {SERVICE_TOPIC_FLOW.map((stage) => (
                          <tr key={`exec-service-flow-${stage.service}`}>
                            <td>{stage.service}</td>
                            <td>{stage.consumes}</td>
                            <td>{stage.publishes}</td>
                            <td>{stage.agent}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Provider</th>
                          <th>Calls</th>
                          <th>Tokens</th>
                          <th>Cost USD</th>
                        </tr>
                      </thead>
                      <tbody>
                        {finopsByProvider.map((row, index) => (
                          <tr key={`exec-finops-${row.provider}-${index}`}>
                            <td>{row.provider}</td>
                            <td>{row.calls}</td>
                            <td>{row.total_tokens}</td>
                            <td>{Number(row.total_cost_usd || 0).toFixed(6)}</td>
                          </tr>
                        ))}
                        {!finopsByProvider.length ? (
                          <tr>
                            <td colSpan={4}>No model calls recorded yet.</td>
                          </tr>
                        ) : null}
                      </tbody>
                    </table>
                  </div>
                </article>

                <h3>Executive Risk & Operations Report</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th>Value</th>
                        <th>Interpretation</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>SLA At Risk</td>
                        <td>{executiveInsights.slaAtRisk}</td>
                        <td>Open high/critical or manual-mode incidents that may affect business SLO/SLA outcomes.</td>
                      </tr>
                      <tr>
                        <td>Average Approval Wait</td>
                        <td>{executiveInsights.avgApprovalWaitMinutes.toFixed(1)} min</td>
                        <td>Mean time pending in approval queue; useful for governance and response speed tracking.</td>
                      </tr>
                      <tr>
                        <td>Auto Remediation Rate</td>
                        <td>{executiveInsights.automationRate.toFixed(1)}%</td>
                        <td>Share of closed incidents resolved using automatic execution modes.</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Incident</th>
                        <th>Service</th>
                        <th>Risk</th>
                        <th>Status</th>
                        <th>Execution Mode</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {monitorScopedIncidentMetadata.slice(0, 20).map((row, index) => (
                        <tr key={`exec-${row.incident_id || index}`}>
                          <td>{row.incident_id || "-"}</td>
                          <td>{row.service || "-"}</td>
                          <td>{row.risk_tier || "-"}</td>
                          <td><span className={`pill ${statusPillClass(row.status)}`}>{row.status || "-"}</span></td>
                          <td>{row.execution_mode || "-"}</td>
                          <td>
                            <button type="button" className="button-secondary" onClick={() => openAlertDetailsFromIncident(row)}>
                              Open
                            </button>
                          </td>
                        </tr>
                      ))}
                      {!monitorScopedIncidentMetadata.length ? (
                        <tr>
                          <td colSpan={6}>No executive rows available for {applicationToMonitor}.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>

                <h3>Recently Closed Tickets</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Incident</th>
                        <th>Service</th>
                        <th>Risk</th>
                        <th>Execution Mode</th>
                        <th>Status</th>
                        <th>Closed At</th>
                      </tr>
                    </thead>
                    <tbody>
                      {executiveClosedSummary.recentRows.map((row, index) => (
                        <tr key={`exec-closed-${row.incident_id || index}`}>
                          <td>{row.incident_id || "-"}</td>
                          <td>{row.service || "-"}</td>
                          <td>{row.risk_tier || row.risk || row.severity || "-"}</td>
                          <td>{row.execution_mode || "-"}</td>
                          <td><span className={`pill ${statusPillClass(row.status || "closed")}`}>{row.status || "closed"}</span></td>
                          <td>{row.closed_at || row.updated_at || "-"}</td>
                        </tr>
                      ))}
                      {!executiveClosedSummary.recentRows.length ? (
                        <tr>
                          <td colSpan={6}>No closed tickets are available yet.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </article>
            </section>
          ) : null}

          {activeTab === "admin" && isAdministrator ? (
            <section className="grid single-col">
              <article className="panel admin-center-panel">
                <div className="panel-head">
                  <h2>Admin Center</h2>
                  <p>Three-step workspace for access, setup, and alert knowledge.</p>
                </div>

                <div className="admin-journey-grid">
                  {adminJourneyCards.map((step) => (
                    <article
                      key={`admin-journey-${step.id}`}
                      className={`admin-journey-card ${adminJourneyStep === step.id ? "active" : ""}`}
                    >
                      <strong>{step.title}</strong>
                      <span>{step.hint}</span>
                      <small>{step.status}</small>
                      <div className="admin-journey-meta">
                        <span className={`admin-journey-chip admin-journey-chip-${step.tone || "info"}`}>{step.tone || "info"}</span>
                        <span className={`workflow-pill ${step.complete ? "workflow-pill-active" : "workflow-pill-idle"}`}>
                          {step.complete ? "done" : "pending"}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="button-secondary admin-journey-cta"
                        onClick={() => triggerAdminJourneyCta(step.id)}
                      >
                        {step.cta}
                      </button>
                    </article>
                  ))}
                </div>

                <p className="subtitle">Navigate by stage: Access handles identity, Setup covers landing pad and approvals, Knowledge stores alert intelligence.</p>
                <p className="subtitle"><strong>Current Stage:</strong> {adminWorkspaceCaptions[adminWorkspace] || "Administrative workspace controls."}</p>

                {adminWorkspace === "users" ? (
                  <div className="grid single-col">
                    <article className="panel">
                      <h3>Session</h3>
                      {adminSession.user ? <p className="subtitle">Signed in as {adminSession.user.username} ({adminSession.user.role_name})</p> : null}
                      {adminSession.error ? <p className="error">{adminSession.error}</p> : null}
                    </article>

                    <article className="panel">
                      <div className="panel-head">
                        <h3>Users</h3>
                        <button className="button-secondary" type="button" onClick={loadAdminUsersAndRoles} disabled={!adminSession.accessToken || adminUsers.loading}>Refresh</button>
                      </div>
                      {adminUsers.error ? <p className="error">{adminUsers.error}</p> : null}
                      {adminUsers.loading ? <p className="subtitle">Loading users and roles...</p> : null}
                      {!adminUsers.loading && !adminUsers.error && !adminUsers.rows.length ? (
                        <div className="empty-state-panel">
                          <strong>No users are shown yet</strong>
                          <span>Refresh access controls to load seeded users, or create a new user below.</span>
                          <button className="button-secondary" type="button" onClick={loadAdminUsersAndRoles} disabled={!adminSession.accessToken}>
                            Refresh Users
                          </button>
                        </div>
                      ) : null}
                      <div className="table-wrap table-wrap-scroll-x">
                        <table>
                          <thead>
                            <tr><th>ID</th><th>Username</th><th>Email</th><th>Role</th><th>Status</th><th>Actions</th></tr>
                          </thead>
                          <tbody>
                            {adminUsers.rows.map((row, index) => (
                              <tr key={`admin-user-${row.id || index}`}>
                                <td>{row.id || "-"}</td><td>{row.username || "-"}</td><td>{row.email || "-"}</td><td>{row.role_name || row.role_id || "-"}</td><td>{row.status || "-"}</td>
                                <td><button type="button" className="button-secondary" onClick={() => selectAdminUserForEdit(row)}>Edit</button></td>
                              </tr>
                            ))}
                            {!adminUsers.rows.length && adminUsers.loading ? <tr><td colSpan={6}>Loading users...</td></tr> : null}
                            {!adminUsers.rows.length && !adminUsers.loading && adminUsers.error ? <tr><td colSpan={6}>Unable to load users. Review the error above.</td></tr> : null}
                            {!adminUsers.rows.length && !adminUsers.loading && !adminUsers.error ? <tr><td colSpan={6}>No users returned yet. Use Refresh Users or create a user.</td></tr> : null}
                          </tbody>
                        </table>
                      </div>
                    </article>

                    <article className="panel">
                      <h3>Create User</h3>
                      <details className="admin-collapsible" open>
                        <summary>Create New User</summary>
                        <form className="form" onSubmit={createAdminUser}>
                          <div className="filter-grid">
                            <label>Username<input value={adminCreateUser.username} onChange={(e) => setAdminCreateUser((curr) => ({ ...curr, username: e.target.value }))} /></label>
                            <label>Email<input value={adminCreateUser.email} onChange={(e) => setAdminCreateUser((curr) => ({ ...curr, email: e.target.value }))} /></label>
                            <label>First Name<input value={adminCreateUser.first_name} onChange={(e) => setAdminCreateUser((curr) => ({ ...curr, first_name: e.target.value }))} /></label>
                            <label>Last Name<input value={adminCreateUser.last_name} onChange={(e) => setAdminCreateUser((curr) => ({ ...curr, last_name: e.target.value }))} /></label>
                          </div>
                          <div className="filter-grid">
                            <label>Password<input type="password" value={adminCreateUser.password} onChange={(e) => setAdminCreateUser((curr) => ({ ...curr, password: e.target.value }))} /></label>
                            <label>Role
                              <select value={adminCreateUser.role_id} onChange={(e) => setAdminCreateUser((curr) => ({ ...curr, role_id: Number(e.target.value) }))}>
                                {(adminRoles.length ? adminRoles : [{ id: 1, name: "administrator" }]).map((role) => (
                                  <option key={`role-${role.id}`} value={role.id}>{role.name}</option>
                                ))}
                              </select>
                            </label>
                            <label>Status<input value={adminCreateUser.status} onChange={(e) => setAdminCreateUser((curr) => ({ ...curr, status: e.target.value }))} /></label>
                            <label>Active
                              <select value={String(adminCreateUser.is_active)} onChange={(e) => setAdminCreateUser((curr) => ({ ...curr, is_active: e.target.value === "true" }))}>
                                <option value="true">true</option><option value="false">false</option>
                              </select>
                            </label>
                          </div>
                          <button className="button-primary" type="submit" disabled={!adminSession.accessToken || adminUsers.loading}>Create User</button>
                        </form>
                      </details>
                    </article>

                    <article className="panel">
                      <h3>Modify User</h3>
                      <details className="admin-collapsible">
                        <summary>Edit Existing User</summary>
                        <form className="form" onSubmit={updateAdminUser}>
                          <div className="filter-grid">
                            <label>User ID<input value={adminEditUser.id || ""} readOnly /></label>
                            <label>Username<input value={adminEditUser.username} readOnly /></label>
                            <label>Email<input value={adminEditUser.email} onChange={(e) => setAdminEditUser((curr) => ({ ...curr, email: e.target.value }))} /></label>
                            <label>Role
                              <select value={adminEditUser.role_id} onChange={(e) => setAdminEditUser((curr) => ({ ...curr, role_id: Number(e.target.value) }))}>
                                {(adminRoles.length ? adminRoles : [{ id: 1, name: "Administrator" }]).map((role) => (
                                  <option key={`edit-role-${role.id}`} value={role.id}>{role.name}</option>
                                ))}
                              </select>
                            </label>
                          </div>
                          <div className="filter-grid">
                            <label>First Name<input value={adminEditUser.first_name} onChange={(e) => setAdminEditUser((curr) => ({ ...curr, first_name: e.target.value }))} /></label>
                            <label>Last Name<input value={adminEditUser.last_name} onChange={(e) => setAdminEditUser((curr) => ({ ...curr, last_name: e.target.value }))} /></label>
                            <label>Status<input value={adminEditUser.status} onChange={(e) => setAdminEditUser((curr) => ({ ...curr, status: e.target.value }))} /></label>
                            <label>Active
                              <select value={String(adminEditUser.is_active)} onChange={(e) => setAdminEditUser((curr) => ({ ...curr, is_active: e.target.value === "true" }))}>
                                <option value="true">true</option><option value="false">false</option>
                              </select>
                            </label>
                          </div>
                          <button className="button-primary" type="submit" disabled={!adminSession.accessToken || adminUsers.loading || !adminEditUser.id}>Update User</button>
                        </form>
                      </details>
                    </article>

                    <article className="panel">
                      <h3>Reset Password</h3>
                      <details className="admin-collapsible">
                        <summary>Reset User Password</summary>
                        <form className="form" onSubmit={resetAdminUserPassword}>
                          <div className="filter-grid">
                            <label>User ID<input value={adminResetPasswordForm.user_id || ""} readOnly /></label>
                            <label>New Password<input type="password" value={adminResetPasswordForm.new_password} onChange={(e) => setAdminResetPasswordForm((curr) => ({ ...curr, new_password: e.target.value }))} /></label>
                          </div>
                          <button className="button-primary" type="submit" disabled={!adminSession.accessToken || adminUsers.loading || !adminResetPasswordForm.user_id || !String(adminResetPasswordForm.new_password || "").trim()}>Reset Password</button>
                        </form>
                      </details>
                    </article>
                  </div>

                ) : null}

                {adminWorkspace === "project" ? (
                  <div className="grid single-col admin-flow-section admin-flow-project">
                    <article className="panel project-stepper-panel">
                      <div className="panel-head">
                        <div>
                          <h3>Setup Wizard</h3>
                          <p>Use two main steps: set up monitoring first, then add documents and rules.</p>
                        </div>
                        <button
                          type="button"
                          className={`setup-section-icon-button ${projectSetupShowAll ? "active" : ""}`}
                          aria-label={projectSetupShowAll ? "Focus current setup step" : "Show full setup"}
                          title={projectSetupShowAll ? "Focus current step" : "Show full setup"}
                          onClick={() => setProjectSetupShowAll((current) => !current)}
                        />
                      </div>
                      <div className="setup-wizard-summary">
                        <div>
                          <span>Project</span>
                          <strong>{String(onboardingForm.name || selectedOnboardingProject || "Not selected")}</strong>
                        </div>
                        <div>
                          <span>Path</span>
                          <strong>{onboardingForm.onboarding_path === "setup_monitoring" ? "Prometheus setup" : "Existing monitoring"}</strong>
                        </div>
                        <div>
                          <span>Service Knowledge</span>
                          <strong>{onboardingSourceDocCount > 0 ? "added" : "missing"}</strong>
                        </div>
                        <div>
                          <span>Generated Rules</span>
                          <strong>{onboardingGeneratedRuleRows.length}</strong>
                        </div>
                      </div>
                      <div className="project-stepper-grid">
                        {projectStepCards.map((card) => (
                          <button
                            key={`project-step-${card.id}`}
                            type="button"
                            className={`project-step-card ${projectSetupStep === card.id ? "active" : ""}`}
                            onClick={() => {
                              setProjectSetupStep(card.id);
                              setProjectSetupShowAll(false);
                              if (card.id === "knowledge") {
                                setAlertKnowledgeView("onboarding");
                              }
                            }}
                          >
                            <strong>{card.label}</strong>
                            <span>{card.hint}</span>
                            <span className={`workflow-pill ${card.complete ? "workflow-pill-active" : "workflow-pill-idle"}`}>
                              {card.complete ? "done" : "pending"}
                            </span>
                          </button>
                        ))}
                      </div>
                    </article>
                    {showProjectStep("setup") ? (
                    <article className="panel">
                      <div className="panel-head">
                        <div>
                          <h3>Setup Monitoring</h3>
                          <p>Choose the monitoring path, enter the tool endpoint, and save the landing-pad setup.</p>
                        </div>
                        <div style={{ display: "flex", gap: 8 }}>
                          <button type="button" className="button-secondary" onClick={loadOnboardingAdminData}>Refresh</button>
                          <button
                            type="button"
                            className="button-secondary"
                            onClick={() => deleteProjectOnboarding(selectedOnboardingProject || onboardingForm.name)}
                            disabled={onboardingProjectMode === "new" || onboardingState.loading || !String(selectedOnboardingProject || onboardingForm.name || "").trim()}
                          >
                            Delete Project
                          </button>
                        </div>
                      </div>
                      <div className="filter-grid">
                        <label>
                          Project Mode
                          <select
                            value={onboardingProjectMode}
                            onChange={(e) => {
                              const nextMode = e.target.value;
                              setOnboardingProjectMode(nextMode);
                              if (nextMode === "new") {
                                resetNewProjectOnboardingDraft();
                              }
                            }}
                          >
                            <option value="existing">Update Existing Project</option>
                            <option value="new">Create New Project</option>
                          </select>
                        </label>
                        <div style={{ display: "flex", alignItems: "end" }}>
                          <button type="button" className="button-secondary" onClick={resetNewProjectOnboardingDraft}>
                            Clear Form
                          </button>
                        </div>
                      </div>
                      <p className="subtitle"><strong>Next:</strong> Save monitoring, then add Service Knowledge in Documents & Rules.</p>
                      {onboardingDocumentSummary.total > 0 ? <p className="subtitle"><strong>Docs:</strong> {onboardingDocumentSummary.total} generated ({onboardingDocumentSummary.approved ? "approved" : "pending"}).</p> : null}
                      {onboardingProjectMode === "existing" ? (
                        <div className="filter-grid">
                        <label>
                          Select Existing Project
                          <select
                            value={selectedOnboardingProject}
                            onChange={(e) => {
                              const nextProjectName = e.target.value;
                              setSelectedOnboardingProject(nextProjectName);
                              const row = (onboardingState.rows || []).find((item) => extractOnboardingProjectName(item) === nextProjectName);
                              if (row) {
                                applyProjectOnboardingRow(row);
                                return;
                              }
                              setOnboardingForm((curr) => ({
                                ...curr,
                                name: nextProjectName,
                                assignment_project: nextProjectName,
                              }));
                            }}
                          >
                            <option value="">Select project</option>
                            {onboardingProjectOptions.map((name, index) => (
                              <option key={`project-select-${name}-${index}`} value={name}>{name}</option>
                            ))}
                          </select>
                        </label>
                        </div>
                      ) : null}
                      <form className="form" onSubmit={saveOnboardingConnectivity}>
                        {onboardingValidationErrors.length ? (
                          <div>
                            {onboardingValidationErrors.map((msg, index) => <p key={`onboarding-error-${index}`} className="error">{msg}</p>)}
                          </div>
                        ) : null}
                        {onboardingHasPendingDocumentApproval ? (
                          <p className="error">Approve pending generated documents before submitting another Create/Update.</p>
                        ) : null}
                        {onboardingAdvisory ? <p className="subtitle">{onboardingAdvisory}</p> : null}
                        <details className="setup-form-section" open>
                          <summary>
                            <span>Project Details</span>
                            <small>Required identity fields</small>
                          </summary>
                        <div className="filter-grid">
                          <label>Project Name *<input placeholder="example-payments" value={onboardingForm.name} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, name: e.target.value, assignment_project: e.target.value }))} /></label>
                          <label>Owner Team *<input placeholder="sre-platform" value={onboardingForm.owner_team} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, owner_team: e.target.value }))} /></label>
                          <label>Environment<select value={onboardingForm.environment} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, environment: e.target.value }))}><option value="dev">dev</option><option value="staging">staging</option><option value="prod">prod</option></select></label>
                          <label>Region *<input placeholder="ap-south-1" value={onboardingForm.region} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, region: e.target.value }))} /></label>
                        </div>
                        <details className="setup-nested-details">
                          <summary>Advanced Settings (Optional)</summary>
                          <div className="filter-grid" style={{ marginTop: 10 }}>
                            <label>Deployment
                              <select value={onboardingForm.deployment_mode} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, deployment_mode: e.target.value }))}>
                                <option value="on_prem">On-Prem</option>
                                <option value="azure_cloud">Azure Cloud</option>
                              </select>
                            </label>
                            <label>Assign User (optional)<input placeholder="username" value={onboardingForm.assignment_username} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, assignment_username: e.target.value }))} /></label>
                          </div>
                          {onboardingForm.deployment_mode === "azure_cloud" ? (
                            <div className="filter-grid" style={{ marginTop: 10 }}>
                              <label>Azure Subscription ID<input value={onboardingForm.azure_subscription_id} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, azure_subscription_id: e.target.value }))} /></label>
                              <label>Azure Resource Group<input value={onboardingForm.azure_resource_group} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, azure_resource_group: e.target.value }))} /></label>
                              <label>Service Bus Namespace<input value={onboardingForm.azure_service_bus_namespace} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, azure_service_bus_namespace: e.target.value }))} /></label>
                              <label>Service Bus Topic<input value={onboardingForm.azure_service_bus_topic} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, azure_service_bus_topic: e.target.value }))} /></label>
                              <label>Service Bus Subscription<input value={onboardingForm.azure_service_bus_subscription} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, azure_service_bus_subscription: e.target.value }))} /></label>
                            </div>
                          ) : null}
                          {onboardingForm.deployment_mode === "azure_cloud" ? (
                            <div className="filter-grid" style={{ marginTop: 10 }}>
                              <label>Azure Content Safety
                                <select value={String(onboardingForm.azure_content_safety_enabled)} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, azure_content_safety_enabled: e.target.value === "true" }))}>
                                  <option value="false">disabled</option>
                                  <option value="true">enabled</option>
                                </select>
                              </label>
                              <label>Content Safety Endpoint<input value={onboardingForm.azure_content_safety_endpoint} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, azure_content_safety_endpoint: e.target.value }))} /></label>
                            </div>
                          ) : null}
                        </details>
                        </details>
                        <details className="setup-form-section" open>
                          <summary>
                            <span>Monitoring Option</span>
                            <small>Choose one</small>
                          </summary>
                          <div className="panel-head">
                            <h3>Monitoring Option</h3>
                          </div>
                          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            <button
                              type="button"
                              className={onboardingForm.onboarding_path === "setup_monitoring" ? "button-primary" : "button-secondary"}
                              onClick={() => {
                                setOnboardingForm((curr) => ({
                                  ...curr,
                                  onboarding_path: "setup_monitoring",
                                  start_rule_onboarding: true,
                                  monitoring_tool: "prometheus",
                                  prometheus_url: curr.monitoring_url,
                                }));
                                setNewRulePipelineForm((curr) => ({ ...curr, selected_tool: "prometheus" }));
                                setExistingRulePipelineForm((curr) => ({ ...curr, platform: "prometheus" }));
                              }}
                            >
                              Configure Prometheus Rules
                            </button>
                            <button
                              type="button"
                              className={onboardingForm.onboarding_path === "existing_monitoring" ? "button-primary" : "button-secondary"}
                              onClick={() => setOnboardingForm((curr) => ({ ...curr, onboarding_path: "existing_monitoring", start_rule_onboarding: false }))}
                            >
                              Use Existing Monitoring Tool
                            </button>
                          </div>
                          <p className="subtitle" style={{ marginTop: 8 }}>
                            {onboardingForm.onboarding_path === "setup_monitoring"
                              ? "KaiOps will generate Prometheus rules from the Documents & Rules step."
                              : "Keep your current monitoring tool and send alert webhooks to KaiOps landing pad."}
                          </p>
                          <div className="setup-message-bus-preview">
                            <div className="setup-route-strip" aria-label="Landing pad event route">
                              <span>Monitoring Tool</span>
                              <i />
                              <span>Landing Pad</span>
                              <i />
                              <span>Alert Workflow</span>
                              <i />
                              <span>Workers</span>
                            </div>
                            <p className="subtitle">
                              Routing is configured after this setup is saved.
                            </p>
                            <details className="setup-bus-details">
                              <summary>Event Bus Topology</summary>
                              <MessageBusTopology
                                actual={messageBusActual}
                                configuredRows={messageBusTopicRows}
                                routing={observedRouting}
                                primaryTopic={onboardingForm.azure_service_bus_topic || "raw-alerts"}
                                compact
                              />
                            </details>
                          </div>
                        </details>
                        <details className="setup-form-section">
                          <summary>
                            <span>Landing Pad Details</span>
                            <small>Endpoint and sample payload for alert ingestion</small>
                          </summary>
                          <div className="panel-head">
                            <h3>Landing Pad Details</h3>
                            <p>Endpoint and payload guidance for alert ingestion into KaiOps workflow. Troubleshooting runbooks for ingested alerts are managed under Alert Knowledge.</p>
                          </div>
                          <div className="filter-grid">
                            <label>Ingestion Endpoint (UI/Gateway)
                              <input value={onboardingLandingPadDetails.externalIngestionEndpoint} readOnly />
                            </label>
                            <label>Ingestion Endpoint (Container Network)
                              <input value={onboardingLandingPadDetails.internalIngestionEndpoint} readOnly />
                            </label>
                            <label>Method
                              <input value={onboardingLandingPadDetails.method} readOnly />
                            </label>
                            <label>Content Type
                              <input value={onboardingLandingPadDetails.contentType} readOnly />
                            </label>
                            {onboardingForm.onboarding_path === "existing_monitoring" ? (
                              <>
                                <label>Selected Monitoring Tool
                                  <input value={onboardingLandingPadDetails.selectedTool} readOnly />
                                </label>
                                <label>Configured Tool Endpoint
                                  <input value={onboardingLandingPadDetails.configuredEndpoint} readOnly />
                                </label>
                              </>
                            ) : null}
                          </div>
                          <p className="subtitle"><strong>Optional Header:</strong> {onboardingLandingPadDetails.traceHeader}</p>
                          <p className="subtitle"><strong>Required Body:</strong> JSON payload with an alerts array.</p>
                          <p className="subtitle"><strong>Flow Note:</strong> {onboardingLandingPadDetails.routeMessage}</p>
                          {onboardingLandingPadDetails.onboardingPath === "existing_monitoring" ? (
                            <p className="subtitle">Use this endpoint from your monitoring platform webhook to start landing-pad ingestion.</p>
                          ) : (
                            <p className="subtitle">Rule setup path is selected; this endpoint becomes active after rule and monitoring setup are completed.</p>
                          )}
                          <pre className="result">{onboardingLandingPadDetails.samplePayload}</pre>
                        </details>
                        <details className="setup-form-section">
                          <summary>
                            <span>Connection Details</span>
                            <small>Endpoint metadata</small>
                          </summary>
                        <div className="filter-grid">
                          {onboardingForm.onboarding_path === "existing_monitoring" ? (
                            <label>
                              Monitoring Tool
                              <select
                                value={onboardingForm.monitoring_tool}
                                onChange={(e) => {
                                  const nextTool = e.target.value;
                                  setOnboardingForm((curr) => ({
                                    ...curr,
                                    monitoring_tool: nextTool,
                                    prometheus_url: nextTool === "prometheus" ? curr.monitoring_url : "",
                                    new_relic_url: nextTool === "new_relic" ? curr.monitoring_url : "",
                                    datadog_url: nextTool === "datadog" ? curr.monitoring_url : "",
                                  }));
                                  setNewRulePipelineForm((curr) => ({ ...curr, selected_tool: nextTool }));
                                  setExistingRulePipelineForm((curr) => ({ ...curr, platform: nextTool }));
                                }}
                              >
                                <option value="prometheus">Prometheus</option>
                                <option value="new_relic">New Relic</option>
                                <option value="datadog">Datadog</option>
                              </select>
                            </label>
                          ) : (
                            <label>
                              Monitoring Tool
                              <input value="prometheus" readOnly />
                            </label>
                          )}
                          <label>
                            {onboardingForm.onboarding_path === "setup_monitoring" ? "Prometheus Endpoint URL" : "Tool Endpoint URL (optional)"}
                            <input
                              value={onboardingForm.monitoring_url}
                              placeholder="http://prometheus:9090"
                              onBlur={(e) => {
                                const normalized = simplifyMonitoringUrl(e.target.value);
                                setOnboardingForm((curr) => ({
                                  ...curr,
                                  monitoring_url: normalized,
                                  prometheus_url: curr.monitoring_tool === "prometheus" ? normalized : "",
                                  new_relic_url: curr.monitoring_tool === "new_relic" ? normalized : "",
                                  datadog_url: curr.monitoring_tool === "datadog" ? normalized : "",
                                }));
                                setExistingRulePipelineForm((curr) => ({ ...curr, connection_url: normalized }));
                              }}
                              onChange={(e) => setOnboardingForm((curr) => ({ ...curr, monitoring_url: e.target.value }))}
                            />
                            <span className="field-hint">
                              {onboardingForm.onboarding_path === "setup_monitoring"
                                ? "Required for Prometheus rule setup. In Docker Compose, use http://prometheus:9090."
                                : "Optional. If provided, KaiOps stores endpoint metadata for your existing monitoring tool."}
                            </span>
                          </label>
                        </div>
                        {onboardingForm.onboarding_path !== "setup_monitoring" ? (
                          <p className="subtitle">Alerts from your configured monitoring tool can be ingested into landing pad to trigger the remaining workflow.</p>
                        ) : null}
                        </details>
                        <button className="button-primary" type="submit" disabled={onboardingState.loading || onboardingValidationErrors.length > 0 || onboardingHasPendingDocumentApproval}>
                          {onboardingState.loading ? "Saving..." : onboardingProjectMode === "new" ? "Create Monitoring Setup" : "Save Monitoring Setup"}
                        </button>
                      </form>
                      {onboardingState.error ? <p className="error">{onboardingState.error}</p> : null}
                      {onboardingState.success ? <p className="subtitle">{onboardingState.success}</p> : null}
                    </article>
                    ) : null}

                    {showProjectStep("docs_rules") ? (
                    <article className="panel">
                      <div className="panel-head">
                        <div>
                          <h3>Documents & Rules</h3>
                          <p>Add Service Knowledge, improve confidence, then generate reviewable documents and rules.</p>
                        </div>
                        <button type="button" className="button-secondary" onClick={() => setProjectSetupStep("setup")}>Back To Monitoring</button>
                      </div>
                      <form className="form" onSubmit={saveOnboardingConnectivity}>
                        {onboardingValidationErrors.length ? (
                          <div>
                            {onboardingValidationErrors.map((msg, index) => <p key={`docs-rules-error-${index}`} className="error">{msg}</p>)}
                          </div>
                        ) : null}
                        {onboardingHasPendingDocumentApproval ? (
                          <p className="error">Approve pending generated documents before submitting another update.</p>
                        ) : null}
                        <details className="setup-form-section setup-source-doc-panel" open>
                          <summary>
                            <span>Service Knowledge</span>
                            <small>One file, validated details</small>
                          </summary>
                          <div className="panel-head">
                            <div>
                              <h3>Add Service Knowledge</h3>
                              <p>Upload one runbook, ticket export, or notes file. KaiOps extracts the details and asks only for anything missing.</p>
                            </div>
                            <button
                              type="button"
                              className="button-secondary"
                              onClick={applyUploadedDocumentsToRuleIntent}
                              disabled={!onboardingDerivedRequirements.length}
                            >
                              Apply To Rules
                            </button>
                          </div>
                          <div className="setup-flow-rail">
                            <div className={`setup-flow-node ${onboardingSourceDocCount > 0 ? "complete" : "active"}`}>
                              <strong>Add</strong>
                              <span>{onboardingSourceDocCount > 0 ? "File ready" : "Choose one file"}</span>
                            </div>
                            <div className={`setup-flow-node ${onboardingKnowledgePack ? "complete" : ""}`}>
                              <strong>Validate</strong>
                              <span>{onboardingKnowledgePack ? `${Math.round(Number(correctedKnowledgeConfidence || 0) * 100)}% confidence` : "Waiting"}</span>
                            </div>
                            <div className={`setup-flow-node ${knowledgePackState.approved ? "complete" : ""}`}>
                              <strong>Approve</strong>
                              <span>{knowledgePackState.approved ? "Saved to knowledge" : "Review details"}</span>
                            </div>
                          </div>
                          <div className="knowledge-pack-panel">
                            <div className="knowledge-pack-upload">
                              <label className="source-doc-upload-card source-doc-upload-card-wide">
                                <span>Service Knowledge File</span>
                                <input
                                  type="file"
                                  accept=".txt,.md,.markdown,.json,.csv,.log,.yaml,.yml"
                                  onChange={(e) => handleOnboardingSourceDocuments(e.target.files, "knowledge_pack")}
                                />
                                <small>One file is enough. Include alerts, checks, commands, dependencies, and rollback details if available.</small>
                              </label>
                              <div className="knowledge-pack-samples">
                                <a className="source-doc-download" href={ONBOARDING_SOURCE_DOC_SAMPLE_FILES.troubleshooting.href} download>
                                  Download sample file
                                </a>
                              </div>
                            </div>
                            <div className="knowledge-pack-status">
                              <span className={`workflow-pill ${onboardingKnowledgePack?.status === "ready" || knowledgePackState.approved ? "workflow-pill-active" : "workflow-pill-idle"}`}>
                                {knowledgePackState.approved ? "approved" : onboardingKnowledgePack?.status || "waiting"}
                              </span>
                              <strong>{onboardingSourceDocCount > 0 ? "File uploaded" : "No file yet"}</strong>
                              <small>Confidence {Math.round(Number(correctedKnowledgeConfidence || 0) * 100)}%</small>
                            </div>
                          </div>
                          {onboardingSourceDocs.loading ? <p className="subtitle">Reading uploaded file...</p> : null}
                          {onboardingSourceDocs.error ? <p className="error">{onboardingSourceDocs.error}</p> : null}
                          {knowledgePackState.loading ? <p className="subtitle">Validating Service Knowledge...</p> : null}
                          {knowledgePackState.error ? <p className="error">{knowledgePackState.error}</p> : null}
                          {knowledgePackState.success ? <p className="subtitle">{knowledgePackState.success}</p> : null}
                          {onboardingKnowledgePack ? (
                            <div className="knowledge-pack-review">
                              <div className="panel-head">
                                <div>
                                  <h3>Review Extracted Details</h3>
                                  <p>Confirm or fill missing details before KaiOps stores this as trusted Alert Knowledge.</p>
                                </div>
                                <button
                                  type="button"
                                  className="button-primary"
                                  onClick={approveKnowledgePack}
                                  disabled={knowledgePackState.loading || !onboardingSourceDocCount}
                                >
                                  Approve Service Knowledge
                                </button>
                              </div>
                              {knowledgeReviewFields.length ? (
                                <div className="knowledge-pack-fix-panel">
                                  <div>
                                    <strong>Improve confidence</strong>
                                    <span>Add only the missing details you know. KaiOps will mark them as user-confirmed.</span>
                                  </div>
                                  <div className="knowledge-pack-fix-grid">
                                    {knowledgeReviewFields.map(([key, fact]) => (
                                      <label key={`docs-rules-fix-${key}`}>
                                        {KNOWLEDGE_FACT_LABELS[key] || key.replaceAll("_", " ")}
                                        <textarea
                                          rows={KNOWLEDGE_LIST_FACTS.has(key) ? 3 : 2}
                                          placeholder={KNOWLEDGE_FACT_HINTS[key] || "Provide the correct value"}
                                          value={knowledgePackCorrections[key] || ""}
                                          onChange={(event) => setKnowledgePackCorrections((current) => ({
                                            ...current,
                                            [key]: event.target.value,
                                          }))}
                                        />
                                        <small>Current: {Array.isArray(fact?.value) ? fact.value.join(", ") || "-" : String(fact?.value || "-")}</small>
                                      </label>
                                    ))}
                                  </div>
                                </div>
                              ) : (
                                <p className="subtitle">All required details are accepted. You can approve Service Knowledge.</p>
                              )}
                              <div className="table-wrap">
                                <table>
                                  <thead>
                                    <tr><th>Detail</th><th>Value</th><th>Confidence</th><th>Status</th></tr>
                                  </thead>
                                  <tbody>
                                    {Object.entries(correctedKnowledgeFacts).map(([key, fact]) => (
                                      <tr key={`docs-rules-fact-${key}`}>
                                        <td>{key.replaceAll("_", " ")}</td>
                                        <td>{Array.isArray(fact?.value) ? fact.value.join(" | ") || "-" : String(fact?.value || "-")}</td>
                                        <td>{Math.round(Number(fact?.confidence || 0) * 100)}%</td>
                                        <td>{String(fact?.status || "needs_review").replaceAll("_", " ")}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          ) : null}
                        </details>
                        <details className={`setup-form-section rule-prompt-panel ${onboardingRulePromptVisible ? "ready" : "locked"}`} open={onboardingRulePromptVisible}>
                          <summary>
                            <span>Rules</span>
                            <small>{onboardingRulePromptVisible ? "Review and edit before generating" : "Upload Service Knowledge or type rule intent"}</small>
                          </summary>
                          <div className="panel-head">
                            <div>
                              <h3>Rule Intent</h3>
                              <p>Use extracted hints or type plain-English rules. Setup Monitoring path will generate Prometheus rules.</p>
                            </div>
                            <span className={`workflow-pill ${onboardingRulePromptVisible ? "workflow-pill-active" : "workflow-pill-idle"}`}>
                              {onboardingRulePromptVisible ? "ready" : "optional"}
                            </span>
                          </div>
                          {onboardingRulePromptLines.length ? (
                            <div className="generated-rule-preview">
                              {onboardingRulePromptLines.slice(0, 4).map((line, index) => (
                                <span key={`docs-rules-prompt-line-${index}`}>{line}</span>
                              ))}
                            </div>
                          ) : null}
                          <label>
                            Rule Intent
                            <textarea
                              rows={5}
                              placeholder="Example: Alert when mysql exporter is down for 5 minutes."
                              value={onboardingForm.rule_onboarding_plain_language}
                              onChange={(e) => {
                                const nextText = e.target.value;
                                setOnboardingForm((curr) => ({ ...curr, rule_onboarding_plain_language: nextText }));
                                setNewRulePipelineForm((curr) => ({ ...curr, requirements_text: nextText }));
                              }}
                            />
                          </label>
                        </details>
                        <button className="button-primary" type="submit" disabled={onboardingState.loading || onboardingValidationErrors.length > 0 || onboardingHasPendingDocumentApproval}>
                          {onboardingState.loading ? "Generating..." : "Generate Documents & Rules"}
                        </button>
                      </form>
                      {onboardingState.error ? <p className="error">{onboardingState.error}</p> : null}
                      {onboardingState.success ? <p className="subtitle">{onboardingState.success}</p> : null}
                    </article>
                    ) : null}

                    {(showProjectStep("review") || (adminWorkspace === "project" && projectSetupStep === "docs_rules" && onboardingGeneratedDocs.length > 0)) ? (
                    <article className="panel onboarding-review-panel">
                      <div className="panel-head">
                        <h3>Generated Rules, Docs, and Metadata Review (Required)</h3>
                        <div style={{ display: "flex", gap: 8 }}>
                          <button
                            type="button"
                            className="button-secondary"
                            onClick={() => {
                              setOnboardingGeneratedDocs([]);
                              setOnboardingDocApprovalState({ loading: false, error: "", success: "", approved: false });
                            }}
                            disabled={!onboardingGeneratedDocs.length || onboardingDocApprovalState.loading}
                          >
                            Clear
                          </button>
                          <button
                            type="button"
                            className="button-primary"
                            onClick={approveGeneratedOnboardingDocuments}
                            disabled={!onboardingGeneratedDocs.length || onboardingDocApprovalState.loading || onboardingDocApprovalState.approved || !onboardingReviewGate.allReviewed}
                          >
                            {onboardingDocApprovalState.loading ? "Approving..." : onboardingDocApprovalState.approved ? "Approved" : "Approve Documents"}
                          </button>
                        </div>
                      </div>
                      <p className="subtitle">After Create/Update Project: review generated artifacts, confirm each checklist item, then click Approve Documents.</p>
                      <div className="filter-grid onboarding-review-checklist" style={{ marginBottom: 8 }}>
                        <label>
                          <input
                            type="checkbox"
                            checked={onboardingReviewAck.rules}
                            onChange={(e) => setOnboardingReviewAck((current) => ({ ...current, rules: e.target.checked }))}
                            disabled={!onboardingGeneratedRuleRows.length}
                          />
                          I reviewed generated rules
                        </label>
                        <label>
                          <input
                            type="checkbox"
                            checked={onboardingReviewAck.docs}
                            onChange={(e) => setOnboardingReviewAck((current) => ({ ...current, docs: e.target.checked }))}
                            disabled={!onboardingGeneratedDocs.length}
                          />
                          I reviewed generated docs
                        </label>
                        <label>
                          <input
                            type="checkbox"
                            checked={onboardingReviewAck.metadata}
                            onChange={(e) => setOnboardingReviewAck((current) => ({ ...current, metadata: e.target.checked }))}
                            disabled={!onboardingMetadataRows.length}
                          />
                          I reviewed generated metadata
                        </label>
                      </div>
                      {!onboardingReviewGate.allReviewed ? <p className="subtitle onboarding-review-warning">Approval is locked until all available review checkboxes are confirmed.</p> : null}
                      {onboardingDocApprovalState.error ? <p className="error">{onboardingDocApprovalState.error}</p> : null}
                      {onboardingDocApprovalState.success ? <p className="subtitle">{onboardingDocApprovalState.success}</p> : null}
                      {!onboardingGeneratedDocs.length ? (
                        <p className="subtitle">No documents pending review.</p>
                      ) : (
                        <div className="table-wrap">
                          <table>
                            <thead>
                              <tr>
                                <th>Kind</th>
                                <th>Title</th>
                                <th>Summary</th>
                              </tr>
                            </thead>
                            <tbody>
                              {onboardingGeneratedDocs.map((doc, index) => (
                                <tr key={`onboarding-doc-${index}`}>
                                  <td>{String(doc?.kind || "-")}</td>
                                  <td>{String(doc?.title || "-")}</td>
                                  <td>{String(doc?.summary || "-")}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {onboardingGeneratedDocs.length ? (
                        <details style={{ marginTop: 12 }}>
                          <summary style={{ cursor: "pointer" }}>View Full Documents JSON</summary>
                          <pre className="result">{JSON.stringify(onboardingGeneratedDocs, null, 2)}</pre>
                        </details>
                      ) : null}
                      <details className="onboarding-review-details" style={{ marginTop: 12 }}>
                        <summary style={{ cursor: "pointer" }}>Generated Rules Review ({onboardingGeneratedRuleRows.length})</summary>
                        <div className="table-wrap" style={{ marginTop: 8 }}>
                          <table>
                            <thead>
                              <tr>
                                <th>Name</th>
                                <th>Platform</th>
                                <th>Adapter</th>
                                <th>Severity</th>
                                <th>Status</th>
                                <th>Expression / Query</th>
                              </tr>
                            </thead>
                            <tbody>
                              {onboardingGeneratedRuleRows.map((row) => (
                                <tr key={`generated-rule-${row.id}`}>
                                  <td>{row.name}</td>
                                  <td>{row.platform}</td>
                                  <td>{row.contractMode !== "-" ? `${row.contractMode} / ${row.contractStatus}` : "-"}</td>
                                  <td>{row.severity}</td>
                                  <td>{row.status}</td>
                                  <td>{row.expression || "-"}</td>
                                </tr>
                              ))}
                              {!onboardingGeneratedRuleRows.length ? <tr><td colSpan={6}>No generated rule rows found in latest workflow payload.</td></tr> : null}
                            </tbody>
                          </table>
                        </div>
                      </details>
                      <details className="onboarding-review-details" style={{ marginTop: 12 }}>
                        <summary style={{ cursor: "pointer" }}>Generated Metadata Review ({onboardingMetadataRows.length})</summary>
                        <div className="table-wrap" style={{ marginTop: 8 }}>
                          <table>
                            <thead>
                              <tr>
                                <th>Provider</th>
                                <th>Project</th>
                                <th>Status</th>
                                <th>Updated</th>
                              </tr>
                            </thead>
                            <tbody>
                              {onboardingMetadataRows.map((row) => (
                                <tr key={`generated-meta-${row.id}`}>
                                  <td>{row.provider}</td>
                                  <td>{row.project}</td>
                                  <td>{row.status}</td>
                                  <td>{row.updated_at}</td>
                                </tr>
                              ))}
                              {!onboardingMetadataRows.length ? <tr><td colSpan={4}>No metadata rows found for selected project yet.</td></tr> : null}
                            </tbody>
                          </table>
                        </div>
                      </details>
                      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
                        <button type="button" className="button-secondary" onClick={() => setProjectSetupStep("status")}>Next: Workflow Status</button>
                      </div>
                    </article>
                    ) : null}

                    {showProjectStep("status") ? (
                    <article className="panel">
                      <h3>Rule Onboarding Status</h3>
                      <p className="subtitle">Rule onboarding is optional. If enabled above, plain-language requirements are converted into tool-specific rules and documentation automatically.</p>
                      {onboardingDocApprovalState.approved || knowledgePackState.approved || onboardingWorkflowSteps.length > 0 ? (
                        <div className="setup-complete-panel">
                          <div>
                            <span className="workflow-pill workflow-pill-active">ready</span>
                            <h3>{currentOnboardedApplicationName() || "Application"} setup is ready</h3>
                            <p>
                              Monitoring setup, Service Knowledge, generated rules, and approved documents are now connected to the selected application workspace.
                            </p>
                          </div>
                          <div className="setup-complete-actions">
                            <button type="button" className="button-primary" onClick={() => openOnboardedApplicationDashboard()}>
                              Open Application Dashboard
                            </button>
                            <button type="button" className="button-secondary" onClick={() => setProjectSetupStep("docs_rules")}>
                              Back To Documents & Rules
                            </button>
                          </div>
                        </div>
                      ) : null}
                      <h3>Step-by-Step Workflow Progress</h3>
                      <div className="monitoring-dashboard-cards">
                        {monitoringAppDetails.dashboards.map((row, index) => (
                          <article className="monitoring-dashboard-card" key={`monitoring-dashboard-card-${row.id || index}`}>
                            <span>Generated Dashboard</span>
                            <strong>{row.title || row.dashboard_uid || "Dashboard"}</strong>
                            <small>UID: {row.dashboard_uid || "-"}</small>
                            <small>Updated: {row.updated_at || "-"}</small>
                            {row.url ? (
                              <button type="button" className="button-secondary" onClick={() => openOnboardedApplicationDashboard(row.url)}>Open Dashboard</button>
                            ) : (
                              <button type="button" className="button-secondary" onClick={() => openOnboardedApplicationDashboard()}>Open Dashboard</button>
                            )}
                          </article>
                        ))}
                        {!monitoringAppDetails.dashboards.length ? (
                          <article className="monitoring-dashboard-card empty">
                            <span>Dashboard Status</span>
                            <strong>No dashboards generated yet</strong>
                            <small>Register an application and validate metrics to generate dashboard references.</small>
                            <button type="button" className="button-secondary" onClick={() => openOnboardedApplicationDashboard()}>Open Application Dashboard</button>
                          </article>
                        ) : null}
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Step</th>
                              <th>Status</th>
                              <th>What Happened</th>
                              <th>Background</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(() => {
                              const isSetupMonitoring = String(onboardingForm.onboarding_path || "existing_monitoring").trim() === "setup_monitoring";
                              const rows = onboardingWorkflowSteps.length ? onboardingWorkflowSteps : (
                                isSetupMonitoring
                                  ? [
                                    { step: 1, title: "Create/Update Project", status: "pending", details: { message: "Start by creating or updating a project." } },
                                    { step: 2, title: "Select Onboarding Path", status: "pending", details: { message: "Choose Setup Monitoring." } },
                                    { step: 3, title: "Capture Rules In Plain English", status: "pending", details: { message: "Provide plain-English rule intent." } },
                                    { step: 4, title: "Convert To YAML, Upload In Prometheus, Test", status: "pending", details: { message: "System will convert, attempt upload/reload, and test." } },
                                    { step: 5, title: "Generate Monitoring/Troubleshooting/Resolution Docs", status: "pending", details: { message: "System will generate documentation payloads." } },
                                  ]
                                  : [
                                    { step: 1, title: "Create/Update Project", status: "pending", details: { message: "Start by creating or updating a project." } },
                                    { step: 2, title: "Select Onboarding Path", status: "pending", details: { message: "Choose Existing Monitoring." } },
                                    { step: 3, title: "Configure Landing Pad Ingestion", status: "pending", details: { message: "Connect your monitoring tool and route alerts to landing pad." } },
                                    { step: 4, title: "Ingest Alerts and Trigger Workflow", status: "pending", details: { message: "Incoming alerts will trigger downstream workflow stages." } },
                                    { step: 5, title: "Generate Monitoring/Troubleshooting/Resolution Docs", status: "pending", details: { message: "Optional generated docs can be reviewed and approved." } },
                                  ]
                              );
                              return rows.map((row) => {
                                const message = row?.details?.message
                                  || row?.details?.summary
                                  || row?.details?.choice
                                  || row?.details?.path
                                  || row?.details?.workflow_id
                                  || `Requirements: ${Number(row?.details?.requirements_count || 0)}`;
                                return (
                                  <tr key={`workflow-step-${row.step}-${row.title}`}>
                                    <td>{row.step}. {row.title}</td>
                                    <td>{row.status || "pending"}</td>
                                    <td>{String(message || "-")}</td>
                                    <td>
                                      <details>
                                        <summary>How This Worked In Background</summary>
                                        <pre className="result">{explainOnboardingStepBackground(row.step, isSetupMonitoring)}</pre>
                                      </details>
                                    </td>
                                  </tr>
                                );
                              });
                            })()}
                          </tbody>
                        </table>
                      </div>
                      <div className="filter-grid">
                        <label>
                          Current Project
                          <input value={onboardingForm.name} readOnly />
                        </label>
                        <label>
                          Monitoring Tool
                          <input value={onboardingForm.monitoring_tool} readOnly />
                        </label>
                        <label>
                          Last Workflow ID
                          <input value={String(onboardingRuleLookup.workflow_id || onboardingRuleRunState?.result?.workflow_id || "").trim()} readOnly />
                        </label>
                      </div>
                      {onboardingRuleRunState.error ? <p className="error">{onboardingRuleRunState.error}</p> : null}
                      {onboardingRuleRunState.result?.knowledge_documents?.length ? (
                        <div className="table-wrap">
                          <h4>Documents Saved To System</h4>
                          <p className="subtitle">For transparency: every knowledge document persisted by this run, with its metadata.</p>
                          <table>
                            <thead>
                              <tr>
                                <th>Title</th>
                                <th>Project</th>
                                <th>Platform</th>
                                <th>Owner</th>
                                <th>Created</th>
                                <th>Document ID</th>
                              </tr>
                            </thead>
                            <tbody>
                              {onboardingRuleRunState.result.knowledge_documents.map((doc) => (
                                <tr key={doc.document_id || doc.title}>
                                  <td>{doc.title || "-"}</td>
                                  <td>{doc.project || "-"}</td>
                                  <td>{doc.platform || "-"}</td>
                                  <td>{doc.owner || "-"}</td>
                                  <td>{doc.created_at || "-"}</td>
                                  <td>{doc.document_id || "-"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : null}
                      {onboardingRuleRunState.result ? <pre className="result">{JSON.stringify(onboardingRuleRunState.result, null, 2)}</pre> : null}
                      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
                        <button type="button" className="button-secondary" onClick={() => setProjectSetupStep("advanced")}>Next: Advanced Tools</button>
                      </div>
                    </article>
                    ) : null}

                    {showProjectStep("advanced") ? (
                    <article className="panel">
                      <h3>Advanced Rule Workflow Management</h3>
                      <details>
                        <summary style={{ cursor: "pointer", marginBottom: 12 }}>Open Advanced Tools</summary>

                        <form className="form" onSubmit={lookupOnboardingRuleWorkflow}>
                          <div className="filter-grid">
                            <label>
                              Workflow ID
                              <input
                                value={onboardingRuleLookup.workflow_id}
                                placeholder="Paste workflow id"
                                onChange={(e) => setOnboardingRuleLookup((curr) => ({ ...curr, workflow_id: e.target.value }))}
                              />
                            </label>
                          </div>
                          <button className="button-secondary" type="submit" disabled={onboardingRuleLookup.loading}>
                            {onboardingRuleLookup.loading ? "Fetching..." : "Lookup Workflow"}
                          </button>
                        </form>
                        {onboardingRuleLookup.error ? <p className="error">{onboardingRuleLookup.error}</p> : null}
                        {onboardingRuleLookup.result ? <pre className="result">{JSON.stringify(onboardingRuleLookup.result, null, 2)}</pre> : null}
                            disabled={!onboardingGeneratedDocs.length || onboardingDocApprovalState.loading || onboardingDocApprovalState.approved || !onboardingReviewGate.allReviewed}
                        <div className="table-wrap" style={{ marginTop: 12 }}>
                          <table>
                            <thead>
                              <tr>
                                <th>Project</th>
                                <th>Pipeline</th>
                                <th>Workflow ID</th>
                                <th>Status</th>
                                <th>Updated</th>
                                <th>Action</th>
                              </tr>
                            </thead>
                            <tbody>
                              {ruleOnboardingRows.slice(0, 100).map((row, index) => {
                                const payload = row.connectivity_payload && typeof row.connectivity_payload === "object" ? row.connectivity_payload : {};
                                const workflowId = String(payload.workflow_id || "").trim();
                                return (
                                  <tr key={`rule-workflow-row-${index}`}>
                                    <td>{row.project_name || "-"}</td>
                                    <td>{row.provider_name || payload.pipeline || "-"}</td>
                                    <td>{workflowId || "-"}</td>
                                    <td>{payload.status || row.test_status || "-"}</td>
                                    <td>{row.updated_at || row.created_at || "-"}</td>
                                    <td>
                                      <div style={{ display: "flex", gap: 8 }}>
                                        <button type="button" className="button-secondary" onClick={() => openRuleWorkflowEditor(row)} disabled={!workflowId}>
                                          Edit
                                        </button>
                                        <button type="button" className="button-secondary" onClick={() => deleteRuleWorkflow(workflowId)} disabled={!workflowId || onboardingRuleEditorState.loading}>
                                          Delete
                                        </button>
                                      </div>
                                    </td>
                                  </tr>
                                );
                              })}
                              {!ruleOnboardingRows.length ? (
                                <tr>
                                  <td colSpan={6}>No saved rule workflows available.</td>
                                </tr>
                              ) : null}
                            </tbody>
                          </table>
                        </div>

                        <h3>Edit Rule Workflow Result</h3>
                        <form className="form" onSubmit={saveRuleWorkflowEditor}>
                          <div className="filter-grid">
                            <label>
                              Workflow ID
                              <input
                                value={onboardingRuleEditor.workflow_id}
                                onChange={(e) => setOnboardingRuleEditor((current) => ({ ...current, workflow_id: e.target.value }))}
                                placeholder="Workflow ID"
                              />
                            </label>
                            <label>
                              Project Name
                              <input
                                value={onboardingRuleEditor.project_name}
                                onChange={(e) => setOnboardingRuleEditor((current) => ({ ...current, project_name: e.target.value }))}
                                placeholder="Project name"
                              />
                            </label>
                          </div>
                          <label>
                            Workflow Result JSON
                            <textarea
                              rows={10}
                              value={onboardingRuleEditor.payload_json}
                              onChange={(e) => setOnboardingRuleEditor((current) => ({ ...current, payload_json: e.target.value }))}
                              placeholder="Paste workflow result JSON"
                            />
                          </label>
                          <button className="button-primary" type="submit" disabled={onboardingRuleEditorState.loading}>
                            {onboardingRuleEditorState.loading ? "Saving..." : "Save Workflow Changes"}
                          </button>
                        </form>
                        {onboardingRuleEditorState.error ? <p className="error">{onboardingRuleEditorState.error}</p> : null}
                        {onboardingRuleEditorState.success ? <p className="subtitle">{onboardingRuleEditorState.success}</p> : null}

                        <div className="panel-head" style={{ marginTop: 12 }}>
                          <h3>Monitoring Platform Capabilities</h3>
                          <button type="button" className="button-secondary" onClick={loadOnboardingRuleCapabilities}>
                            Refresh
                          </button>
                        </div>
                        {onboardingRuleCapabilities.error ? <p className="error">{onboardingRuleCapabilities.error}</p> : null}
                        <div className="table-wrap">
                          <table>
                            <thead>
                              <tr>
                                <th>Platform</th>
                                <th>Pull Rules</th>
                                <th>Push Rules</th>
                                <th>Adapter</th>
                                <th>Simulation</th>
                                <th>Dashboards</th>
                              </tr>
                            </thead>
                            <tbody>
                              {onboardingRuleCapabilities.rows.map((row, index) => (
                                <tr key={`capability-${row.platform || index}`}>
                                  <td>{row.platform || "-"}</td>
                                  <td>{String(Boolean(row.can_pull_rules))}</td>
                                  <td>{String(Boolean(row.can_push_rules))}</td>
                                  <td title={row.contract_label || ""}>{row.contract_mode || "-"} / {row.contract_status || "-"}</td>
                                  <td>{String(Boolean(row.supports_simulation))}</td>
                                  <td>{String(Boolean(row.supports_dashboard_refs))}</td>
                                </tr>
                              ))}
                              {!onboardingRuleCapabilities.rows.length && !onboardingRuleCapabilities.loading ? (
                                <tr>
                                  <td colSpan={6}>No capabilities loaded yet.</td>
                                </tr>
                              ) : null}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    </article>
                    ) : null}
                  </div>

                ) : null}

                {adminWorkspace === "monitoring" ? (
                  <div className="grid single-col admin-flow-section admin-flow-monitoring">
                    <article className="panel">
                      <div className="panel-head">
                        <h3>Setup Monitoring</h3>
                        <button className="button-secondary" type="button" onClick={loadMonitoringApplications} disabled={monitoringApps.loading}>Refresh</button>
                      </div>
                      <p className="subtitle">Start here. Register an application and inspect the end-to-end onboarding chain (discovery, validation, rules, Prometheus update, dashboard).</p>
                      <p className="subtitle"><strong>Alert Knowledge:</strong> Included in Setup Monitoring + Landing Pad. Use the unified setup tab for one continuous workflow.</p>
                      <form className="form" onSubmit={submitMonitoringApplication}>
                        <div className="filter-grid">
                          <label>Tenant<input value={monitoringAppForm.tenant_id} onChange={(e) => setMonitoringAppForm((curr) => ({ ...curr, tenant_id: e.target.value }))} /></label>
                          <label>Application Name<input value={monitoringAppForm.name} onChange={(e) => setMonitoringAppForm((curr) => ({ ...curr, name: e.target.value }))} /></label>
                          <label>Owner Team<input value={monitoringAppForm.owner_team} onChange={(e) => setMonitoringAppForm((curr) => ({ ...curr, owner_team: e.target.value }))} /></label>
                          <label>Owner Email<input value={monitoringAppForm.owner_email} onChange={(e) => setMonitoringAppForm((curr) => ({ ...curr, owner_email: e.target.value }))} /></label>
                        </div>
                        <div className="filter-grid">
                          <label>Environment<select value={monitoringAppForm.environment} onChange={(e) => setMonitoringAppForm((curr) => ({ ...curr, environment: e.target.value }))}><option value="dev">dev</option><option value="staging">staging</option><option value="prod">prod</option></select></label>
                          <label>Namespace<input value={monitoringAppForm.namespace} onChange={(e) => setMonitoringAppForm((curr) => ({ ...curr, namespace: e.target.value }))} /></label>
                          <label>Region<input value={monitoringAppForm.region} onChange={(e) => setMonitoringAppForm((curr) => ({ ...curr, region: e.target.value }))} /></label>
                          <label>Technology<input value={monitoringAppForm.technology} onChange={(e) => setMonitoringAppForm((curr) => ({ ...curr, technology: e.target.value }))} /></label>
                        </div>
                        <label>Metrics Endpoint<input placeholder="http://api-gateway:8000/metrics" value={monitoringAppForm.metrics_endpoint} onChange={(e) => setMonitoringAppForm((curr) => ({ ...curr, metrics_endpoint: e.target.value }))} /></label>
                        <label>Labels (comma-separated key=value)<input value={monitoringAppForm.labels_text} onChange={(e) => setMonitoringAppForm((curr) => ({ ...curr, labels_text: e.target.value }))} /></label>
                        <button className="button-primary" type="submit" disabled={monitoringAppSubmit.loading}>{monitoringAppSubmit.loading ? "Submitting..." : "Register Application"}</button>
                      </form>
                      {monitoringAppSubmit.error ? <p className="error">{monitoringAppSubmit.error}</p> : null}
                      {monitoringAppSubmit.success ? <p className="subtitle">{monitoringAppSubmit.success}</p> : null}
                      <article className="panel monitoring-doc-gate" style={{ marginTop: 10, borderStyle: "dashed" }}>
                        <div className="panel-head">
                          <h3>Service Knowledge Status</h3>
                          <button type="button" className="button-secondary" onClick={applyUploadedDocumentsToRuleIntent} disabled={!onboardingDerivedRequirements.length}>Apply To Rules</button>
                        </div>
                        <p className="subtitle">Use the Service Knowledge upload above. KaiOps extracts and validates the important details in one flow.</p>
                        <div className="approval-steps" style={{ marginTop: 10 }}>
                          <div className="approval-step">
                            <strong>Extract</strong>
                            <span>Service, owner, environment, dependencies, alerts, commands, rollback, and validation checks.</span>
                          </div>
                          <div className="approval-step">
                            <strong>Validate</strong>
                            <span>Flags missing or low-confidence fields before the details are trusted.</span>
                          </div>
                          <div className="approval-step">
                            <strong>Approve</strong>
                            <span>Stores the reviewed pack in Alert Knowledge for RAG and future incidents.</span>
                          </div>
                        </div>
                        {onboardingSourceDocs.loading ? <p className="subtitle">Reading uploaded file...</p> : null}
                        {onboardingSourceDocs.error ? <p className="error">{onboardingSourceDocs.error}</p> : null}
                        <p className="subtitle monitoring-doc-gate-count">
                          Uploaded file: <strong>{onboardingSourceDocCount > 0 ? "yes" : "no"}</strong> | Service Knowledge: <strong>{knowledgePackState.approved ? "approved" : onboardingKnowledgePack?.status || "waiting"}</strong>
                        </p>
                      </article>
                    </article>

                    <article className="panel">
                      <h3>Applications</h3>
                      {monitoringApps.error ? <p className="error">{monitoringApps.error}</p> : null}
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr><th>Name</th><th>Tenant</th><th>Namespace</th><th>Environment</th><th>Technology</th><th>Status</th><th>Metrics Endpoint</th><th>Action</th></tr>
                          </thead>
                          <tbody>
                            {monitoringApps.rows.map((row, index) => (
                              <tr key={`monitoring-app-${row.id || index}`}>
                                <td>{row.name || "-"}</td>
                                <td>{row.tenant_id || "default"}</td>
                                <td>{row.namespace || "-"}</td>
                                <td>{row.environment || "-"}</td>
                                <td>{row.technology || "-"}</td>
                                <td><span className={`pill ${String(row.status || "").includes("failed") ? "status-failed" : "status-closed"}`}>{row.status || "-"}</span></td>
                                <td>{row.metrics_endpoint || "-"}</td>
                                <td><button type="button" className="button-secondary" onClick={() => setSelectedMonitoringAppId(String(row.id || ""))}>Inspect</button></td>
                              </tr>
                            ))}
                            {!monitoringApps.rows.length ? <tr><td colSpan={8}>No monitoring applications registered yet.</td></tr> : null}
                          </tbody>
                        </table>
                      </div>
                    </article>

                    <article className="panel" ref={monitoringInspectRef}>
                      <div className="panel-head">
                        <h3>Selected Application Timeline</h3>
                        <p className="subtitle">{selectedMonitoringAppId || "Select an application to inspect stage history, validations, and dashboards."}</p>
                      </div>
                      {monitoringAppDetails.error ? <p className="error">{monitoringAppDetails.error}</p> : null}
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr><th>Event</th><th>Agent</th><th>Decision</th><th>Status</th><th>Execution (ms)</th><th>Timestamp</th></tr>
                          </thead>
                          <tbody>
                            {monitoringAppDetails.history.map((row, index) => (
                              <tr key={`monitoring-history-${row.id || index}`}>
                                <td>{row.event_type || "-"}</td>
                                <td>{row.agent || "-"}</td>
                                <td>{row.decision || "-"}</td>
                                <td>{row.status || "-"}</td>
                                <td>{asDisplayValue(row.execution_time_ms)}</td>
                                <td>{row.created_at || "-"}</td>
                              </tr>
                            ))}
                            {!monitoringAppDetails.history.length ? <tr><td colSpan={6}>No stage history available yet.</td></tr> : null}
                          </tbody>
                        </table>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr><th>Target Up</th><th>Metrics</th><th>Alerts Loaded</th><th>Recording Rules</th><th>Service Discovery</th><th>Timestamp</th></tr>
                          </thead>
                          <tbody>
                            {monitoringAppDetails.validations.map((row, index) => (
                              <tr key={`monitoring-validation-${row.id || index}`}>
                                <td>{String(Boolean(row.target_up))}</td>
                                <td>{String(Boolean(row.metrics_available))}</td>
                                <td>{String(Boolean(row.alerts_loaded))}</td>
                                <td>{String(Boolean(row.recording_rules_loaded))}</td>
                                <td>{String(Boolean(row.service_discovery_ok))}</td>
                                <td>{row.created_at || "-"}</td>
                              </tr>
                            ))}
                            {!monitoringAppDetails.validations.length ? <tr><td colSpan={6}>No validation records available yet.</td></tr> : null}
                          </tbody>
                        </table>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr><th>Dashboard UID</th><th>Title</th><th>URL</th><th>Updated</th></tr>
                          </thead>
                          <tbody>
                            {monitoringAppDetails.dashboards.map((row, index) => (
                              <tr key={`monitoring-dashboard-${row.id || index}`}>
                                <td>{row.dashboard_uid || "-"}</td>
                                <td>{row.title || "-"}</td>
                                <td>{row.url || "-"}</td>
                                <td>{row.updated_at || "-"}</td>
                              </tr>
                            ))}
                            {!monitoringAppDetails.dashboards.length ? <tr><td colSpan={4}>No dashboards generated yet.</td></tr> : null}
                          </tbody>
                        </table>
                      </div>
                    </article>
                  </div>
                ) : null}

                {(adminWorkspace === "alerts" || (adminWorkspace === "project" && showProjectStep("knowledge"))) ? (
                  <div className="grid single-col admin-flow-section admin-flow-knowledge">
                    <article className="panel">
                      <div className="panel-head">
                        <h3>{adminWorkspace === "project" ? "Knowledge: Alert Documents" : "Alert Knowledge Onboarding"}</h3>
                        <p>{adminWorkspace === "project" ? "Create and review alert knowledge here in the same setup workspace." : "Standalone alert knowledge workspace for focused onboarding and review."}</p>
                      </div>
                      <div className="detail-tabs" style={{ marginBottom: 0 }}>
                        <button
                          type="button"
                          className={alertKnowledgeView === "onboarding" ? "button-primary" : "button-secondary"}
                          onClick={() => setAlertKnowledgeView("onboarding")}
                        >
                          Guided Onboarding
                        </button>
                        <button
                          type="button"
                          className={alertKnowledgeView === "backend" ? "button-primary" : "button-secondary"}
                          onClick={() => setAlertKnowledgeView("backend")}
                        >
                          Stored Docs & Metadata
                        </button>
                      </div>
                    </article>

                    {alertKnowledgeView === "onboarding" ? (
                    <article className="panel" ref={alertKnowledgeRef}>
                      <h3>Alert Knowledge Onboarding</h3>
                      <p className="subtitle">Add monitoring/troubleshooting knowledge as part of the same onboarding flow.</p>
                      <form className="form" onSubmit={submitAlertOnboarding}>
                        <label>
                          Prompt For Document Generation
                          <textarea
                            rows={4}
                            placeholder="Describe the alert scenario, triage steps, impact, and expected remediation. Optional prefixes: cmd:, script:, query:."
                            value={alertKnowledgePrompt}
                            onChange={(e) => setAlertKnowledgePrompt(e.target.value)}
                          />
                        </label>
                        <div className="alert-knowledge-source">
                          <label>
                            Supporting Document
                            <input
                              type="file"
                              accept=".md,.markdown,.txt,.json,.csv,.yaml,.yml,.log"
                              onChange={(e) => handleAlertKnowledgeSourceDocument(e.target.files)}
                            />
                          </label>
                          <div className="alert-knowledge-source-status">
                            {alertKnowledgeSourceDoc.loading ? <span>Reading document...</span> : null}
                            {alertKnowledgeSourceDoc.error ? <span className="error">{alertKnowledgeSourceDoc.error}</span> : null}
                            {alertKnowledgeSourceDoc.name && !alertKnowledgeSourceDoc.error ? (
                              <>
                                <div>
                                  <strong>{alertKnowledgeSourceDoc.name}</strong>
                                  <small>{alertKnowledgeSourceDoc.size ? `${Math.ceil(alertKnowledgeSourceDoc.size / 1024)} KB` : "uploaded"}</small>
                                </div>
                                {alertKnowledgeSourceDoc.excerpt ? <p>{alertKnowledgeSourceDoc.excerpt}</p> : null}
                                <button type="button" className="button-secondary" onClick={clearAlertKnowledgeSourceDocument}>
                                  Clear Document
                                </button>
                              </>
                            ) : !alertKnowledgeSourceDoc.loading && !alertKnowledgeSourceDoc.error ? (
                              <span>Upload runbook, RCA, logs, support notes, or troubleshooting docs. The draft uses this together with the prompt.</span>
                            ) : null}
                          </div>
                        </div>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                          <button
                            type="button"
                            className="button-secondary"
                            onClick={generateAlertKnowledgeDraftFromPrompt}
                            disabled={alertOnboardingState.loading}
                          >
                            Generate Draft From Prompt + Document
                          </button>
                        </div>
                        <div className="detail-tabs" style={{ marginBottom: 10 }}>
                          {ALERT_DOC_KIND_OPTIONS.map((kind) => (
                            <button
                              key={`onboard-kind-${kind}`}
                              type="button"
                              className={String(alertOnboarding.kind || "").trim().toLowerCase() === kind ? "button-primary" : "button-secondary"}
                              onClick={() => setAlertOnboarding((curr) => ({ ...curr, kind }))}
                            >
                              {kind}
                            </button>
                          ))}
                        </div>
                        <div className="filter-grid">
                          <label>Kind
                            <select value={alertOnboarding.kind} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, kind: e.target.value }))}>
                              <option value="incident">incident</option>
                              <option value="runbook">runbook</option>
                              <option value="deployment">deployment</option>
                              <option value="change">change</option>
                              <option value="dependency">dependency</option>
                              <option value="remediation">remediation</option>
                            </select>
                          </label>
                          <label>Title<input value={alertOnboarding.title} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, title: e.target.value }))} /></label>
                          <label>Alert Type<input value={alertOnboarding.alert_type} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, alert_type: e.target.value }))} /></label>
                          <label>Severity<select value={alertOnboarding.severity} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, severity: e.target.value }))}><option value="critical">critical</option><option value="high">high</option><option value="medium">medium</option><option value="low">low</option></select></label>
                        </div>
                        <label>Services (comma separated)<input value={alertOnboarding.services} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, services: e.target.value }))} /></label>
                        <label>Summary<textarea rows={2} value={alertOnboarding.summary} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, summary: e.target.value }))} /></label>
                        <label>Content<textarea rows={5} value={alertOnboarding.content} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, content: e.target.value }))} /></label>
                        {String(alertOnboarding.kind || "").trim().toLowerCase() === "remediation" ? (
                          <>
                            <div style={{ display: "flex", alignItems: "end", gap: 8 }}>
                              <button
                                type="button"
                                className="button-secondary"
                                onClick={() => autoGenerateRemediationPlan()}
                                disabled={alertOnboardingState.loading}
                              >
                                Auto-Generate Commands/Scripts/Queries
                              </button>
                            </div>
                            <label>Execution Plan<textarea rows={4} value={alertOnboarding.execution_plan} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, execution_plan: e.target.value }))} /></label>
                            <div className="filter-grid">
                              <label>Remediation Commands (one per line)<textarea rows={5} value={alertOnboarding.remediation_commands_text} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, remediation_commands_text: e.target.value }))} /></label>
                              <label>Remediation Scripts (one per line)<textarea rows={5} value={alertOnboarding.remediation_scripts_text} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, remediation_scripts_text: e.target.value }))} /></label>
                              <label>Validation Queries (one per line)<textarea rows={5} value={alertOnboarding.remediation_queries_text} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, remediation_queries_text: e.target.value }))} /></label>
                            </div>
                          </>
                        ) : null}
                        <button className="button-primary" type="submit" disabled={alertOnboardingState.loading}>{alertOnboardingState.loading ? "Saving..." : "Create Alert Onboarding Doc"}</button>
                      </form>
                      {alertOnboardingState.error ? <p className="error">{alertOnboardingState.error}</p> : null}
                      {alertOnboardingState.result ? <pre className="result">{JSON.stringify(alertOnboardingState.result, null, 2)}</pre> : null}
                    </article>
                    ) : null}

                    {alertKnowledgeView === "backend" ? (
                      <article className="panel">
                        <div className="panel-head">
                          <h3>Stored Backend Documents</h3>
                          <button className="button-secondary" type="button" onClick={loadRagDocs}>Refresh</button>
                        </div>
                        <p className="subtitle">Documents currently stored in backend with metadata details.</p>
                        {ragDocs.error ? <p className="error">{ragDocs.error}</p> : null}
                        <div className="table-wrap">
                          <table>
                            <thead>
                              <tr>
                                <th>Title</th>
                                <th>Kind</th>
                                <th>Alert Type</th>
                                <th>Severity</th>
                                <th>Services</th>
                                <th>Document View</th>
                                <th>Updated</th>
                                <th>Metadata</th>
                              </tr>
                            </thead>
                            <tbody>
                              {ragDocs.rows.map((doc, index) => (
                                <tr key={`backend-doc-${doc.path || doc.title || index}`}>
                                  <td>{doc.title || "-"}</td>
                                  <td>{doc.kind || doc.document_kind || "-"}</td>
                                  <td>{doc.alert_type || "-"}</td>
                                  <td>{doc.severity || "-"}</td>
                                  <td>{Array.isArray(doc.services) ? doc.services.join(", ") : (doc.services || "-")}</td>
                                  <td>
                                    <details className="backend-document-view">
                                      <summary>
                                        <span>{backendDocumentPreview(doc)}</span>
                                      </summary>
                                      <div>
                                        <p>{doc.summary || doc.recommended_action || "Document details are available from backend metadata."}</p>
                                        {doc.root_cause ? <p><strong>Root cause:</strong> {doc.root_cause}</p> : null}
                                        {doc.impact ? <p><strong>Impact:</strong> {doc.impact}</p> : null}
                                        {doc.execution_plan ? <pre className="result">{String(doc.execution_plan)}</pre> : null}
                                        <div className="backend-document-actions">
                                          <button
                                            type="button"
                                            className="button-secondary"
                                            onClick={() => downloadRagDocument(doc)}
                                            disabled={!doc.path}
                                          >
                                            Download
                                          </button>
                                        </div>
                                      </div>
                                    </details>
                                  </td>
                                  <td>{doc.updated_at || doc.modified_at || doc.created_at || "-"}</td>
                                  <td>
                                    <details>
                                      <summary style={{ cursor: "pointer" }}>view</summary>
                                      <pre className="result" style={{ marginTop: 8 }}>{JSON.stringify({
                                        path: doc.path || null,
                                        alert_id: doc.alert_id || null,
                                        root_cause: doc.root_cause || null,
                                        impact: doc.impact || null,
                                        execution_plan: doc.execution_plan || null,
                                        recommended_action: doc.recommended_action || null,
                                        source_system: doc.source_system || null,
                                        source_ref: doc.source_ref || null,
                                        tags: doc.tags || null,
                                        metadata: doc.metadata || null,
                                      }, null, 2)}</pre>
                                    </details>
                                  </td>
                                </tr>
                              ))}
                              {!ragDocs.rows.length && !ragDocs.loading ? <tr><td colSpan={8}>No documents found in backend.</td></tr> : null}
                            </tbody>
                          </table>
                        </div>
                      </article>
                    ) : null}
                  </div>
                ) : null}
              </article>
            </section>
          ) : null}

          {activeTab === "summary" ? (
            <section className="grid single-col">
              <article className="panel">
                <div className="panel-head">
                  <h2>Incident Metadata</h2>
                  <p>Incident metadata explorer with policy, transport, and status context.</p>
                  <button className="button-secondary" onClick={loadIncidentMetadata}>Refresh</button>
                </div>
                <div className="filter-grid sticky-controls">
                  <label>
                    Risk Tier
                    <select
                      value={metadataFilters.risk_tier}
                      onChange={(e) => setMetadataFilters((curr) => ({ ...curr, risk_tier: e.target.value }))}
                    >
                      <option value="all">all</option>
                      <option value="high">high</option>
                      <option value="medium">medium</option>
                      <option value="low">low</option>
                    </select>
                  </label>
                  <label>
                    Execution Mode
                    <select
                      value={metadataFilters.execution_mode}
                      onChange={(e) => setMetadataFilters((curr) => ({ ...curr, execution_mode: e.target.value }))}
                    >
                      <option value="all">all</option>
                      <option value="human-approval">human-approval</option>
                      <option value="guided-auto">guided-auto</option>
                      <option value="auto-execute">auto-execute</option>
                    </select>
                  </label>
                  <label>
                    Transport
                    <select
                      value={metadataFilters.transport_provider}
                      onChange={(e) => setMetadataFilters((curr) => ({ ...curr, transport_provider: e.target.value }))}
                    >
                      <option value="all">all</option>
                      <option value="kafka">kafka</option>
                      <option value="rabbitmq">rabbitmq</option>
                    </select>
                  </label>
                  <label>
                    Status
                    <select
                      value={metadataFilters.status}
                      onChange={(e) => setMetadataFilters((curr) => ({ ...curr, status: e.target.value }))}
                    >
                      <option value="all">all</option>
                      <option value="open">open</option>
                      <option value="investigating">investigating</option>
                      <option value="awaiting_approval">awaiting_approval</option>
                      <option value="remediating">remediating</option>
                      <option value="validating">validating</option>
                      <option value="closed">closed</option>
                      <option value="failed">failed</option>
                    </select>
                  </label>
                </div>
                <label>
                  Service contains
                  <input
                    value={metadataFilters.service}
                    placeholder="payments"
                    onChange={(e) => setMetadataFilters((curr) => ({ ...curr, service: e.target.value }))}
                  />
                </label>
                {incidentMetadata.error ? <p className="error">{incidentMetadata.error}</p> : null}
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Incident</th>
                        <th>Service</th>
                        <th>Risk</th>
                        <th>Execution Mode</th>
                        <th>Provider</th>
                        <th>Status</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {monitorScopedIncidentMetadata.map((row, index) => (
                        <tr key={row.incident_id || row.id || index}>
                          <td>{row.incident_id || row.id || "-"}</td>
                          <td>{row.service || "-"}</td>
                          <td>{row.risk_tier || "-"}</td>
                          <td>{row.execution_mode || "-"}</td>
                          <td>{row.transport_provider || "-"}</td>
                          <td><span className={`pill ${statusPillClass(row.status)}`}>{row.status || "-"}</span></td>
                          <td>
                            <button type="button" className="button-secondary" onClick={() => openAlertDetailsFromIncident(row)}>
                              Open
                            </button>
                          </td>
                        </tr>
                      ))}
                      {!monitorScopedIncidentMetadata.length && !incidentMetadata.loading ? (
                        <tr>
                          <td colSpan={7}>No incidents available for {applicationToMonitor}. Run one sample flow from Home.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </article>
            </section>
          ) : null}

          {activeTab === "approval" ? (
            <section className="grid single-col">
              <article className="panel">
                <div className="panel-head">
                  <h2>Human Approval Queue (Legacy)</h2>
                  <p>Primary approval actions now run inside the Alert Details Cockpit on Dashboard for eligible roles.</p>
                </div>
                <p className="subtitle">Use this queue for cross-incident triage, bulk-style review, or manual fallback operations.</p>

                <div className="search-row sticky-controls">
                  <label>
                    Search Guidance
                    <input
                      value={guidanceQuery}
                      onChange={(e) => setGuidanceQuery(e.target.value)}
                      placeholder="payments timeout rollback"
                    />
                  </label>
                  <button className="button-secondary" type="button" onClick={searchGuidanceDocs} disabled={guidanceState.loading}>
                    {guidanceState.loading ? "Searching..." : "Search Guidance"}
                  </button>
                </div>
                {guidanceState.error ? <p className="error">{guidanceState.error}</p> : null}
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Kind</th>
                        <th>Score</th>
                        <th>Title</th>
                        <th>Path</th>
                      </tr>
                    </thead>
                    <tbody>
                      {guidanceState.rows.map((row, index) => (
                        <tr key={`${row.path || row.title || "match"}-${index}`}>
                          <td>{row.kind || row.document_kind || "-"}</td>
                          <td>{row.score ?? "-"}</td>
                          <td>{row.title || row.id || "-"}</td>
                          <td>{row.path || "-"}</td>
                        </tr>
                      ))}
                      {!guidanceState.rows.length && !guidanceState.loading ? (
                        <tr>
                          <td colSpan={4}>Search guidance to view matching runbooks and incidents.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>

                <div className="approval-steps">
                  <div className="approval-step">
                    <strong>Step 1</strong>
                    <span>Select a pending incident from the table below.</span>
                  </div>
                  <div className="approval-step">
                    <strong>Step 2</strong>
                    <span>Review flow context and action details.</span>
                  </div>
                  <div className="approval-step">
                    <strong>Step 3</strong>
                    <span>Submit approve, reject, or modify.</span>
                  </div>
                </div>

                <div className="filter-grid sticky-controls approval-controls">
                  <label>
                    Pending Filter
                    <select value={approvalFilter} onChange={(e) => setApprovalFilter(e.target.value)}>
                      <option value="all">all</option>
                      <option value="awaiting_approval">awaiting_approval</option>
                      <option value="critical">critical</option>
                      <option value="high">high</option>
                      <option value="medium">medium</option>
                      <option value="low">low</option>
                    </select>
                  </label>
                  <label>
                    Selected Incident
                    <input value={selectedApprovalRow ? approvalIncidentId(selectedApprovalRow) : ""} readOnly placeholder="Select from table" />
                  </label>
                  <label>
                    Selected Recommendation
                    <input value={selectedApprovalRecommendationId} readOnly placeholder="Autofills from selected incident" />
                  </label>
                  <label>
                    Flow Context
                    <input value={selectedApprovalFlowContext} readOnly placeholder="flow_id, trace_id, or correlation_id" />
                  </label>
                </div>

                <div className="approval-nav-actions">
                  <button className="button-secondary" type="button" onClick={() => setActiveTab("summary")}>Open Incident Metadata</button>
                  <button className="button-secondary" type="button" onClick={() => setActiveTab("trace")}>Open Agent Flow</button>
                  <button className="button-secondary" type="button" onClick={() => selectedApprovalIncidentId && loadApprovalIncidentContext(selectedApprovalIncidentId)} disabled={!selectedApprovalIncidentId || approvalIncidentContext.loading}>
                    {approvalIncidentContext.loading ? "Syncing..." : "Sync From Approval API"}
                  </button>
                  <button className="button-secondary" type="button" onClick={() => setShowAdvancedApprovalForm((current) => !current)}>
                    {showAdvancedApprovalForm ? "Hide Advanced Approval Form" : "Show Advanced Approval Form"}
                  </button>
                </div>
                {approvalIncidentContext.error ? <p className="error">{approvalIncidentContext.error}</p> : null}

                <p className="subtitle">Latest workflow incident: {latestIncidentId || "not available"}</p>
                <div className="table-wrap" ref={approvalQueueRef}>
                  <table>
                    <thead>
                      <tr>
                        <th>Select</th>
                        <th>Incident</th>
                        <th>Recommendation</th>
                        <th>Service</th>
                        <th>Severity</th>
                        <th>Execution Mode</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPendingApprovals.map((row, index) => {
                        const incidentId = approvalIncidentId(row);
                        const recommendationId = approvalRecommendationId(row);
                        const selected = incidentId && incidentId === selectedApprovalIncidentId;
                        const rowStatus = normalizeApprovalStatus(row?.status);
                        const rowResolved = isApprovalResolvedStatus(rowStatus);
                        const canQuickApprove = !rowResolved && looksLikeUuid(incidentId);
                        const quickApproveBusy = approvalState.loading && selected && approvalForm.action === "approve";
                        const quickRejectBusy = approvalState.loading && selected && approvalForm.action === "reject";
                        const rejectExpanded = !rowResolved && inlineRejectState.incidentId === incidentId;
                        return (
                        <tr key={incidentId || index} className={selected ? "row-selected" : ""}>
                          <td>
                            <button className="button-secondary" type="button" onClick={() => selectApprovalIncident(row)}>
                              {selected ? "Selected" : "Use"}
                            </button>
                          </td>
                          <td>{incidentId || "-"}</td>
                          <td>{recommendationId || "-"}</td>
                          <td>{row.service || "-"}</td>
                          <td>{row.severity || row.risk_tier || "-"}</td>
                          <td>{row.execution_mode || "-"}</td>
                          <td><span className={`pill ${statusPillClass(rowStatus)}`}>{rowStatus || "pending"}</span></td>
                          <td>
                            <button className="button-secondary" type="button" onClick={() => openAlertDetailsFromIncident(row)}>
                              Open
                            </button>
                            {!rowResolved ? (
                              <>
                                <button
                                  className="button-primary"
                                  type="button"
                                  onClick={() => approveIncidentRow(row)}
                                  disabled={!canQuickApprove || approvalState.loading}
                                  title={canQuickApprove ? "Approve this incident directly" : "Recommendation ID unavailable. Use Sync From Approval API first."}
                                  style={{ marginLeft: 8 }}
                                >
                                  {quickApproveBusy ? "Approving..." : "Approve"}
                                </button>
                                <button
                                  className="button-secondary"
                                  type="button"
                                  onClick={() => {
                                    setApprovalState({ loading: false, result: null, error: "" });
                                    setInlineRejectState((current) => current.incidentId === incidentId ? { incidentId: "", comment: "" } : { incidentId, comment: "" });
                                  }}
                                  disabled={!canQuickApprove || approvalState.loading}
                                  title={canQuickApprove ? "Reject this incident with a comment" : "Recommendation ID unavailable. Use Sync From Approval API first."}
                                  style={{ marginLeft: 8 }}
                                >
                                  {rejectExpanded ? "Cancel Reject" : "Reject"}
                                </button>
                              </>
                            ) : (
                              <span className={`pill ${statusPillClass(rowStatus)}`} style={{ marginLeft: 8 }}>
                                {rowStatus}
                              </span>
                            )}
                            {rejectExpanded ? (
                              <div style={{ marginTop: 8, display: "grid", gap: 8 }}>
                                <textarea
                                  rows={2}
                                  placeholder="Add rejection comment"
                                  value={inlineRejectState.comment}
                                  onChange={(e) => setInlineRejectState({ incidentId, comment: e.target.value })}
                                />
                                <button
                                  className="button-primary"
                                  type="button"
                                  onClick={() => rejectIncidentRow(row)}
                                  disabled={!String(inlineRejectState.comment || "").trim() || approvalState.loading}
                                >
                                  {quickRejectBusy ? "Rejecting..." : "Confirm Reject"}
                                </button>
                              </div>
                            ) : null}
                          </td>
                        </tr>
                      )})}
                      {!filteredPendingApprovals.length ? (
                        <tr>
                          <td colSpan={8}>No pending approvals for this filter and monitor scope.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
                {showAdvancedApprovalForm ? (
                  <>
                    <form className="form" onSubmit={submitApproval}>
                      <label>
                        Action
                        <select value={approvalForm.action} onChange={(e) => setApprovalForm({ ...approvalForm, action: e.target.value })}>
                          <option value="approve">approve</option>
                          <option value="reject">reject</option>
                          <option value="modify">modify</option>
                        </select>
                      </label>
                      <label>
                        Incident ID
                        <input value={approvalForm.incident_id} onChange={(e) => setApprovalForm({ ...approvalForm, incident_id: e.target.value })} />
                      </label>
                      <label>
                        Recommendation ID
                        <input value={approvalForm.recommendation_id} onChange={(e) => setApprovalForm({ ...approvalForm, recommendation_id: e.target.value })} />
                      </label>
                      <label>
                        Approver
                        <input value={approvalForm.approver} onChange={(e) => setApprovalForm({ ...approvalForm, approver: e.target.value })} />
                      </label>
                      <label>
                        Channel
                        <select value={approvalForm.channel} onChange={(e) => setApprovalForm({ ...approvalForm, channel: e.target.value })}>
                          <option value="web">web</option>
                          <option value="slack">slack</option>
                          <option value="teams">teams</option>
                          <option value="email">email</option>
                        </select>
                      </label>
                      {approvalForm.action === "modify" ? (
                        <label>
                          Modified Action
                          <textarea rows={3} value={approvalForm.modified_action} onChange={(e) => setApprovalForm({ ...approvalForm, modified_action: e.target.value })} />
                        </label>
                      ) : null}
                      <label>
                        Comment
                        <textarea rows={3} value={approvalForm.comment} onChange={(e) => setApprovalForm({ ...approvalForm, comment: e.target.value })} />
                      </label>
                      <button className="button-primary" type="submit" disabled={!approvalReady || approvalState.loading}>
                        {approvalState.loading ? "Submitting..." : "Submit Approval Action"}
                      </button>
                    </form>
                    {!String(approvalForm.recommendation_id || "").trim() ? (
                      <p className="subtitle">Recommendation ID is required by the approval API. Use the table row selector and Sync From Approval API to load it.</p>
                    ) : null}
                  </>
                ) : (
                  <p className="subtitle">Use inline Approve or Reject for common actions. Open the advanced form for modify or manual approval payload editing.</p>
                )}
                {approvalState.error ? <p className="error">{approvalState.error}</p> : null}
                {approvalState.result ? <pre className="result">{JSON.stringify(approvalState.result, null, 2)}</pre> : null}
              </article>
            </section>
          ) : null}

          {activeTab === "trace" ? (
            <section className="grid single-col">
              <article className="panel">
                <div className="panel-head">
                  <h2>Agent Flow</h2>
                  <p>Agent flow with decisions, outputs, and communication handoffs.</p>
                </div>
                <h3>Workflow Event Timeline</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Step</th>
                        <th>Agent</th>
                        <th>Action</th>
                        <th>Decision</th>
                        <th>Output</th>
                        <th>Handoff</th>
                      </tr>
                    </thead>
                    <tbody>
                      {workflowEventRows.map((row, index) => (
                        <tr key={`${row.sequence}-${index}`}>
                          <td>{row.sequence}</td>
                          <td>{row.agent}</td>
                          <td>{row.action}</td>
                          <td>{row.decision}</td>
                          <td>{row.output}</td>
                          <td>{row.communicates_to}</td>
                        </tr>
                      ))}
                      {!workflowEventRows.length ? (
                        <tr>
                          <td colSpan={6}>Run a workflow to populate detailed agent timeline.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>

                <h3>Gateway Audit Events</h3>
                {gatewayRecent.error ? <p className="error">{gatewayRecent.error}</p> : null}
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Path</th>
                        <th>Status</th>
                        <th>Decision</th>
                        <th>Trace ID</th>
                      </tr>
                    </thead>
                    <tbody>
                      {gatewayRecent.rows.slice(0, 30).map((row, index) => (
                        <tr key={row.id || index}>
                          <td>{row.created_at || "-"}</td>
                          <td>{row.path || "-"}</td>
                          <td>{row.status_code || "-"}</td>
                          <td>{row?.safety?.decision || "-"}</td>
                          <td>{row.trace_id || "-"}</td>
                        </tr>
                      ))}
                      {!gatewayRecent.rows.length && !gatewayRecent.loading ? (
                        <tr>
                          <td colSpan={5}>No recent gateway trace entries.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
                {workflowState.result ? <pre className="result">{JSON.stringify(workflowState.result, null, 2)}</pre> : null}
              </article>
            </section>
          ) : null}

          {activeTab === "finops" ? (
            <section className="grid single-col">
              <article className="panel">
                <div className="panel-head">
                  <h2>FinOps</h2>
                  <p>LLM FinOps with provider cost breakdown and per-call model usage.</p>
                </div>
                <h3>Provider Cost Breakdown</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Provider</th>
                        <th>Calls</th>
                        <th>Tokens</th>
                        <th>Cost USD</th>
                      </tr>
                    </thead>
                    <tbody>
                      {finopsByProvider.map((row, index) => (
                        <tr key={`${row.provider}-${index}`}>
                          <td>{row.provider}</td>
                          <td>{row.calls}</td>
                          <td>{row.total_tokens}</td>
                          <td>{Number(row.total_cost_usd || 0).toFixed(6)}</td>
                        </tr>
                      ))}
                      {!finopsByProvider.length ? (
                        <tr>
                          <td colSpan={4}>No successful model calls recorded yet.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>

                <h3>Per-call Model Usage</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Task</th>
                        <th>Provider</th>
                        <th>Model</th>
                        <th>Input Tokens</th>
                        <th>Output Tokens</th>
                        <th>Total Cost (USD)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {allUsageRows.map((row, index) => (
                        <tr key={`${row.task || "task"}-${index}`}>
                          <td>{row.task || "-"}</td>
                          <td>{row.provider || "-"}</td>
                          <td>{row.model || "-"}</td>
                          <td>{row.input_tokens || "-"}</td>
                          <td>{row.output_tokens || "-"}</td>
                          <td>{row.total_cost_usd || "-"}</td>
                        </tr>
                      ))}
                      {!allUsageRows.length ? (
                        <tr>
                          <td colSpan={6}>No usage yet. Run a sample workflow from Home or open a processed alert to populate FinOps data.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </article>
            </section>
          ) : null}

          {activeTab === "rag" ? (
            <section className="grid single-col">
              <article className="panel">
                <div className="panel-head">
                  <h2>Message Bus</h2>
                  <button className="button-secondary" onClick={() => runWorkflow(selectedFlow)}>Refresh Activity</button>
                </div>

                <MessageBusTopology
                  actual={messageBusActual}
                  configuredRows={messageBusTopicRows}
                  routing={observedRouting}
                  primaryTopic={onboardingForm.azure_service_bus_topic}
                />

                <h3>Latest Workflow Topic Activity</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Service</th>
                        <th>Consumed</th>
                        <th>Published</th>
                        <th>Provider</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {messageBusActual.rows.map((row, index) => (
                        <tr key={`${row.service}-${index}`}>
                          <td>{row.service}</td>
                          <td>{row.consumed}</td>
                          <td>{row.published}</td>
                          <td>{row.provider}</td>
                          <td>{row.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="dual-col">
                  <article className="panel">
                    <h3>Actual Topics Published</h3>
                    <ul className="flow-list">
                      {messageBusActual.published.map((topic) => <li key={`pub-${topic}`}>{topic}</li>)}
                      {!messageBusActual.published.length ? <li>No published topics observed yet.</li> : null}
                    </ul>
                  </article>
                  <article className="panel">
                    <h3>Actual Topics Consumed</h3>
                    <ul className="flow-list">
                      {messageBusActual.consumed.map((topic) => <li key={`con-${topic}`}>{topic}</li>)}
                      {!messageBusActual.consumed.length ? <li>No consumed topics observed yet.</li> : null}
                    </ul>
                  </article>
                </div>

                <h3>Configured Topic Topology</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Service</th>
                        <th>Consumes</th>
                        <th>Publishes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {messageBusTopicRows.map((row, index) => (
                        <tr key={`${row.service}-${index}`}>
                          <td>{row.service}</td>
                          <td>{row.consumes}</td>
                          <td>{row.publishes}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <h3>Routing Rule</h3>
                <p className="subtitle">When dynamic routing is enabled: if stream_count exceeds threshold, provider is kafka; otherwise rabbitmq.</p>
                <p className="subtitle">Observed workflow: {observedRouting?.workflow || "N/A"} | next action: {observedRouting?.next_action || "N/A"}</p>
              </article>
            </section>
          ) : null}

          {activeTab === "safety" ? (
            <section className="grid single-col">
              <article className="panel">
                <div className="panel-head">
                  <h2>Gateway Safety</h2>
                  <p>Review gateway decision, policy reasons, and safety metrics before closure.</p>
                  <button className="button-secondary" onClick={() => { loadGatewaySummary(); loadGatewayRecent(); loadLandingPadRecent(); }}>
                    Refresh
                  </button>
                </div>
                {gatewaySummary.error ? <p className="error">{gatewaySummary.error}</p> : null}
                <div className="stat-grid">
                  <div className="stat-card"><strong>Total</strong><span>{gatewaySummary.data.total_events || 0}</span></div>
                  <div className="stat-card"><strong>Allowed</strong><span>{gatewaySummary.data.allowed || 0}</span></div>
                  <div className="stat-card"><strong>Review</strong><span>{gatewaySummary.data.review || 0}</span></div>
                  <div className="stat-card"><strong>Blocked</strong><span>{gatewaySummary.data.blocked || 0}</span></div>
                </div>
                <p className="subtitle">Latest trace: {gatewaySummary.data.latest_trace_id || "-"}</p>
                <h3>Recent Gateway Events</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Path</th>
                        <th>Status</th>
                        <th>Decision</th>
                        <th>Score</th>
                        <th>Latency ms</th>
                        <th>Reasons</th>
                      </tr>
                    </thead>
                    <tbody>
                      {gatewayRecent.rows.map((row, index) => (
                        <tr key={`${row.trace_id || "gw"}-${index}`}>
                          <td>{row.path || "-"}</td>
                          <td>{row.status_code || "-"}</td>
                          <td>{row?.safety?.decision || "-"}</td>
                          <td>{row?.safety?.score ?? "-"}</td>
                          <td>{row.latency_ms || "-"}</td>
                          <td>{Array.isArray(row?.safety?.reasons) ? row.safety.reasons.join("; ") : "-"}</td>
                        </tr>
                      ))}
                      {!gatewayRecent.rows.length ? (
                        <tr>
                          <td colSpan={6}>No gateway events yet.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>

                <h3>Landing Pad Realtime Ingestion</h3>
                {landingPadRecent.error ? <p className="error">{landingPadRecent.error}</p> : null}
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Received At (UTC)</th>
                        <th>Alert</th>
                        <th>Service</th>
                        <th>Severity</th>
                        <th>Status</th>
                        <th>File</th>
                      </tr>
                    </thead>
                    <tbody>
                      {landingPadRecent.rows.map((row, index) => (
                        <tr key={`${row.file || "landing-pad"}-${index}`}>
                          <td>{row.received_at || row.modified_at || "-"}</td>
                          <td>{row.name || row.alertname || "-"}</td>
                          <td>{row.service || "-"}</td>
                          <td>{String(row.severity || "-").toUpperCase()}</td>
                          <td>{row.alert_status || "-"}</td>
                          <td>{row.file || "-"}</td>
                        </tr>
                      ))}
                      {!landingPadRecent.rows.length ? (
                        <tr>
                          <td colSpan={6}>No realtime landing-pad ingestion records yet.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </article>
            </section>
          ) : null}

          {activeTab === "closed" ? (
            <section className="grid single-col">
              <article className="panel">
                <div className="panel-head">
                  <h2>Closed Tickets</h2>
                  <p>Closed tickets and current closure report summary.</p>
                  <button className="button-secondary" onClick={loadClosedIncidents}>Refresh</button>
                </div>
                <div className="filter-grid sticky-controls">
                  <label>
                    Filter by Risk Tier
                    <select
                      value={closedFilters.risk}
                      onChange={(e) => setClosedFilters((curr) => ({ ...curr, risk: e.target.value }))}
                    >
                      <option value="all">all</option>
                      {closedRiskOptions.map((option) => (
                        <option key={`risk-${option}`} value={option}>{option}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Filter by Execution Mode
                    <select
                      value={closedFilters.mode}
                      onChange={(e) => setClosedFilters((curr) => ({ ...curr, mode: e.target.value }))}
                    >
                      <option value="all">all</option>
                      {closedModeOptions.map((option) => (
                        <option key={`mode-${option}`} value={option}>{option}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <p className="subtitle">Showing {filteredClosedRows.length} filtered records</p>
                {closedIncidents.error ? <p className="error">{closedIncidents.error}</p> : null}
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Incident</th>
                        <th>Service</th>
                        <th>Severity</th>
                        <th>Status</th>
                        <th>Closed At</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredClosedRows.map((row, index) => (
                        <tr key={row.incident_id || index}>
                          <td>{row.incident_id || "-"}</td>
                          <td>{row.service || "-"}</td>
                          <td>{row.severity || "-"}</td>
                          <td><span className={`pill ${statusPillClass(row.status || "closed")}`}>{row.status || "closed"}</span></td>
                          <td>{row.closed_at || row.updated_at || "-"}</td>
                        </tr>
                      ))}
                      {!filteredClosedRows.length && !closedIncidents.loading ? (
                        <tr>
                          <td colSpan={5}>No closed incidents available.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </article>
            </section>
          ) : null}
        </section>
      </div>
    </main>
  );
}
