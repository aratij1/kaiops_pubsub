import { useEffect, useMemo, useRef, useState } from "react";
import * as XLSX from "xlsx";

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
  Digit8: "finops",
  Digit9: "closed",
  Digit0: "summary",
};
const VALID_TABS = new Set(Object.values(TAB_SHORTCUT_MAP));
const MONITORING_TOOL_OPTIONS = ["prometheus", "new_relic", "datadog"];

const ROLE_ALLOWED_TABS = {
  administrator: ["home", "copilot", "approval", "executive", "admin", "trace", "safety", "rag", "finops", "closed", "summary"],
  l1_operator: ["home"],
  l2_engineer: ["home", "copilot", "approval", "trace", "safety", "rag", "finops", "closed", "summary"],
  l3_engineer: ["home", "copilot", "approval", "executive", "trace", "safety", "rag", "finops", "closed", "summary"],
  executive: ["home", "copilot", "approval", "executive", "trace", "safety", "rag", "finops", "closed", "summary"],
};

function normalizeRoleName(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_");
}

function simplifyMonitoringUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `http://${raw}`;
  return withScheme.replace(/\/+$/, "");
}

function extractMonitoringToolAndUrl(source, fallbackTool = "prometheus", fallbackUrl = "") {
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

function looksLikeUuid(value) {
  const token = String(value || "").trim();
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(token);
}

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
  return token === "kaiops-core" || token === "kaiops" || token === "core";
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

async function fetchJson(path, options = {}) {
  const maxAttempts = 4;
  let lastError = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetch(path, {
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
        ...options,
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
      lastError = error;
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

function elapsedSeconds(start, end) {
  const startDate = parseUtcTimestamp(start);
  const endDate = parseUtcTimestamp(end);
  if (!startDate || !endDate) {
    return "-";
  }
  return ((endDate.getTime() - startDate.getTime()) / 1000).toFixed(3);
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
  const inputTokens = toFiniteNumber(entry.input_tokens);
  const outputTokens = toFiniteNumber(entry.output_tokens);
  const totalTokens = toFiniteNumber(entry.total_tokens || (inputTokens + outputTokens));
  return {
    task: entry.task || entry.agent || entry.service || entry.action || "-",
    provider: entry.provider || entry.vendor || "unknown",
    model: entry.model || entry.model_name || "unknown",
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    total_tokens: totalTokens,
    total_cost_usd: toFiniteNumber(entry.total_cost_usd || entry.cost_usd),
  };
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

function FlowTimelineGraph({ rows }) {
  const timelineRows = Array.isArray(rows) ? rows : [];
  if (!timelineRows.length) {
    return <p className="subtitle">No timeline data found for selected alert.</p>;
  }
  return (
    <div className="timeline-graph">
      {timelineRows.map((row, index) => (
        <article
          className="timeline-node"
          key={`timeline-node-${index}`}
          style={{ animationDelay: `${Math.min(index * 70, 560)}ms` }}
        >
          <div className="timeline-rail">
            <span className="timeline-dot" />
            {index < timelineRows.length - 1 ? <span className="timeline-line" /> : null}
          </div>
          <div className="timeline-body">
            <div className="timeline-headline">
              <strong>{row.stage || "-"}</strong>
              <span>{formatUtcTimestamp(row.timestamp)}</span>
            </div>
            <div className="timeline-meta">
              <span>{row.agent || "-"}</span>
              <span>{row.service || "-"}</span>
              <span>{row.elapsed !== "-" ? `${row.elapsed}s` : "-"}</span>
            </div>
            <p>{row.detail || "-"}</p>
            <div className="timeline-tags">
              <span className="timeline-tag">in: {row.consumes || "-"}</span>
              <span className="timeline-tag">out: {row.publishes || "-"}</span>
              <span className="timeline-tag">db: {row.tables || "-"}</span>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

function AgentEventsGraph({ rows }) {
  const eventRows = Array.isArray(rows) ? rows : [];
  if (!eventRows.length) {
    return <p className="subtitle">No events found for selected alert.</p>;
  }
  return (
    <div className="agent-events-graph">
      {eventRows.map((row, index) => (
        <article
          className="agent-event-card"
          key={`agent-event-${index}`}
          style={{ animationDelay: `${Math.min(index * 60, 480)}ms` }}
        >
          <div className="agent-event-step">{row.sequence || index + 1}</div>
          <div className="agent-event-body">
            <strong>{row.agent || "-"}</strong>
            <p>{row.action || "-"}</p>
            <div className="agent-event-kv">
              <span>Decision: {compactText(row.decision, 120) || "-"}</span>
              <span>Output: {compactText(row.output, 120) || "-"}</span>
              <span>Next: {row.communicates_to || "-"}</span>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

function TopicFlowGraph({ routing, timelineRows }) {
  const safeRouting = routing && typeof routing === "object" ? routing : {};
  const channels = Array.from(new Set(
    (Array.isArray(timelineRows) ? timelineRows : [])
      .flatMap((row) => [row?.consumes, row?.publishes])
      .map((item) => String(item || "").trim())
      .filter(Boolean)
  ));

  return (
    <div className="topic-flow-graph">
      <div className="topic-flow-pill">
        <span>Provider</span>
        <strong>{String(safeRouting?.message_bus_provider || "-").toUpperCase()}</strong>
      </div>
      <div className="topic-flow-pill">
        <span>Workflow</span>
        <strong>{safeRouting?.workflow || "-"}</strong>
      </div>
      <div className="topic-flow-pill">
        <span>Execution</span>
        <strong>{safeRouting?.execution_mode || "-"}</strong>
      </div>
      <div className="topic-channel-rail">
        {channels.length ? channels.map((channel, index) => (
          <div key={`channel-${index}`} className="topic-channel-chip" style={{ animationDelay: `${Math.min(index * 70, 560)}ms` }}>
            {channel}
          </div>
        )) : <p className="subtitle">No observed channels for selected alert.</p>}
      </div>
    </div>
  );
}

function ExecutionPlanGraph({ plan }) {
  const safePlan = plan && typeof plan === "object" ? plan : {};
  const commands = Array.isArray(safePlan.commands) ? safePlan.commands : [];

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
        </div>
      </article>
      <article className="execution-card">
        <h4>Command Sequence</h4>
        <div className="execution-command-list">
          {commands.length ? commands.map((command, index) => (
            <div className="execution-command" key={`cmd-${index}`} style={{ animationDelay: `${Math.min(index * 80, 640)}ms` }}>
              <span>{index + 1}</span>
              <code>{String(command || "-")}</code>
            </div>
          )) : <p className="subtitle">No command sequence found.</p>}
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

export default function App() {
  const defaultMonitorApplications = ["payments", "checkout", "orders-db", "inventory", "kaiops-core"];
  const [applicationToMonitor, setApplicationToMonitor] = useState("payments");
  const [monitorApplications, setMonitorApplications] = useState(defaultMonitorApplications);
  const [activeTab, setActiveTab] = useState("home");
  const [uiDensity, setUiDensity] = useState("comfortable");
  const [uiTheme, setUiTheme] = useState("auto");
  const [health, setHealth] = useState({ loading: false, ok: false, message: "Not checked" });
  const [alerts, setAlerts] = useState({ loading: false, rows: [], error: "" });
  const [alertsLimit, setAlertsLimit] = useState(50);
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
  const [selectedStageCompleteness, setSelectedStageCompleteness] = useState({
    loading: false,
    data: null,
    error: "",
    incidentId: "",
  });
  const [homeDetailTab, setHomeDetailTab] = useState("summary");
  const [approvalForm, setApprovalForm] = useState({
    action: "approve",
    incident_id: "",
    recommendation_id: "",
    approver: "admin",
    channel: "web",
    comment: "",
    modified_action: "",
  });
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
    monitoring_url: "http://prometheus.local:9090",
    prometheus_url: "http://prometheus.local:9090",
    new_relic_url: "",
    datadog_url: "",
    gcp_project_id: "",
    gcp_region: "us-central1",
    pubsub_topic: "kaiops-orchestration-events",
    pubsub_subscription: "kaiops-orchestration-sub",
    vertex_model_armor_enabled: false,
    vertex_model_armor_template: "",
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
  const [onboardingGeneratedDocs, setOnboardingGeneratedDocs] = useState([]);
  const [onboardingDocApprovalState, setOnboardingDocApprovalState] = useState({
    loading: false,
    error: "",
    success: "",
    approved: false,
  });
  const [onboardingRuleLookup, setOnboardingRuleLookup] = useState({ workflow_id: "", loading: false, result: null, error: "" });
  const [selectedOnboardingProject, setSelectedOnboardingProject] = useState("");
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
  });
  const [alertOnboardingState, setAlertOnboardingState] = useState({ loading: false, result: null, error: "" });
  const [docPromptAlert, setDocPromptAlert] = useState(null);
  const [alertBulkState, setAlertBulkState] = useState({
    fileName: "",
    loading: false,
    parsedRows: [],
    results: [],
    error: "",
  });
  const alertDetailsRef = useRef(null);

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
    setHomeDetailTab("summary");
    loadAlertDetails(alertId);
  }

  function openAlertDetailsFromIncident(row) {
    const incidentId = String(row?.incident_id || row?.id || "").trim();
    if (!incidentId) {
      return;
    }
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
      return;
    }
    openAlertDetails(scopedRows[0]);
  }, [activeTab, alerts.rows, applicationToMonitor, selectedAlertId, selectedAlertData.payload, selectedAlertData.error, selectedAlertData.alertId]);

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
      const payload = await fetchJson("/api-gateway/onboarding/state");
      const data = unwrap(payload);
      const rows = Array.isArray(data?.rows) ? data.rows : [];
      const projects = rows
        .map((row) => String(row?.project_name || "").trim())
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
      const unique = Array.from(new Set([...defaultMonitorApplications, ...projects, ...alertApplications]));
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
      await fetchJson("/api-gateway/rag/reload", { method: "POST", body: JSON.stringify({}) });
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
      gcp_project_id: String(connectivityPayload.gcp_project_id || curr.gcp_project_id || "").trim(),
      gcp_region: String(connectivityPayload.gcp_region || curr.gcp_region || "").trim(),
      pubsub_topic: String(connectivityPayload.pubsub_topic || curr.pubsub_topic || "").trim(),
      pubsub_subscription: String(connectivityPayload.pubsub_subscription || curr.pubsub_subscription || "").trim(),
      vertex_model_armor_enabled: Boolean(connectivityPayload.vertex_model_armor_enabled ?? curr.vertex_model_armor_enabled),
      vertex_model_armor_template: String(connectivityPayload.vertex_model_armor_template || curr.vertex_model_armor_template || "").trim(),
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
  }

  function resetNewProjectOnboardingDraft() {
    setSelectedOnboardingProject("");
    setOnboardingWorkflowSteps([]);
    setOnboardingGeneratedDocs([]);
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

  async function ingestGeneratedOnboardingDocuments(documents) {
    const rows = Array.isArray(documents) ? documents : [];
    if (!rows.length) {
      return { total: 0, ingested: 0, failed: 0 };
    }

    let ingested = 0;
    let failed = 0;
    for (const row of rows) {
      try {
        await fetchJson("/api-gateway/rag/documents", {
          method: "POST",
          body: JSON.stringify(row),
        });
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
      setOnboardingState((current) => ({ ...current, success: `Project onboarding saved. Documents approved: ${summary.ingested}/${summary.total}.` }));
    } catch (error) {
      setOnboardingDocApprovalState({ loading: false, error: error.message, success: "", approved: false });
    }
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
      await fetchJson(`/api-gateway/onboarding/rules/pipeline/${encodeURIComponent(workflowId)}`, {
        method: "PUT",
        body: JSON.stringify({
          project_name: projectName,
          result: parsedResult,
          status: "updated",
        }),
      });
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
      await fetchJson(`/api-gateway/onboarding/rules/pipeline/${encodeURIComponent(normalizedWorkflowId)}`, {
        method: "DELETE",
      });
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
      await fetchJson(`/api-gateway/onboarding/state/${encodeURIComponent(normalizedProject)}`, {
        method: "DELETE",
      });
      await loadOnboardingAdminData();
      setOnboardingState((current) => ({ ...current, success: "Project onboarding deleted." }));
    } catch (error) {
      setOnboardingState((current) => ({ ...current, loading: false, error: error.message, success: "" }));
    }
  }

  async function loadOnboardingAdminData() {
    setOnboardingState((current) => ({ ...current, loading: true, error: "", success: "" }));
    try {
      const [connectivityPayload, statePayload] = await Promise.all([
        fetchJson("/api-gateway/onboarding/connectivity"),
        fetchJson("/api-gateway/onboarding/state"),
      ]);
      const connectivity = connectivityPayload?.data?.connectivity || connectivityPayload?.connectivity || {};
      const rows = statePayload?.data?.rows || statePayload?.rows || [];
      const project = connectivity?.project || {};
      const allRows = Array.isArray(rows) ? rows : [];
      const projectRows = allRows.filter((row) => String(row?.provider_name || "").trim().toLowerCase() === "project");
      const preferredProjectName = String(project?.name || selectedOnboardingProject || "").trim();
      const preferredProjectRow = projectRows.find((row) => String(row?.project_name || "").trim() === preferredProjectName)
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
        gcp_project_id: String(connectivity?.gcp_project_id || curr.gcp_project_id || "").trim(),
        gcp_region: String(connectivity?.gcp_region || curr.gcp_region || "").trim(),
        pubsub_topic: String(connectivity?.pubsub_topic || curr.pubsub_topic || "").trim(),
        pubsub_subscription: String(connectivity?.pubsub_subscription || curr.pubsub_subscription || "").trim(),
        vertex_model_armor_enabled: Boolean(connectivity?.vertex_model_armor_enabled ?? curr.vertex_model_armor_enabled),
        vertex_model_armor_template: String(connectivity?.vertex_model_armor_template || curr.vertex_model_armor_template || "").trim(),
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
        gcp_project_id: String(onboardingForm.gcp_project_id || "").trim(),
        gcp_region: String(onboardingForm.gcp_region || "").trim(),
        pubsub_topic: String(onboardingForm.pubsub_topic || "").trim(),
        pubsub_subscription: String(onboardingForm.pubsub_subscription || "").trim(),
        vertex_model_armor_enabled: Boolean(onboardingForm.vertex_model_armor_enabled),
        vertex_model_armor_template: String(onboardingForm.vertex_model_armor_template || "").trim(),
        user_assignments: userAssignments,
        active_provider: selectedMonitoringTool,
      };

      const onboardingPath = String(onboardingForm.onboarding_path || "existing_monitoring").trim().toLowerCase();
      const plainLanguageRequirements = String(onboardingForm.rule_onboarding_plain_language || "")
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
      const shouldStartRuleOnboarding = onboardingPath === "setup_monitoring" && plainLanguageRequirements.length > 0;

      const response = await fetchJson("/api-gateway/onboarding/complete", {
        method: "POST",
        body: JSON.stringify({
          project_mode: onboardingProjectMode === "new" ? "new" : "existing",
          onboarding_path: onboardingPath,
          connectivity: payload,
          start_rules_onboarding: shouldStartRuleOnboarding,
          plain_language_requirements: plainLanguageRequirements,
          selected_monitoring_tool: selectedMonitoringTool,
          generate_documents: true,
        }),
      });

      const completePayload = unwrap(response);
      const workflowSteps = Array.isArray(completePayload?.workflow_steps) ? completePayload.workflow_steps : [];
      setOnboardingWorkflowSteps(workflowSteps);
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
      const generatedDocs = Array.isArray(completePayload?.rag_documents) ? completePayload.rag_documents : [];
      setOnboardingGeneratedDocs(generatedDocs);

      setSelectedOnboardingProject(String(payload.project.name || "").trim());
      if (onboardingProjectMode === "new") {
        setOnboardingProjectMode("existing");
      }
      await loadOnboardingAdminData();
      setOnboardingState((current) => ({
        ...current,
        success: shouldStartRuleOnboarding
          ? generatedDocs.length
            ? `Workflow completed through step ${workflowSteps.length || 0}. Review generated documents and click Approve.`
            : `Workflow completed through step ${workflowSteps.length || 0}. No documents were generated.`
          : onboardingPath === "existing_monitoring"
            ? "Project onboarding saved. Send alerts to landing pad to trigger the downstream workflow."
            : "Project onboarding saved.",
      }));
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
      cloud_provider: onboardingForm.deployment_mode === "gcp_cloud" ? "gcp" : "on_prem",
      region: String(onboardingForm.region || "").trim(),
      monitoring_platforms: MONITORING_TOOL_OPTIONS.includes(selectedMonitoringTool) ? [selectedMonitoringTool] : ["prometheus"],
      notification_platforms: ["slack", "teams", "pagerduty"],
    };
  }

  async function loadOnboardingRuleCapabilities() {
    setOnboardingRuleCapabilities((current) => ({ ...current, loading: true, error: "" }));
    try {
      const response = await fetchJson("/api-gateway/onboarding/rules/capabilities");
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

      const response = await fetchJson("/api-gateway/onboarding/rules/pipeline/existing", {
        method: "POST",
        body: JSON.stringify(payload),
      });
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

      const response = await fetchJson("/api-gateway/onboarding/rules/pipeline/new", {
        method: "POST",
        body: JSON.stringify(payload),
      });
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
      const response = await fetchJson(`/api-gateway/onboarding/rules/pipeline/${encodeURIComponent(workflowId)}`);
      const result = unwrap(response);
      setOnboardingRuleLookup((current) => ({ ...current, loading: false, result, error: "" }));
    } catch (error) {
      setOnboardingRuleLookup((current) => ({ ...current, loading: false, result: null, error: error.message }));
    }
  }

  async function submitAlertOnboarding(event) {
    event.preventDefault();
    setAlertOnboardingState({ loading: true, result: null, error: "" });
    try {
      const payload = {
        kind: String(alertOnboarding.kind || "incident").trim(),
        title: String(alertOnboarding.title || "").trim(),
        summary: String(alertOnboarding.summary || "").trim() || null,
        content: String(alertOnboarding.content || "").trim(),
        services: String(alertOnboarding.services || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        severity: String(alertOnboarding.severity || "").trim(),
        alert_type: String(alertOnboarding.alert_type || "").trim(),
        alert_id: String(alertOnboarding.alert_id || "").trim() || null,
      };
      const response = await fetchJson("/api-gateway/rag/documents", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setAlertOnboardingState({ loading: false, result: response, error: "" });
      await loadRagDocs();
      if (docPromptAlert) {
        await loadRecentAlerts();
        setDocPromptAlert(null);
      }
    } catch (error) {
      setAlertOnboardingState({ loading: false, result: null, error: error.message });
    }
  }

  function openDocumentPrompt(row) {
    const alertId = String(row?.alert_id || row?.id || "").trim();
    setAlertOnboarding((curr) => ({
      ...curr,
      kind: "runbook",
      title: String(row?.name || row?.alert_name || "Runbook").slice(0, 160),
      summary: "",
      content: "Provide troubleshooting and escalation steps for this alert scenario.",
      services: String(row?.service || "").trim(),
      severity: String(row?.severity || "high").toLowerCase(),
      alert_type: String(row?.name || row?.alert_name || "").trim(),
      alert_id: alertId,
    }));
    setAlertOnboardingState({ loading: false, result: null, error: "" });
    setDocPromptAlert(row);
  }

  function closeDocumentPrompt() {
    setDocPromptAlert(null);
  }

  function toText(value) {
    return String(value == null ? "" : value).trim();
  }

  function findColumn(row, aliases) {
    const keys = Object.keys(row || {});
    const normalizedMap = new Map(keys.map((key) => [toText(key).toLowerCase().replace(/\s+/g, "_"), key]));
    for (const alias of aliases) {
      const resolved = normalizedMap.get(alias);
      if (resolved) {
        return row[resolved];
      }
    }
    return "";
  }

  function normalizeBulkAlertRow(row, index) {
    const line = index + 2;
    const kind = toText(findColumn(row, ["kind"])) || alertOnboarding.kind;
    const title = toText(findColumn(row, ["title", "name"]));
    const summary = toText(findColumn(row, ["summary", "description"]));
    const content = toText(findColumn(row, ["content", "details", "runbook", "body"]));
    const severity = toText(findColumn(row, ["severity", "priority"])) || alertOnboarding.severity;
    const alertType = toText(findColumn(row, ["alert_type", "alerttype", "type"])) || alertOnboarding.alert_type;
    const servicesRaw = toText(findColumn(row, ["services", "service", "service_names"]));
    const services = servicesRaw
      .split(",")
      .map((item) => toText(item))
      .filter(Boolean);

    const payload = {
      kind,
      title,
      summary: summary || null,
      content,
      services,
      severity,
      alert_type: alertType,
    };

    const errors = [];
    if (!title) {
      errors.push("title is required");
    }
    if (!content || content.length < 20) {
      errors.push("content must be at least 20 characters");
    }
    if (!kind) {
      errors.push("kind is required");
    }

    return {
      line,
      payload,
      valid: errors.length === 0,
      errors,
    };
  }

  async function onAlertBulkFileSelected(event) {
    const file = event.target?.files?.[0];
    if (!file) {
      return;
    }
    setAlertBulkState({ fileName: file.name, loading: false, parsedRows: [], results: [], error: "" });

    try {
      const extension = toText(file.name.split(".").pop()).toLowerCase();
      const workbook = extension === "csv"
        ? XLSX.read(await file.text(), { type: "string" })
        : XLSX.read(await file.arrayBuffer(), { type: "array" });
      const firstSheetName = workbook.SheetNames[0];
      const firstSheet = workbook.Sheets[firstSheetName];
      const rows = XLSX.utils.sheet_to_json(firstSheet, { defval: "" });

      if (!rows.length) {
        setAlertBulkState((current) => ({ ...current, error: "Uploaded sheet has no rows." }));
        return;
      }

      const parsedRows = rows.map((row, index) => normalizeBulkAlertRow(row, index));
      setAlertBulkState((current) => ({ ...current, parsedRows, error: "", results: [] }));
    } catch (error) {
      setAlertBulkState((current) => ({ ...current, parsedRows: [], results: [], error: `Unable to parse spreadsheet: ${error.message}` }));
    }
  }

  async function submitAlertOnboardingBulk() {
    const rows = alertBulkState.parsedRows;
    if (!rows.length) {
      setAlertBulkState((current) => ({ ...current, error: "Upload an Excel file first." }));
      return;
    }

    setAlertBulkState((current) => ({ ...current, loading: true, error: "", results: [] }));

    const results = [];
    for (const row of rows) {
      if (!row.valid) {
        results.push({
          line: row.line,
          status: "failed",
          message: row.errors.join("; "),
          title: row.payload.title || "-",
        });
        continue;
      }

      try {
        await fetchJson("/api-gateway/rag/documents", {
          method: "POST",
          body: JSON.stringify(row.payload),
        });
        results.push({ line: row.line, status: "success", message: "Inserted", title: row.payload.title || "-" });
      } catch (error) {
        results.push({ line: row.line, status: "failed", message: error.message, title: row.payload.title || "-" });
      }
    }

    setAlertBulkState((current) => ({ ...current, loading: false, results }));
    await loadRagDocs();
  }

  async function refreshAll() {
    await Promise.all([
      checkHealth(),
      loadRecentAlerts(),
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
    setApplicationToMonitor(monitorApplications[0] || "payments");
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
    const mappedEvents = selectedAlertEvents.map((event, index) => {
      const decision = event?.decision;
      const input = typeof event?.input === "object" && event.input ? event.input : {};
      return {
        sequence: event?.sequence || index + 1,
        agent: displayAgentName(event?.agent || event?.service || "-"),
        action: event?.action || event?.event_type || event?.status || "-",
        decision: decision && typeof decision === "object" ? JSON.stringify(decision) : String(decision || "-"),
        output:
          event?.output && typeof event.output === "object"
            ? JSON.stringify(event.output)
            : String(event?.output || event?.event_type || "-"),
        communicates_to: event?.communicates_to || event?.transport_channel || input?.transport_channel || "-",
      };
    });

    const traceRows = selectedAlertEventTrace.map((row, index) => ({
      sequence: mappedEvents.length + index + 1,
      agent: displayAgentName(row?.service || "-"),
      action: summarizeEventType(row?.event_type),
      decision: row?.policy_reason || row?.status || row?.event_stage || "-",
      output: row?.event_type || "-",
      communicates_to: row?.transport_channel || "-",
    }));

    if (!mappedEvents.length) {
      return traceRows;
    }

    const seenSignatures = new Set(
      mappedEvents.map((row) => `${String(row.agent || "").toLowerCase()}|${String(row.action || "").toLowerCase()}`)
    );
    const appendedTraceRows = traceRows.filter((row) => {
      const signature = `${String(row.agent || "").toLowerCase()}|${String(row.action || "").toLowerCase()}`;
      if (seenSignatures.has(signature)) {
        return false;
      }
      seenSignatures.add(signature);
      return true;
    });

    return [...mappedEvents, ...appendedTraceRows].map((row, index) => ({
      ...row,
      sequence: index + 1,
    }));
  }, [selectedAlertEvents, selectedAlertEventTrace, selectedAlertWorkflow]);

  const selectedAlertUsage = useMemo(() => {
    const usage =
      selectedAlertWorkflow?.recommendation?.metadata?.model_usage
      || selectedAlertWorkflow?.finops?.calls
      || selectedAlertWorkflow?.recommendation?.metadata?.llm_calls
      || [];
    return Array.isArray(usage) ? usage : [];
  }, [selectedAlertWorkflow]);

  const selectedAlertRouting = useMemo(() => extractObservedRoutingMetrics(selectedAlertWorkflow), [selectedAlertWorkflow]);

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
    const commands =
      (Array.isArray(recommendation?.commands) && recommendation.commands)
      || (Array.isArray(remediationAction?.commands) && remediationAction.commands)
      || (Array.isArray(decision?.commands) && decision.commands)
      || [];

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
      commands,
    };
  }, [selectedAlertWorkflow, selectedAlertRouting]);

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

  const selectedAlertTimelineRows = useMemo(() => {
    const ingestAt =
      selectedAlertWorkflow?.alert?.created_at ||
      selectedAlertRow?.created_at ||
      selectedAlertRow?.starts_at ||
      "";
    const incidentCreatedAt = selectedAlertWorkflow?.incident?.created_at || "";
    const latestFlowUpdateAt =
      selectedIncidentMetadataRow?.updated_at ||
      selectedIncidentMetadataRow?.latest_event_at ||
      "";
    const latestEventType = String(selectedIncidentMetadataRow?.latest_event_type || "").trim();

    const summaryRows = [
      {
        stage: "Alert Ingested",
        agent: "monitoring-adapter",
        service: "monitoring-adapter",
        consumes: "-",
        publishes: "raw-alerts",
        timestamp: ingestAt,
        elapsed: "0.000",
        detail: "Alert accepted and persisted.",
        tables: "alerts",
        query: "INSERT alerts",
      },
      {
        stage: "Incident Created",
        agent: "alert-intelligence",
        service: "alert-intelligence",
        consumes: "raw-alerts",
        publishes: "enriched-alerts",
        timestamp: incidentCreatedAt,
        elapsed: elapsedSeconds(ingestAt, incidentCreatedAt),
        detail: "Incident opened from alert correlation.",
        tables: "incidents, agent_work_items",
        query: "INSERT incidents; INSERT agent_work_items",
      },
    ];

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
        agent: displayAgentName(event.service || "-"),
        service: event.service || "-",
        consumes: event.source_channel || "-",
        publishes: event.transport_channel || "-",
        timestamp: event.timestamp || "",
        elapsed: elapsedSeconds(ingestAt, event.timestamp || ""),
        detail: detailParts.join(" | ") || "Trace event recorded.",
        tables: tableHints.join(", ") || "-",
        query: compactText(event.query_hint, 140) || "-",
      };
    });

    const workflowRows =
      traceRows.length > 0
        ? traceRows
        : selectedAlertEvents
            .filter((event) => event && typeof event === "object")
            .sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0))
            .map((event) => {
              const route = routeForAgent(event.agent);
              const step = Number(event.sequence || 0);
              const timestamp = event.timestamp || "";
              const stageName = step > 0 ? `Workflow Step ${step}` : "Workflow Step";
              const decisionText =
                event.decision && typeof event.decision === "object"
                  ? JSON.stringify(event.decision)
                  : String(event.decision || "").trim();
              const actionText = String(event.action || event.output || event.status || "").trim();
              return {
                stage: stageName,
                agent: displayAgentName(event.agent || "-"),
                service: route?.service || "-",
                consumes: route?.consumes || "-",
                publishes: route?.publishes || "-",
                timestamp,
                elapsed: elapsedSeconds(ingestAt, timestamp),
                detail: compactText(decisionText || actionText || "Workflow event recorded.", 160),
                tables: "-",
                query: "-",
              };
            });

    const terminalRows = [
      {
        stage: "Latest Workflow Update",
        agent: "incident-projection",
        service: "monitoring-adapter",
        consumes: "incident-events",
        publishes: "incident-projections",
        timestamp: latestFlowUpdateAt,
        elapsed: elapsedSeconds(ingestAt, latestFlowUpdateAt),
        detail: latestEventType || "Latest incident metadata/projection update.",
        tables: "incident_projections",
        query: "UPSERT incident_projections",
      },
      {
        stage: "Current Incident Status",
        agent: "workflow-state",
        service: "ui",
        consumes: "incident-projections",
        publishes: "ui",
        timestamp: latestFlowUpdateAt || incidentCreatedAt || ingestAt,
        elapsed: elapsedSeconds(ingestAt, latestFlowUpdateAt || incidentCreatedAt || ingestAt),
        detail: String(selectedIncidentMetadataRow?.status || selectedAlertWorkflow?.incident?.status || "unknown"),
        tables: "incident_projections",
        query: "SELECT incident_projections",
      },
    ];

    const rows = [...summaryRows, ...workflowRows, ...terminalRows].filter(
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
    );

    return rows;
  }, [selectedAlertWorkflow, selectedAlertRow, selectedIncidentMetadataRow, selectedAlertEvents, selectedAlertEventTrace]);

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
      if (
        synthetic.provider !== "unknown"
        || synthetic.model !== "unknown"
        || synthetic.total_tokens > 0
        || synthetic.total_cost_usd > 0
      ) {
        merged.push(synthetic);
      }
    });

    gatewayRecent.rows.forEach((row) => {
      appendUsage(row?.finops?.calls);
      appendUsage(row?.model_usage);
      appendUsage(row?.llm_usage);
    });

    return merged;
  }, [panelWorkflowUsage, selectedAlertUsage, latestWorkflow, monitorScopedIncidentMetadata, gatewayRecent.rows]);

  useEffect(() => {
    if (activeTab !== "home" || homeDetailTab !== "api") {
      return;
    }
    loadGatewayRecent();
  }, [activeTab, homeDetailTab]);

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
    const recommendation = normalized.recommendation && typeof normalized.recommendation === "object"
      ? normalized.recommendation
      : {};
    const candidates = [
      normalized.recommendation_id,
      recommendation.id,
      normalized.remediation_recommendation_id,
      normalized.recommended_action_id,
    ];
    for (const candidate of candidates) {
      const token = String(candidate || "").trim();
      if (looksLikeUuid(token)) {
        return token;
      }
    }
    return "";
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

  async function loadApprovalIncidentContext(incidentId) {
    const normalized = String(incidentId || "").trim();
    if (!normalized) {
      return;
    }
    setApprovalIncidentContext({ loading: true, incident_id: normalized, payload: null, error: "" });
    try {
      const response = await fetchJson(`/api-gateway/approval/incident/${encodeURIComponent(normalized)}`);
      const payload = unwrap(response);
      const recommendationId = approvalRecommendationFromPayload(payload);
      setApprovalIncidentContext({ loading: false, incident_id: normalized, payload, error: "" });
      if (recommendationId) {
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
      setApprovalIncidentContext({ loading: false, incident_id: normalized, payload: null, error: brief });
    }
  }

  const pendingApprovals = useMemo(() => {
    return monitorScopedIncidentMetadata.filter((row) => {
      const mode = String(row?.execution_mode || "").toLowerCase();
      const status = String(row?.status || "").toLowerCase();
      return mode === "human-approval" || status === "awaiting_approval";
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
    setApprovalState((current) => ({ ...current, error: "" }));
    loadApprovalIncidentContext(incidentId);
  }

  const approvalReady = useMemo(() => {
    const hasBase = String(approvalForm.incident_id || "").trim() && String(approvalForm.recommendation_id || "").trim() && String(approvalForm.approver || "").trim();
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

    return fetchJson(`/api-gateway/approval/${normalizedAction}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async function approveIncidentRow(row) {
    const incidentId = approvalIncidentId(row);
    const rowRecommendationId = approvalRecommendationId(row);
    const recommendationId = rowRecommendationId
      || (approvalIncidentContext.incident_id === incidentId ? approvalRecommendationFromPayload(approvalIncidentContext.payload) : "");

    setSelectedApprovalIncidentId(incidentId);
    setApprovalState({ loading: true, result: null, error: "" });

    try {
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
      setApprovalState({ loading: false, result: response, error: "" });
      await Promise.all([loadIncidentMetadata(), loadGatewayRecent(), loadGatewaySummary()]);
    } catch (error) {
      const raw = String(error?.message || "");
      const concise = raw.includes("HTTP 422")
        ? "Inline approve needs a valid recommendation_id. Use Sync From Approval API first if this row has not been enriched yet."
        : raw;
      setApprovalState({ loading: false, result: null, error: concise });
    }
  }

  async function rejectIncidentRow(row) {
    const incidentId = approvalIncidentId(row);
    const rowRecommendationId = approvalRecommendationId(row);
    const recommendationId = rowRecommendationId
      || (approvalIncidentContext.incident_id === incidentId ? approvalRecommendationFromPayload(approvalIncidentContext.payload) : "");

    setSelectedApprovalIncidentId(incidentId);
    setApprovalState({ loading: true, result: null, error: "" });

    try {
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
      setInlineRejectState({ incidentId: "", comment: "" });
      setApprovalState({ loading: false, result: response, error: "" });
      await Promise.all([loadIncidentMetadata(), loadGatewayRecent(), loadGatewaySummary()]);
    } catch (error) {
      const raw = String(error?.message || "");
      const concise = raw.includes("HTTP 422")
        ? "Inline reject needs a valid recommendation_id. Use Sync From Approval API first if this row has not been enriched yet."
        : raw;
      setApprovalState({ loading: false, result: null, error: concise });
    }
  }

  async function submitApproval(event) {
    event.preventDefault();
    setApprovalState({ loading: true, result: null, error: "" });
    try {
      const incidentId = String(approvalForm.incident_id || selectedApprovalIncidentId || "").trim();
      const recommendationIdCandidate = String(
        approvalForm.recommendation_id
        || selectedApprovalRecommendationId
        || approvalRecommendationFromPayload(approvalIncidentContext.payload)
        || ""
      ).trim();
      const response = await executeApprovalAction({
        incidentId,
        recommendationId: recommendationIdCandidate,
        action: approvalForm.action,
        approver: approvalForm.approver,
        channel: approvalForm.channel,
        comment: approvalForm.comment,
        modifiedAction: approvalForm.modified_action,
      });
      setApprovalState({ loading: false, result: response, error: "" });
      await Promise.all([loadIncidentMetadata(), loadGatewayRecent(), loadGatewaySummary()]);
    } catch (error) {
      const raw = String(error?.message || "");
      const concise = raw.includes("HTTP 422")
        ? "Approval payload was rejected (422). Confirm incident_id and recommendation_id are valid UUIDs from the selected pending incident."
        : raw;
      setApprovalState({ loading: false, result: null, error: concise });
    }
  }

  const tabs = [
    { id: "home", label: "Dashboard" },
    { id: "copilot", label: "Copilot Studio" },
    { id: "approval", label: "Human Approval" },
    { id: "executive", label: "Executive Dashboard" },
    { id: "admin", label: "Admin Center" },
    { id: "trace", label: "Agent Flow" },
    { id: "safety", label: "Gateway Safety" },
    { id: "rag", label: "Message Bus" },
    { id: "finops", label: "FinOps" },
    { id: "closed", label: "Closed Tickets" },
    { id: "summary", label: "Incident Metadata Explorer" },
  ];

  const sidebarSections = [
    { id: "home", icon: "DB", shortLabel: "Dashboard", label: "Dashboard", tone: "ops" },
    { id: "approval", icon: "AL", shortLabel: "Approval", label: "Human Approval", tone: "risk" },
    { id: "executive", icon: "EX", shortLabel: "Executive", label: "Executive Dashboard", tone: "meta" },
    { id: "admin", icon: "AD", shortLabel: "Admin", label: "Admin Center", tone: "bus" },
    { id: "finops", icon: "FX", shortLabel: "FinOps", label: "FinOps", tone: "cost" },
  ];

  const currentRole = useMemo(() => normalizeRoleName(adminSession?.user?.role_name), [adminSession?.user?.role_name]);
  const projectOnboardingRows = useMemo(
    () => (onboardingState.rows || []).filter((row) => String(row?.provider_name || "").trim().toLowerCase() === "project"),
    [onboardingState.rows],
  );
  const ruleOnboardingRows = useMemo(
    () => (onboardingState.rows || []).filter((row) => {
      const provider = String(row?.provider_name || "").trim().toLowerCase();
      return provider === "existing_rule_sync" || provider === "new_rule_onboarding";
    }),
    [onboardingState.rows],
  );
  const allowedTabs = useMemo(() => ROLE_ALLOWED_TABS[currentRole] || ["home"], [currentRole]);
  const visibleSidebarSections = useMemo(() => sidebarSections.filter((tab) => allowedTabs.includes(tab.id)), [sidebarSections, allowedTabs]);
  const isAuthenticated = Boolean(String(adminSession.accessToken || "").trim());
  const isAdministrator = currentRole === "administrator";
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
    if (String(onboardingForm.deployment_mode || "").trim() === "gcp_cloud" && !String(onboardingForm.gcp_project_id || "").trim()) {
      errors.push("GCP Project ID is required for Google Cloud deployment.");
    }
    const isSetupMonitoringPath = String(onboardingForm.onboarding_path || "existing_monitoring").trim() === "setup_monitoring";
    if (isSetupMonitoringPath && !String(onboardingForm.rule_onboarding_plain_language || "").trim()) {
      errors.push("Add plain-English rule intent when the Setup Monitoring path is selected.");
    }
    return errors;
  }, [
    onboardingForm.name,
    onboardingForm.owner_team,
    onboardingForm.region,
    onboardingForm.deployment_mode,
    onboardingForm.gcp_project_id,
    onboardingForm.onboarding_path,
    onboardingForm.rule_onboarding_plain_language,
  ]);
  const onboardingAdvisory = useMemo(() => {
    const onboardingPath = String(onboardingForm.onboarding_path || "existing_monitoring").trim();
    if (onboardingPath === "existing_monitoring") {
      return "Existing monitoring path: configure your tool and send alerts to /alerts/alertmanager to trigger workflow.";
    }
    if (String(onboardingForm.deployment_mode || "").trim() !== "on_prem") {
      return "";
    }
    if (String(onboardingForm.monitoring_url || "").trim()) {
      return "";
    }
    return "Tool endpoint URL is optional now, but recommended for connectivity and rule simulation quality.";
  }, [onboardingForm.deployment_mode, onboardingForm.monitoring_url, onboardingForm.onboarding_path]);
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
  const onboardingNextAction = useMemo(() => {
    const onboardingPath = String(onboardingForm.onboarding_path || "existing_monitoring").trim();
    if (onboardingState.loading) {
      return "Step 2/4: Saving project and generating workflow artifacts...";
    }
    if (onboardingHasPendingDocumentApproval) {
      return "Step 3/4: Review generated documents below, then click Approve Documents.";
    }
    if (onboardingDocumentSummary.approved) {
      return "Step 4/4: Documents approved. You can continue with another update or proceed to advanced workflow management.";
    }
    return onboardingPath === "setup_monitoring"
      ? "Step 1/4: Complete project and monitoring-rule setup details, then click Create Project or Update Project."
      : "Step 1/4: Complete project details, save, then ingest alerts into landing pad.";
  }, [
    onboardingState.loading,
    onboardingHasPendingDocumentApproval,
    onboardingDocumentSummary.approved,
    onboardingForm.onboarding_path,
  ]);

  const adminWorkspaceCaptions = useMemo(() => ({
    users: "Manage users, roles, and credentials.",
    project: "Set up project monitoring using existing ingestion or guided rule creation.",
    projects: "Browse persisted project onboarding records.",
    alerts: "Author and bulk upload alert onboarding knowledge docs.",
  }), []);

  useEffect(() => {
    if (onboardingProjectMode === "new" || selectedOnboardingProject || !projectOnboardingRows.length) {
      return;
    }
    applyProjectOnboardingRow(projectOnboardingRows[0]);
  }, [onboardingProjectMode, selectedOnboardingProject, projectOnboardingRows]);

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
    } else if (workspace === "project") {
      setAdminWorkspace("project");
    } else if (workspace === "alerts") {
      setAdminWorkspace("alerts");
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
  ]);

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
      `<section><h2>Alert Details Workspace</h2>${renderHtmlTable(["Field", "Value"], selectedSummaryRows)}${renderHtmlTable(["Step", "Agent", "Action", "Decision", "Output", "Communicates To"], selectedEventsRows)}${renderHtmlTable(["Task", "Provider", "Model", "Input", "Output", "Cost USD"], selectedUsageRows)}${renderHtmlTable(["Field", "Value"], selectedRoutingRows)}<h3>Raw Payload</h3><pre>${htmlEscape(JSON.stringify(selectedAlertData.payload || {}, null, 2))}</pre></section>`,
      `<section><h2>Executive Dashboard</h2>${renderHtmlTable(["Metric", "Value"], executiveMetrics)}${renderHtmlTable(["Incident", "Service", "Risk", "Execution Mode", "Provider", "Status"], metadataRows)}</section>`,
      `<section><h2>Incident Metadata Explorer</h2>${renderHtmlTable(["Incident", "Service", "Risk", "Execution Mode", "Provider", "Status"], metadataRows)}</section>`,
      `<section><h2>Alerts and Quick Docs</h2>${renderHtmlTable(["Incident", "Service", "Severity", "Execution Mode", "Status"], pendingApprovalRows)}${renderHtmlTable(["Kind", "Score", "Title", "Path"], guidanceRows)}</section>`,
      `<section><h2>Agent Flow</h2>${renderHtmlTable(["Step", "Agent", "Action", "Decision", "Output", "Handoff"], traceRows)}${renderHtmlTable(["Time", "Path", "Status", "Decision", "Trace"], gatewayRows)}</section>`,
      `<section><h2>FinOps</h2>${renderHtmlTable(["Provider", "Calls", "Tokens", "Cost USD"], finopsProviderRows)}${renderHtmlTable(["Task", "Provider", "Model", "Input Tokens", "Output Tokens", "Total Cost USD"], finopsUsageRows)}</section>`,
      `<section><h2>Message Bus</h2>${renderHtmlTable(["Service", "Consumed", "Published", "Provider", "Status"], busActualRows)}${renderHtmlTable(["Service", "Consumes", "Publishes"], busConfigRows)}<h3>Observed Topics</h3><p>Published: ${htmlEscape(messageBusActual.published.join(", ") || "none")}</p><p>Consumed: ${htmlEscape(messageBusActual.consumed.join(", ") || "none")}</p></section>`,
      `<section><h2>Gateway Safety</h2>${renderHtmlTable(["Metric", "Value"], safetyMetrics)}${renderHtmlTable(["Time", "Path", "Status", "Decision", "Trace"], gatewayRows)}</section>`,
      `<section><h2>Closed Incidents</h2>${renderHtmlTable(["Incident", "Service", "Severity", "Status", "Closed At"], closedRows)}</section>`,
      `<section><h2>Admin Snapshot</h2>${renderHtmlTable(["Field", "Value"], [["Signed In User", adminSession?.user?.username || "-"], ["Users Loaded", adminUsers.rows.length], ["Onboarding Rows", onboardingState.rows.length], ["Bulk Upload Results", alertBulkState.results.length]])}</section>`,
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
            <p className="subtitle">Role access: Admin = all screens, L3 = all except Admin Center, L2 = all except Admin Center and Executive, L1 = Dashboard only.</p>
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
                  Download Full HTML Pack
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
          </section>

          {activeTab === "home" ? (
            <section className="grid single-col">
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
                <div className="table-wrap">
                  <table className="alert-stream-table">
                    <thead>
                      <tr>
                        <th>Alert ID</th>
                        <th>Time (UTC)</th>
                        <th>Name</th>
                        <th>Application</th>
                        <th>Service</th>
                        <th>Severity</th>
                        <th>Status</th>
                        <th>Docs</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleAlerts.map((row, index) => {
                        const rowId = String(row.alert_id || row.id || row.incident_id || index);
                        const fullAlertId = String(row.alert_id || row.id || row.incident_id || "-");
                        const compactAlertId = fullAlertId.length > 16 ? `${fullAlertId.slice(0, 8)}...${fullAlertId.slice(-6)}` : fullAlertId;
                        const severity = String(row.severity || "-").toUpperCase();
                        const status = String(row.status || row.state || "open");
                        const application = row.application || row.project_name || row.project || row.service || "-";
                        const documentAvailable = row.document_available;
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
                            <td>{row.name || row.alert_name || "-"}</td>
                            <td>{application}</td>
                            <td>{row.service || "-"}</td>
                            <td><span className={`pill severity-${severity.toLowerCase()}`}>{severity}</span></td>
                            <td><span className={`pill status-${status.toLowerCase()}`}>{status}</span></td>
                            <td>
                              {documentAvailable === false ? (
                                <button
                                  type="button"
                                  className="button-secondary pill status-blocked"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    openDocumentPrompt(row);
                                  }}
                                >
                                  Provide Docs
                                </button>
                              ) : documentAvailable === true ? (
                                <span className="pill status-resolved">Available</span>
                              ) : (
                                <span className="pill">-</span>
                              )}
                            </td>
                            <td>
                              <button
                                type="button"
                                className="button-secondary"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  openAlertDetails(row);
                                }}
                              >
                                Open
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                      {!visibleAlerts.length && !alerts.loading ? (
                        <tr>
                          <td colSpan={9}>No alerts available for {applicationToMonitor}.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </article>

              {docPromptAlert ? (
                <article className="panel" role="dialog" aria-label="Provide documents for alert">
                  <div className="panel-head">
                    <h3>Provide Documents</h3>
                    <button type="button" className="button-secondary" onClick={closeDocumentPrompt}>Close</button>
                  </div>
                  <p className="subtitle">
                    No knowledge base document was found for alert{" "}
                    <strong>{String(docPromptAlert.name || docPromptAlert.alert_name || docPromptAlert.alert_id || docPromptAlert.id || "-")}</strong>.
                    Upload a runbook or incident doc so future alerts of this type can be resolved automatically.
                  </p>
                  <form className="form" onSubmit={submitAlertOnboarding}>
                    <div className="filter-grid">
                      <label>Kind
                        <select value={alertOnboarding.kind} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, kind: e.target.value }))}>
                          <option value="incident">incident</option>
                          <option value="runbook">runbook</option>
                          <option value="deployment">deployment</option>
                          <option value="change">change</option>
                          <option value="dependency">dependency</option>
                        </select>
                      </label>
                      <label>Title<input value={alertOnboarding.title} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, title: e.target.value }))} /></label>
                      <label>Severity<select value={alertOnboarding.severity} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, severity: e.target.value }))}><option value="critical">critical</option><option value="high">high</option><option value="medium">medium</option><option value="low">low</option></select></label>
                    </div>
                    <label>Services (comma separated)<input value={alertOnboarding.services} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, services: e.target.value }))} /></label>
                    <label>Summary<textarea rows={2} value={alertOnboarding.summary} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, summary: e.target.value }))} /></label>
                    <label>Content<textarea rows={5} value={alertOnboarding.content} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, content: e.target.value }))} /></label>
                    <button className="button-primary" type="submit" disabled={alertOnboardingState.loading}>{alertOnboardingState.loading ? "Uploading..." : "Upload Document"}</button>
                  </form>
                  {alertOnboardingState.error ? <p className="error">{alertOnboardingState.error}</p> : null}
                </article>
              ) : null}

              {selectedAlertRow ? (
                <article className="panel" ref={alertDetailsRef}>
                  <div className="panel-head">
                    <h2>Alert Details Workspace</h2>
                  </div>
                  <div className="detail-context">
                    <span><strong>ID:</strong> {selectedAlertId}</span>
                    <span><strong>Service:</strong> {selectedAlertRow?.service || "-"}</span>
                    <span><strong>Severity:</strong> {String(selectedAlertRow?.severity || "-").toUpperCase()}</span>
                  </div>

                  <div className="detail-tabs">
                    {["summary", "timeline", "events", "finops", "api", "topics", "execution", "raw"].map((tab) => (
                      <button
                        key={`detail-${tab}`}
                        type="button"
                        className={`detail-tab ${homeDetailTab === tab ? "active" : ""}`}
                        onClick={() => setHomeDetailTab(tab)}
                      >
                        {tab === "summary" ? "Summary" : tab === "timeline" ? "Flow Timeline" : tab === "events" ? "Agent Events" : tab === "finops" ? "FinOps" : tab === "api" ? "API Gateway" : tab === "topics" ? "Message Bus Topics" : tab === "execution" ? "Execution Plan" : "Raw Payload"}
                      </button>
                    ))}
                  </div>

                  {selectedAlertData.loading ? <p className="subtitle">Loading selected alert details...</p> : null}
                  {selectedAlertData.error ? <p className="error">{selectedAlertData.error}</p> : null}

                  {homeDetailTab === "summary" ? (
                    <>
                      <div className="table-wrap">
                        <table>
                          <tbody>
                            <tr><th>Alert</th><td>{selectedAlertRow?.name || selectedAlertWorkflow?.alert?.name || "-"}</td></tr>
                            <tr><th>Incident</th><td>{selectedAlertWorkflow?.incident?.id || selectedAlertWorkflow?.incident_id || "-"}</td></tr>
                            <tr><th>Persisted Incident Status</th><td>{selectedStageCompleteness.data?.status || selectedAlertWorkflow?.incident?.status || "-"}</td></tr>
                            <tr><th>Closed At</th><td>{selectedAlertWorkflow?.incident?.closed_at || "-"}</td></tr>
                            <tr><th>Service</th><td>{selectedAlertRow?.service || selectedAlertWorkflow?.alert?.service || "-"}</td></tr>
                            <tr><th>Root Cause</th><td>{selectedAlertWorkflow?.recommendation?.root_cause || "-"}</td></tr>
                            <tr><th>Recommended Action</th><td>{selectedAlertWorkflow?.recommendation?.recommended_action || "-"}</td></tr>
                            <tr><th>Impact</th><td>{selectedAlertWorkflow?.recommendation?.impact || "-"}</td></tr>
                          </tbody>
                        </table>
                      </div>

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

                  {homeDetailTab === "timeline" ? (
                    <FlowTimelineGraph rows={selectedAlertTimelineRows} />
                  ) : null}

                  {homeDetailTab === "events" ? (
                    <AgentEventsGraph rows={selectedAlertEventsDisplay} />
                  ) : null}

                  {homeDetailTab === "finops" ? (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Task</th>
                            <th>Provider</th>
                            <th>Model</th>
                            <th>Input</th>
                            <th>Output</th>
                            <th>Cost USD</th>
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
                            </tr>
                          ))}
                          {!selectedAlertUsage.length ? (
                            <tr>
                              <td colSpan={6}>No FinOps usage found for selected alert.</td>
                            </tr>
                          ) : null}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {homeDetailTab === "api" ? (
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

                  {homeDetailTab === "topics" ? (
                    <TopicFlowGraph routing={selectedAlertRouting} timelineRows={selectedAlertTimelineRows} />
                  ) : null}

                  {homeDetailTab === "execution" ? (
                    <ExecutionPlanGraph plan={selectedExecutionPlan} />
                  ) : null}

                  {homeDetailTab === "raw" ? (
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
                    <button type="button" className="button-primary" onClick={() => openCopilotWorkspace("project")}>Open Onboarding</button>
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
                  <button type="button" className="button-secondary" onClick={() => openCopilotWorkspace("project")}>Project Onboarding</button>
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
                          <td>{row.status || "-"}</td>
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
                          <td>{row.status || "closed"}</td>
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
              <article className="panel">
                <div className="panel-head">
                  <h2>Admin Center</h2>
                  <p>User management, project onboarding, and alerts onboarding workspace.</p>
                </div>

                <div className="detail-tabs sticky-controls">
                  <button type="button" className={`detail-tab ${adminWorkspace === "users" ? "active" : ""}`} onClick={() => setAdminWorkspace("users")}>Users & Access</button>
                  <button type="button" className={`detail-tab ${adminWorkspace === "project" ? "active" : ""}`} onClick={() => setAdminWorkspace("project")}>Project Setup Flows</button>
                  <button type="button" className={`detail-tab ${adminWorkspace === "projects" ? "active" : ""}`} onClick={() => setAdminWorkspace("projects")}>Project Registry</button>
                  <button type="button" className={`detail-tab ${adminWorkspace === "alerts" ? "active" : ""}`} onClick={() => setAdminWorkspace("alerts")}>Alert Knowledge Base</button>
                </div>
                <p className="subtitle">{adminWorkspaceCaptions[adminWorkspace] || "Administrative workspace controls."}</p>

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
                      <div className="table-wrap">
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
                            {!adminUsers.rows.length ? <tr><td colSpan={6}>No users available.</td></tr> : null}
                          </tbody>
                        </table>
                      </div>
                    </article>

                    <article className="panel">
                      <h3>Create User</h3>
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
                    </article>

                    <article className="panel">
                      <h3>Modify User</h3>
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
                    </article>

                    <article className="panel">
                      <h3>Reset Password</h3>
                      <form className="form" onSubmit={resetAdminUserPassword}>
                        <div className="filter-grid">
                          <label>User ID<input value={adminResetPasswordForm.user_id || ""} readOnly /></label>
                          <label>New Password<input type="password" value={adminResetPasswordForm.new_password} onChange={(e) => setAdminResetPasswordForm((curr) => ({ ...curr, new_password: e.target.value }))} /></label>
                        </div>
                        <button className="button-primary" type="submit" disabled={!adminSession.accessToken || adminUsers.loading || !adminResetPasswordForm.user_id || !String(adminResetPasswordForm.new_password || "").trim()}>Reset Password</button>
                      </form>
                    </article>
                  </div>

                ) : null}

                {adminWorkspace === "project" ? (
                  <div className="grid single-col">
                    <article className="panel">
                      <div className="panel-head">
                        <h3>Project Onboarding</h3>
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
                      <p className="subtitle">Flow options: Existing Monitoring (ingest alerts to landing pad) or Setup Monitoring (generate rules, upload, and validate).</p>
                      <p className="subtitle"><strong>Next Action:</strong> {onboardingNextAction}</p>
                      {onboardingDocumentSummary.total > 0 ? (
                        <p className="subtitle">
                          <strong>Document Status:</strong> {onboardingDocumentSummary.total} generated, {onboardingDocumentSummary.approved ? "approved" : "pending approval"}.
                        </p>
                      ) : null}
                      {onboardingProjectMode === "existing" ? (
                        <div className="filter-grid">
                        <label>
                          Select Existing Project
                          <select
                            value={selectedOnboardingProject}
                            onChange={(e) => {
                              const nextProjectName = e.target.value;
                              setSelectedOnboardingProject(nextProjectName);
                              const row = projectOnboardingRows.find((item) => String(item?.project_name || "") === nextProjectName);
                              if (row) {
                                applyProjectOnboardingRow(row);
                              }
                            }}
                          >
                            <option value="">Select project</option>
                            {projectOnboardingRows.map((row, index) => {
                              const name = String(row?.project_name || "").trim() || `project-${index + 1}`;
                              return <option key={`project-select-${name}-${index}`} value={name}>{name}</option>;
                            })}
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
                        <div className="filter-grid">
                          <label>Project Name *<input placeholder="example-payments" value={onboardingForm.name} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, name: e.target.value, assignment_project: e.target.value }))} /></label>
                          <label>Owner Team *<input placeholder="sre-platform" value={onboardingForm.owner_team} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, owner_team: e.target.value }))} /></label>
                          <label>Environment<select value={onboardingForm.environment} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, environment: e.target.value }))}><option value="dev">dev</option><option value="staging">staging</option><option value="prod">prod</option></select></label>
                          <label>Region *<input placeholder="ap-south-1" value={onboardingForm.region} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, region: e.target.value }))} /></label>
                        </div>
                        <div className="filter-grid">
                          <label>Deployment
                            <select value={onboardingForm.deployment_mode} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, deployment_mode: e.target.value }))}>
                              <option value="on_prem">On-Prem</option>
                              <option value="gcp_cloud">Google Cloud</option>
                            </select>
                          </label>
                        </div>
                        {onboardingForm.deployment_mode === "gcp_cloud" ? (
                          <div className="filter-grid">
                            <label>GCP Project ID<input value={onboardingForm.gcp_project_id} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, gcp_project_id: e.target.value }))} /></label>
                            <label>GCP Region<input value={onboardingForm.gcp_region} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, gcp_region: e.target.value }))} /></label>
                            <label>Pub/Sub Topic<input value={onboardingForm.pubsub_topic} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, pubsub_topic: e.target.value }))} /></label>
                            <label>Pub/Sub Subscription<input value={onboardingForm.pubsub_subscription} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, pubsub_subscription: e.target.value }))} /></label>
                          </div>
                        ) : null}
                        <div className="filter-grid">
                          <label>
                            Onboarding Path
                            <select
                              value={onboardingForm.onboarding_path}
                              onChange={(e) => {
                                const nextPath = e.target.value;
                                setOnboardingForm((curr) => ({
                                  ...curr,
                                  onboarding_path: nextPath,
                                  start_rule_onboarding: nextPath === "setup_monitoring",
                                }));
                              }}
                            >
                              <option value="existing_monitoring">Existing Monitoring -&gt; Ingest Alerts To Landing Pad</option>
                              <option value="setup_monitoring">No Monitoring Yet -&gt; Create Rules &amp; Configure Prometheus</option>
                            </select>
                          </label>
                        </div>
                        <div className="filter-grid">
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
                          <label>
                            Tool Endpoint URL (optional)
                            <input
                              value={onboardingForm.monitoring_url}
                              placeholder="prometheus:9090"
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
                          </label>
                          <label>Assign User (optional)<input placeholder="username" value={onboardingForm.assignment_username} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, assignment_username: e.target.value }))} /></label>
                        </div>
                        {onboardingForm.deployment_mode === "gcp_cloud" ? (
                          <div className="filter-grid">
                            <label>Vertex Model Armor
                              <select value={String(onboardingForm.vertex_model_armor_enabled)} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, vertex_model_armor_enabled: e.target.value === "true" }))}>
                                <option value="false">disabled</option>
                                <option value="true">enabled</option>
                              </select>
                            </label>
                            <label>Model Armor Template<input value={onboardingForm.vertex_model_armor_template} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, vertex_model_armor_template: e.target.value }))} /></label>
                          </div>
                        ) : null}
                        <label>Assignment Project (auto)<input value={onboardingForm.name} readOnly /></label>
                        {onboardingForm.onboarding_path === "setup_monitoring" ? (
                          <label>
                            Rule Intent (Plain English)
                            <textarea
                              rows={5}
                              placeholder="Example: Alert when checkout API 5xx is above 3% for 5 minutes and route to SRE."
                              value={onboardingForm.rule_onboarding_plain_language}
                              onChange={(e) => {
                                const nextText = e.target.value;
                                setOnboardingForm((curr) => ({ ...curr, rule_onboarding_plain_language: nextText }));
                                setNewRulePipelineForm((curr) => ({ ...curr, requirements_text: nextText }));
                              }}
                            />
                          </label>
                        ) : <p className="subtitle">Alerts from your configured monitoring tool can be ingested into landing pad to trigger the remaining workflow.</p>}
                        <button className="button-primary" type="submit" disabled={onboardingState.loading || onboardingValidationErrors.length > 0 || onboardingHasPendingDocumentApproval}>
                          {onboardingState.loading ? "Saving..." : onboardingProjectMode === "new" ? "Create Project" : "Update Project"}
                        </button>
                      </form>
                      {onboardingState.error ? <p className="error">{onboardingState.error}</p> : null}
                      {onboardingState.success ? <p className="subtitle">{onboardingState.success}</p> : null}
                    </article>

                    <article className="panel">
                      <div className="panel-head">
                        <h3>Generated Documents Review</h3>
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
                            disabled={!onboardingGeneratedDocs.length || onboardingDocApprovalState.loading || onboardingDocApprovalState.approved}
                          >
                            {onboardingDocApprovalState.loading ? "Approving..." : onboardingDocApprovalState.approved ? "Approved" : "Approve Documents"}
                          </button>
                        </div>
                      </div>
                      <p className="subtitle">After Create/Update Project, review all generated documents below, then approve to ingest them.</p>
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
                    </article>

                    <article className="panel">
                      <h3>Rule Onboarding Status</h3>
                      <p className="subtitle">Rule onboarding is optional. If enabled above, plain-language requirements are converted into tool-specific rules and documentation automatically.</p>
                      <h3>Step-by-Step Workflow Progress</h3>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Step</th>
                              <th>Status</th>
                              <th>What Happened</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(onboardingWorkflowSteps.length ? onboardingWorkflowSteps : (
                              String(onboardingForm.onboarding_path || "existing_monitoring").trim() === "setup_monitoring"
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
                            )).map((row) => {
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
                                </tr>
                              );
                            })}
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
                      {onboardingRuleRunState.result ? <pre className="result">{JSON.stringify(onboardingRuleRunState.result, null, 2)}</pre> : null}
                    </article>

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
                                  <td>{String(Boolean(row.supports_simulation))}</td>
                                  <td>{String(Boolean(row.supports_dashboard_refs))}</td>
                                </tr>
                              ))}
                              {!onboardingRuleCapabilities.rows.length && !onboardingRuleCapabilities.loading ? (
                                <tr>
                                  <td colSpan={5}>No capabilities loaded yet.</td>
                                </tr>
                              ) : null}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    </article>
                  </div>

                ) : null}

                {adminWorkspace === "projects" ? (
                  <div className="grid single-col">
                    <article className="panel">
                      <div className="panel-head">
                        <h3>Saved Projects</h3>
                        <button type="button" className="button-secondary" onClick={loadOnboardingAdminData}>
                          Refresh
                        </button>
                      </div>
                      <p className="subtitle">Manage existing projects here. Use Modify to open Project Onboarding with the selected project prefilled.</p>
                      <div className="table-wrap">
                        <table>
                          <thead><tr><th>Project</th><th>Owner</th><th>Environment</th><th>Updated</th><th>Action</th></tr></thead>
                          <tbody>
                            {projectOnboardingRows.slice(0, 100).map((row, index) => (
                              <tr key={`saved-project-row-${index}`}>
                                <td>{row.project_name || "-"}</td>
                                <td>{row.owner_team || "-"}</td>
                                <td>{row.environment || "-"}</td>
                                <td>{row.updated_at || row.created_at || "-"}</td>
                                <td>
                                  <div style={{ display: "flex", gap: 8 }}>
                                    <button
                                      type="button"
                                      className="button-secondary"
                                      onClick={() => {
                                        setOnboardingProjectMode("existing");
                                        applyProjectOnboardingRow(row);
                                        setAdminWorkspace("project");
                                      }}
                                    >
                                      Modify
                                    </button>
                                    <button type="button" className="button-secondary" onClick={() => deleteProjectOnboarding(row.project_name)}>
                                      Delete
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))}
                            {!projectOnboardingRows.length ? <tr><td colSpan={5}>No saved projects available.</td></tr> : null}
                          </tbody>
                        </table>
                      </div>
                    </article>
                  </div>
                ) : null}

                {adminWorkspace === "alerts" ? (
                  <div className="grid single-col">
                    <article className="panel">
                      <h3>Alerts Onboarding</h3>
                      <p className="subtitle">Create onboarding knowledge docs for alert types and runbook guidance.</p>
                      <form className="form" onSubmit={submitAlertOnboarding}>
                        <div className="filter-grid">
                          <label>Kind
                            <select value={alertOnboarding.kind} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, kind: e.target.value }))}>
                              <option value="incident">incident</option>
                              <option value="runbook">runbook</option>
                              <option value="deployment">deployment</option>
                              <option value="change">change</option>
                              <option value="dependency">dependency</option>
                            </select>
                          </label>
                          <label>Title<input value={alertOnboarding.title} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, title: e.target.value }))} /></label>
                          <label>Alert Type<input value={alertOnboarding.alert_type} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, alert_type: e.target.value }))} /></label>
                          <label>Severity<select value={alertOnboarding.severity} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, severity: e.target.value }))}><option value="critical">critical</option><option value="high">high</option><option value="medium">medium</option><option value="low">low</option></select></label>
                        </div>
                        <label>Services (comma separated)<input value={alertOnboarding.services} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, services: e.target.value }))} /></label>
                        <label>Summary<textarea rows={2} value={alertOnboarding.summary} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, summary: e.target.value }))} /></label>
                        <label>Content<textarea rows={5} value={alertOnboarding.content} onChange={(e) => setAlertOnboarding((curr) => ({ ...curr, content: e.target.value }))} /></label>
                        <button className="button-primary" type="submit" disabled={alertOnboardingState.loading}>{alertOnboardingState.loading ? "Saving..." : "Create Alert Onboarding Doc"}</button>
                      </form>
                      {alertOnboardingState.error ? <p className="error">{alertOnboardingState.error}</p> : null}
                      {alertOnboardingState.result ? <pre className="result">{JSON.stringify(alertOnboardingState.result, null, 2)}</pre> : null}
                    </article>

                    <article className="panel">
                      <h3>Bulk Insert From Excel</h3>
                      <p className="subtitle">Upload .xlsx, .xls, or .csv with columns: kind, title, summary, content, services, severity, alert_type.</p>
                      <div className="search-row">
                        <a className="button-secondary" href="/alerts_onboarding_bulk_template.csv" download>
                          Download Template
                        </a>
                      </div>
                      <label>
                        Excel File
                        <input type="file" accept=".xlsx,.xls,.csv" onChange={onAlertBulkFileSelected} />
                      </label>
                      {alertBulkState.fileName ? <p className="subtitle">Loaded: {alertBulkState.fileName}</p> : null}
                      {alertBulkState.error ? <p className="error">{alertBulkState.error}</p> : null}

                      <div className="panel-head">
                        <h3>Parsed Rows</h3>
                        <button className="button-primary" type="button" onClick={submitAlertOnboardingBulk} disabled={alertBulkState.loading || !alertBulkState.parsedRows.length}>
                          {alertBulkState.loading ? "Uploading..." : "Upload Parsed Rows"}
                        </button>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr><th>Line</th><th>Title</th><th>Kind</th><th>Status</th><th>Validation</th></tr>
                          </thead>
                          <tbody>
                            {alertBulkState.parsedRows.map((row) => (
                              <tr key={`bulk-parse-${row.line}`}>
                                <td>{row.line}</td>
                                <td>{row.payload.title || "-"}</td>
                                <td>{row.payload.kind || "-"}</td>
                                <td><span className={`pill ${row.valid ? "status-closed" : "status-failed"}`}>{row.valid ? "Ready" : "Invalid"}</span></td>
                                <td>{row.errors.length ? row.errors.join("; ") : "OK"}</td>
                              </tr>
                            ))}
                            {!alertBulkState.parsedRows.length ? <tr><td colSpan={5}>No file parsed yet.</td></tr> : null}
                          </tbody>
                        </table>
                      </div>

                      <h3>Upload Results</h3>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr><th>Line</th><th>Title</th><th>Status</th><th>Message</th></tr>
                          </thead>
                          <tbody>
                            {alertBulkState.results.map((row, index) => (
                              <tr key={`bulk-result-${index}`}>
                                <td>{row.line}</td>
                                <td>{row.title}</td>
                                <td><span className={`pill ${row.status === "success" ? "status-closed" : "status-failed"}`}>{row.status}</span></td>
                                <td>{row.message}</td>
                              </tr>
                            ))}
                            {!alertBulkState.results.length ? <tr><td colSpan={4}>No upload attempted yet.</td></tr> : null}
                          </tbody>
                        </table>
                      </div>
                    </article>
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
                          <td>{row.status || "-"}</td>
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
                  <h2>Human Approval & Alerts</h2>
                  <p>Pending approvals, recent alerts, and quick docs decision workspace.</p>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Incident</th>
                        <th>Title</th>
                        <th>Application</th>
                        <th>Service</th>
                        <th>Severity</th>
                        <th>Status</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {monitorScopedAlerts.slice(0, 40).map((row, index) => (
                        <tr key={row.alert_id || row.id || index}>
                          <td>{row.alert_id || row.id || row.incident_id || "-"}</td>
                          <td>{row.name || row.alert_name || row.description || "-"}</td>
                          <td>{row.application || row.project_name || row.project || row.service || "-"}</td>
                          <td>{row.service || "-"}</td>
                          <td>{String(row.severity || "").toUpperCase() || "-"}</td>
                          <td>{row.status || row.state || "open"}</td>
                          <td>
                            <button type="button" className="button-secondary" onClick={() => openAlertDetails(row)}>
                              Open
                            </button>
                          </td>
                        </tr>
                      ))}
                      {!monitorScopedAlerts.length ? (
                        <tr>
                          <td colSpan={7}>No recent alerts available for {applicationToMonitor}. Run a sample flow from Incident Summary.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>

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
                <div className="table-wrap">
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
                        const canQuickApprove = looksLikeUuid(incidentId) && looksLikeUuid(recommendationId);
                        const quickApproveBusy = approvalState.loading && selected && approvalForm.action === "approve";
                        const quickRejectBusy = approvalState.loading && selected && approvalForm.action === "reject";
                        const rejectExpanded = inlineRejectState.incidentId === incidentId;
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
                          <td>{row.status || "pending"}</td>
                          <td>
                            <button className="button-secondary" type="button" onClick={() => openAlertDetailsFromIncident(row)}>
                              Open
                            </button>
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
                              onClick={() => setInlineRejectState((current) => current.incidentId === incidentId ? { incidentId: "", comment: "" } : { incidentId, comment: "" })}
                              disabled={!canQuickApprove || approvalState.loading}
                              title={canQuickApprove ? "Reject this incident with a comment" : "Recommendation ID unavailable. Use Sync From Approval API first."}
                              style={{ marginLeft: 8 }}
                            >
                              {rejectExpanded ? "Cancel Reject" : "Reject"}
                            </button>
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
                          <td>{row.status || "closed"}</td>
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
