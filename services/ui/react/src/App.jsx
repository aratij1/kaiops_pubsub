import { useEffect, useMemo, useState } from "react";
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

const PREFERENCE_STORAGE_KEY = "kaiops.ui.preferences.v1";
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

const ROLE_ALLOWED_TABS = {
  administrator: ["home", "copilot", "approval", "executive", "admin", "trace", "safety", "rag", "finops", "closed", "summary"],
  l1_operator: ["approval"],
  l2_engineer: ["home", "copilot", "approval", "executive", "trace", "safety", "rag", "finops", "closed", "summary"],
  l3_engineer: ["home", "copilot", "approval", "executive", "trace", "safety", "rag", "finops", "closed", "summary"],
  executive: ["home", "copilot", "approval", "executive", "trace", "safety", "rag", "finops", "closed", "summary"],
};

function normalizeRoleName(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_");
}

function extractObservedRoutingMetrics(workflow) {
  if (!workflow || typeof workflow !== "object") {
    return {};
  }
  const events = Array.isArray(workflow.events) ? workflow.events : [];
  const orchestratorEvent = [...events]
    .reverse()
    .find((item) => String(item?.agent || "").trim().toLowerCase() === "orchestrator agent");

  if (!orchestratorEvent || typeof orchestratorEvent !== "object") {
    return {};
  }

  const metrics = typeof orchestratorEvent.metrics === "object" ? { ...orchestratorEvent.metrics } : {};
  const decision = typeof orchestratorEvent.decision === "object" ? orchestratorEvent.decision : {};

  return {
    ...metrics,
    workflow: metrics.workflow || decision.workflow,
    next_action: metrics.next_action || decision.next_action,
    requires_approval: metrics.requires_approval ?? decision.requires_approval,
    risk_tier: metrics.risk_tier || decision.risk_tier,
    execution_mode: metrics.execution_mode || decision.execution_mode,
    policy_version: metrics.policy_version || decision.policy_version,
    message_bus_provider: metrics.message_bus_provider || decision.message_bus_provider,
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

function filterAlertsForMonitor(rows, applicationToMonitor) {
  const target = String(applicationToMonitor || "").trim().toLowerCase();
  const alertRows = Array.isArray(rows) ? rows : [];
  if (!target) {
    return alertRows;
  }
  return alertRows.filter((row) => {
    const candidates = [
      row?.application,
      row?.project,
      row?.project_name,
      row?.service,
      row?.source,
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
    const candidates = [
      row?.application,
      row?.project,
      row?.project_name,
      row?.service,
      row?.source,
      row?.provider_name,
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
  const defaultMonitorApplications = ["payments", "checkout", "orders-db", "inventory"];
  const [applicationToMonitor, setApplicationToMonitor] = useState("payments");
  const [monitorApplications, setMonitorApplications] = useState(defaultMonitorApplications);
  const [activeTab, setActiveTab] = useState("home");
  const [uiDensity, setUiDensity] = useState("comfortable");
  const [health, setHealth] = useState({ loading: false, ok: false, message: "Not checked" });
  const [alerts, setAlerts] = useState({ loading: false, rows: [], error: "" });
  const [incidentMetadata, setIncidentMetadata] = useState({ loading: false, rows: [], error: "" });
  const [closedIncidents, setClosedIncidents] = useState({ loading: false, rows: [], error: "" });
  const [flows, setFlows] = useState({ loading: false, rows: [], error: "" });
  const [gatewaySummary, setGatewaySummary] = useState({ loading: false, data: {}, error: "" });
  const [gatewayRecent, setGatewayRecent] = useState({ loading: false, rows: [], error: "" });
  const [ragDocs, setRagDocs] = useState({ loading: false, rows: [], error: "" });
  const [guidanceQuery, setGuidanceQuery] = useState("");
  const [guidanceState, setGuidanceState] = useState({ loading: false, rows: [], error: "" });
  const [submitState, setSubmitState] = useState({ loading: false, result: null, error: "" });
  const [workflowState, setWorkflowState] = useState({ loading: false, result: null, error: "" });
  const [approvalState, setApprovalState] = useState({ loading: false, result: null, error: "" });
  const [approvalFilter, setApprovalFilter] = useState("all");
  const [approvalIncidentContext, setApprovalIncidentContext] = useState({
    loading: false,
    incident_id: "",
    payload: null,
    error: "",
  });
  const [collapsedGroups, setCollapsedGroups] = useState({ monitor: false, context: false, view: false, sections: false });
  const [selectedAlertId, setSelectedAlertId] = useState("");
  const [selectedApprovalIncidentId, setSelectedApprovalIncidentId] = useState("");
  const [selectedAlertData, setSelectedAlertData] = useState({ loading: false, payload: null, error: "" });
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
  });
  const [onboardingState, setOnboardingState] = useState({ loading: false, connectivity: {}, rows: [], error: "", success: "" });
  const [alertOnboarding, setAlertOnboarding] = useState({
    kind: "incident",
    title: "New Alert Onboarding",
    summary: "",
    content: "Provide troubleshooting and escalation steps for this alert scenario.",
    services: "payments",
    severity: "high",
    alert_type: "availability",
  });
  const [alertOnboardingState, setAlertOnboardingState] = useState({ loading: false, result: null, error: "" });
  const [alertBulkState, setAlertBulkState] = useState({
    fileName: "",
    loading: false,
    parsedRows: [],
    results: [],
    error: "",
  });

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
      const payload = await fetchJson("/api-gateway/alerts/all?limit=50");
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
    setSelectedAlertData({ loading: true, payload: null, error: "" });
    try {
      const payload = await fetchJson(`/monitoring-adapter/alerts/${normalized}/processed-result`);
      setSelectedAlertData({ loading: false, payload, error: "" });
    } catch (error) {
      setSelectedAlertData({ loading: false, payload: null, error: error.message });
    }
  }

  function openAlertDetails(row) {
    const alertId = row?.alert_id || row?.id || row?.incident_id;
    if (!alertId) {
      return;
    }
    setSelectedAlertId(String(alertId));
    setHomeDetailTab("summary");
    loadAlertDetails(alertId);
  }

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
        setSelectedAlertData({ loading: false, payload: null, error: "" });
      }
      return;
    }
    const selectedExists = scopedRows.some(
      (row) => String(row?.alert_id || row?.id || row?.incident_id || "") === selectedAlertId
    );
    if (selectedExists) {
      return;
    }
    openAlertDetails(scopedRows[0]);
  }, [activeTab, alerts.rows, applicationToMonitor, selectedAlertId, selectedAlertData.payload, selectedAlertData.error]);

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
        .map((row) => String(row?.application || row?.project_name || row?.project || row?.service || "").trim())
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
    setActiveTab("approval");
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
      setOnboardingForm((curr) => ({
        ...curr,
        name: String(project?.name || curr.name || "").trim(),
        owner_team: String(project?.owner_team || curr.owner_team || "").trim(),
        environment: String(project?.environment || curr.environment || "prod").trim(),
        region: String(project?.region || curr.region || "").trim(),
        deployment_mode: String(connectivity?.deployment_mode || curr.deployment_mode || "on_prem").trim(),
        prometheus_url: String(connectivity?.prometheus_url || curr.prometheus_url || "").trim(),
        new_relic_url: String(connectivity?.new_relic_url || curr.new_relic_url || "").trim(),
        datadog_url: String(connectivity?.datadog_url || curr.datadog_url || "").trim(),
        gcp_project_id: String(connectivity?.gcp_project_id || curr.gcp_project_id || "").trim(),
        gcp_region: String(connectivity?.gcp_region || curr.gcp_region || "").trim(),
        pubsub_topic: String(connectivity?.pubsub_topic || curr.pubsub_topic || "").trim(),
        pubsub_subscription: String(connectivity?.pubsub_subscription || curr.pubsub_subscription || "").trim(),
        vertex_model_armor_enabled: Boolean(connectivity?.vertex_model_armor_enabled ?? curr.vertex_model_armor_enabled),
        vertex_model_armor_template: String(connectivity?.vertex_model_armor_template || curr.vertex_model_armor_template || "").trim(),
      }));
      setOnboardingState({ loading: false, connectivity, rows: Array.isArray(rows) ? rows : [], error: "", success: "" });
    } catch (error) {
      setOnboardingState({ loading: false, connectivity: {}, rows: [], error: error.message, success: "" });
    }
  }

  async function saveOnboardingConnectivity(event) {
    event.preventDefault();
    setOnboardingState((current) => ({ ...current, loading: true, error: "", success: "" }));
    try {
      const username = String(onboardingForm.assignment_username || "").trim();
      const assignmentProject = String(onboardingForm.assignment_project || "").trim();
      const userAssignments = username && assignmentProject ? { [username]: [assignmentProject] } : {};
      const payload = {
        project: {
          name: String(onboardingForm.name || "").trim(),
          owner_team: String(onboardingForm.owner_team || "").trim(),
          environment: String(onboardingForm.environment || "prod").trim(),
          region: String(onboardingForm.region || "").trim(),
        },
        deployment_mode: String(onboardingForm.deployment_mode || "on_prem").trim(),
        prometheus_url: String(onboardingForm.prometheus_url || "").trim(),
        new_relic_url: String(onboardingForm.new_relic_url || "").trim(),
        datadog_url: String(onboardingForm.datadog_url || "").trim(),
        gcp_project_id: String(onboardingForm.gcp_project_id || "").trim(),
        gcp_region: String(onboardingForm.gcp_region || "").trim(),
        pubsub_topic: String(onboardingForm.pubsub_topic || "").trim(),
        pubsub_subscription: String(onboardingForm.pubsub_subscription || "").trim(),
        vertex_model_armor_enabled: Boolean(onboardingForm.vertex_model_armor_enabled),
        vertex_model_armor_template: String(onboardingForm.vertex_model_armor_template || "").trim(),
        user_assignments: userAssignments,
      };
      await fetchJson("/api-gateway/onboarding/connectivity", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await loadOnboardingAdminData();
      setOnboardingState((current) => ({ ...current, success: "Project onboarding saved." }));
    } catch (error) {
      setOnboardingState((current) => ({ ...current, loading: false, error: error.message, success: "" }));
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
      };
      const response = await fetchJson("/api-gateway/rag/documents", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setAlertOnboardingState({ loading: false, result: response, error: "" });
      await loadRagDocs();
    } catch (error) {
      setAlertOnboardingState({ loading: false, result: null, error: error.message });
    }
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
    const payload = {
      applicationToMonitor,
      uiDensity,
      selectedFlow,
      activeTab,
      metadataFilters,
      closedFilters,
    };
    window.localStorage.setItem(PREFERENCE_STORAGE_KEY, JSON.stringify(payload));
  }, [applicationToMonitor, uiDensity, selectedFlow, activeTab, metadataFilters, closedFilters]);

  useEffect(() => {
    const onKeyDown = (event) => {
      const authenticated = Boolean(String(adminSession.accessToken || "").trim());
      if (!authenticated) {
        return;
      }
      const roleName = normalizeRoleName(adminSession?.user?.role_name);
      const roleTabs = ROLE_ALLOWED_TABS[roleName] || ["approval"];
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
    return monitorScopedAlerts.length ? monitorScopedAlerts : alerts.rows;
  }, [monitorScopedAlerts, alerts.rows]);

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
    const events = selectedAlertWorkflow?.events || [];
    return Array.isArray(events) ? events : [];
  }, [selectedAlertWorkflow]);

  const selectedAlertUsage = useMemo(() => {
    const usage = selectedAlertWorkflow?.recommendation?.metadata?.model_usage || [];
    return Array.isArray(usage) ? usage : [];
  }, [selectedAlertWorkflow]);

  const selectedAlertRouting = useMemo(() => extractObservedRoutingMetrics(selectedAlertWorkflow), [selectedAlertWorkflow]);

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

  const workflowEventRows = useMemo(() => {
    const mapped = panelWorkflowEvents
      .filter((event) => event && typeof event === "object")
      .sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0))
      .map((event) => {
        const decisionValue = event.decision;
        const outputValue = event.output;
        return {
          sequence: event.sequence || "-",
          agent: event.agent || "-",
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
      agent: "API Gateway",
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
    const observedAgents = new Set(events.map((item) => String(item?.agent || "").trim()));
    const observedProvider = String(observedRouting?.message_bus_provider || "").trim().toUpperCase() || "N/A";
    const approval = typeof workflow.approval === "object" ? workflow.approval : {};
    const remediation = typeof workflow.remediation_action === "object" ? workflow.remediation_action : {};
    const closure = typeof workflow.closure_report === "object" ? workflow.closure_report : {};
    const hasWorkflow = Boolean(workflow.alert || workflow.incident || events.length);

    const published = [];
    const consumed = [];
    const rows = SERVICE_TOPIC_FLOW.map((row) => {
      let isObserved = false;
      if (row.agent === "alert") {
        isObserved = hasWorkflow;
      } else if (observedAgents.has(row.agent)) {
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

    return { published, consumed, rows };
  }, [panelWorkflow, observedRouting]);

  const finopsByProvider = useMemo(() => {
    const grouped = new Map();
    panelWorkflowUsage.forEach((row) => {
      const key = String(row?.provider || "unknown");
      const current = grouped.get(key) || { provider: key, calls: 0, total_tokens: 0, total_cost_usd: 0 };
      current.calls += 1;
      current.total_tokens += Number(row?.input_tokens || 0) + Number(row?.output_tokens || 0);
      current.total_cost_usd += Number(row?.total_cost_usd || 0);
      grouped.set(key, current);
    });
    return Array.from(grouped.values());
  }, [panelWorkflowUsage]);

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
    return String(
      row?.recommendation_id
      || row?.recommended_action_id
      || row?.remediation_recommendation_id
      || row?.recommendation?.id
      || ""
    ).trim();
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
    return String(
      normalized.recommendation_id
      || recommendation.id
      || normalized.remediation_recommendation_id
      || normalized.recommended_action_id
      || ""
    ).trim();
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

  async function submitApproval(event) {
    event.preventDefault();
    setApprovalState({ loading: true, result: null, error: "" });
    try {
      const payload = {
        incident_id: String(approvalForm.incident_id || "").trim(),
        recommendation_id: String(approvalForm.recommendation_id || "").trim(),
        approver: String(approvalForm.approver || "").trim(),
        channel: String(approvalForm.channel || "web").trim(),
        comment: String(approvalForm.comment || "").trim() || null,
      };
      if (approvalForm.action === "modify") {
        payload.modified_action = String(approvalForm.modified_action || "").trim();
      }
      const response = await fetchJson(`/api-gateway/approval/${approvalForm.action}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setApprovalState({ loading: false, result: response, error: "" });
      await Promise.all([loadIncidentMetadata(), loadGatewayRecent(), loadGatewaySummary()]);
    } catch (error) {
      setApprovalState({ loading: false, result: null, error: error.message });
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
    { id: "copilot", icon: "CP", shortLabel: "Copilot", label: "Copilot Studio", tone: "meta" },
    { id: "approval", icon: "AL", shortLabel: "Approval", label: "Human Approval", tone: "risk" },
    { id: "executive", icon: "EX", shortLabel: "Executive", label: "Executive Dashboard", tone: "meta" },
    { id: "admin", icon: "AD", shortLabel: "Admin", label: "Admin Center", tone: "bus" },
    { id: "trace", icon: "AG", shortLabel: "Flow", label: "Agent Flow", tone: "ops" },
    { id: "safety", icon: "GW", shortLabel: "Safety", label: "Gateway Safety", tone: "risk" },
    { id: "rag", icon: "MB", shortLabel: "Bus", label: "Message Bus", tone: "bus" },
    { id: "finops", icon: "FX", shortLabel: "FinOps", label: "FinOps", tone: "cost" },
    { id: "closed", icon: "CL", shortLabel: "Tickets", label: "Closed Tickets", tone: "ops" },
    { id: "summary", icon: "MD", shortLabel: "Metadata", label: "Incident Metadata Explorer", tone: "meta" },
  ];

  const currentRole = useMemo(() => normalizeRoleName(adminSession?.user?.role_name), [adminSession?.user?.role_name]);
  const allowedTabs = useMemo(() => ROLE_ALLOWED_TABS[currentRole] || ["approval"], [currentRole]);
  const visibleSidebarSections = useMemo(() => sidebarSections.filter((tab) => allowedTabs.includes(tab.id)), [sidebarSections, allowedTabs]);
  const isAuthenticated = Boolean(String(adminSession.accessToken || "").trim());
  const isAdministrator = currentRole === "administrator";

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }
    if (allowedTabs.includes(activeTab)) {
      return;
    }
    setActiveTab(allowedTabs[0] || "approval");
  }, [isAuthenticated, allowedTabs, activeTab]);

  function toggleSidebarGroup(group) {
    setCollapsedGroups((current) => ({ ...current, [group]: !current[group] }));
  }

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
          ["LLM Calls", panelWorkflowUsage.length],
          [
            "Total Cost (USD)",
            panelWorkflowUsage
              .reduce((sum, row) => sum + Number(row?.total_cost_usd || 0), 0)
              .toFixed(6),
          ],
          ["Providers", new Set(panelWorkflowUsage.map((row) => row.provider).filter(Boolean)).size],
          ["Models", new Set(panelWorkflowUsage.map((row) => row.model).filter(Boolean)).size],
        ],
        refresh: () => runWorkflow(selectedFlow),
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
    panelWorkflowUsage,
    messageBusActual,
    observedRouting,
    gatewaySummary.data,
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
      `<section><h2>Alert Stream</h2>${renderHtmlTable(["Alert ID", "Name", "Application", "Service", "Severity", "Status"], monitorAlertsRows)}</section>`,
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
            <p className="subtitle">Role access: Admin = all screens, L2/L3 = all except Admin Center, L1 = Alerts only.</p>
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
            <p className="subtitle">Operator controls and navigation.</p>
          </div>

          <div className="sidebar-group">
            <div className="sidebar-group-head">
              <h3>Monitor</h3>
              <button type="button" className="sidebar-toggle" onClick={() => toggleSidebarGroup("monitor")}>
                {collapsedGroups.monitor ? "Show" : "Hide"}
              </button>
            </div>
            {!collapsedGroups.monitor ? (
              <>
                <label>
                  Application
                  <select value={applicationToMonitor} onChange={(e) => setApplicationToMonitor(e.target.value)}>
                    {monitorApplications.map((app) => (
                      <option key={app} value={app}>{app}</option>
                    ))}
                  </select>
                </label>
                <HealthBadge ok={health.ok} label={health.message} />
              </>
            ) : null}
          </div>

          <div className="sidebar-group actions-group">
            <h3>Quick Actions</h3>
            <div className="sidebar-actions">
              <button className="button-secondary" onClick={refreshAll}>Refresh</button>
              <button className="button-primary" onClick={checkHealth} disabled={health.loading}>
                {health.loading ? "Checking..." : "Health"}
              </button>
              <button className="button-secondary sidebar-action-wide" onClick={() => runWorkflow(selectedFlow)} disabled={workflowState.loading}>
                {workflowState.loading ? "Running Flow..." : "Run Selected Flow"}
              </button>
            </div>
            <p className="keyboard-hint">Shortcuts: Alt+1 Dashboard, Alt+2 Human Approval ... Alt+0 Metadata</p>
          </div>

          <div className="sidebar-group">
            <div className="sidebar-group-head">
              <h3>View</h3>
              <button type="button" className="sidebar-toggle" onClick={() => toggleSidebarGroup("view")}>
                {collapsedGroups.view ? "Show" : "Hide"}
              </button>
            </div>
            {!collapsedGroups.view ? (
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
            ) : null}
          </div>

          <div className="sidebar-group">
            <div className="sidebar-group-head">
              <h3>Current Context</h3>
              <button type="button" className="sidebar-toggle" onClick={() => toggleSidebarGroup("context")}>
                {collapsedGroups.context ? "Show" : "Hide"}
              </button>
            </div>
            {!collapsedGroups.context ? (
              <div className="context-list">
                <div className="context-row"><span>Selected Flow</span><strong>{selectedFlow || "-"}</strong></div>
                <div className="context-row"><span>Incident ID</span><strong>{latestIncidentId || "-"}</strong></div>
                <div className="context-row"><span>Recommendation ID</span><strong>{latestRecommendationId || "-"}</strong></div>
              </div>
            ) : null}
          </div>

          <div className="sidebar-group">
            <div className="sidebar-group-head">
              <h3>Sections</h3>
              <button type="button" className="sidebar-toggle" onClick={() => toggleSidebarGroup("sections")}>
                {collapsedGroups.sections ? "Show" : "Hide"}
              </button>
            </div>
            {!collapsedGroups.sections ? (
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
            ) : null}
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
                        <th>Name</th>
                        <th>Application</th>
                        <th>Service</th>
                        <th>Severity</th>
                        <th>Status</th>
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
                            <td>{row.name || row.alert_name || "-"}</td>
                            <td>{application}</td>
                            <td>{row.service || "-"}</td>
                            <td><span className={`pill severity-${severity.toLowerCase()}`}>{severity}</span></td>
                            <td><span className={`pill status-${status.toLowerCase()}`}>{status}</span></td>
                          </tr>
                        );
                      })}
                      {!visibleAlerts.length && !alerts.loading ? (
                        <tr>
                          <td colSpan={6}>No alerts available for {applicationToMonitor}.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </article>

              {selectedAlertRow ? (
                <article className="panel">
                  <div className="panel-head">
                    <h2>Alert Details Workspace</h2>
                  </div>
                  <div className="detail-context">
                    <span><strong>ID:</strong> {selectedAlertId}</span>
                    <span><strong>Service:</strong> {selectedAlertRow?.service || "-"}</span>
                    <span><strong>Severity:</strong> {String(selectedAlertRow?.severity || "-").toUpperCase()}</span>
                  </div>

                  <div className="detail-tabs">
                    {["summary", "events", "finops", "api", "topics", "execution", "raw"].map((tab) => (
                      <button
                        key={`detail-${tab}`}
                        type="button"
                        className={`detail-tab ${homeDetailTab === tab ? "active" : ""}`}
                        onClick={() => setHomeDetailTab(tab)}
                      >
                        {tab === "summary" ? "Summary" : tab === "events" ? "Agent Events" : tab === "finops" ? "FinOps" : tab === "api" ? "API Gateway" : tab === "topics" ? "Message Bus Topics" : tab === "execution" ? "Execution Plan" : "Raw Payload"}
                      </button>
                    ))}
                  </div>

                  {selectedAlertData.loading ? <p className="subtitle">Loading selected alert details...</p> : null}
                  {selectedAlertData.error ? <p className="error">{selectedAlertData.error}</p> : null}

                  {homeDetailTab === "summary" ? (
                    <div className="table-wrap">
                      <table>
                        <tbody>
                          <tr><th>Alert</th><td>{selectedAlertRow?.name || selectedAlertWorkflow?.alert?.name || "-"}</td></tr>
                          <tr><th>Incident</th><td>{selectedAlertWorkflow?.incident?.id || selectedAlertWorkflow?.incident_id || "-"}</td></tr>
                          <tr><th>Service</th><td>{selectedAlertRow?.service || selectedAlertWorkflow?.alert?.service || "-"}</td></tr>
                          <tr><th>Root Cause</th><td>{selectedAlertWorkflow?.recommendation?.root_cause || "-"}</td></tr>
                          <tr><th>Recommended Action</th><td>{selectedAlertWorkflow?.recommendation?.recommended_action || "-"}</td></tr>
                          <tr><th>Impact</th><td>{selectedAlertWorkflow?.recommendation?.impact || "-"}</td></tr>
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {homeDetailTab === "events" ? (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Step</th>
                            <th>Agent</th>
                            <th>Action</th>
                            <th>Decision</th>
                            <th>Output</th>
                            <th>Communicates To</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedAlertEvents.map((event, index) => (
                            <tr key={`evt-${index}`}>
                              <td>{event.sequence || "-"}</td>
                              <td>{event.agent || "-"}</td>
                              <td>{event.action || "-"}</td>
                              <td>{typeof event.decision === "object" ? JSON.stringify(event.decision) : String(event.decision || "-")}</td>
                              <td>{typeof event.output === "object" ? JSON.stringify(event.output) : String(event.output || "-")}</td>
                              <td>{event.communicates_to || "-"}</td>
                            </tr>
                          ))}
                          {!selectedAlertEvents.length ? (
                            <tr>
                              <td colSpan={6}>No events found for selected alert.</td>
                            </tr>
                          ) : null}
                        </tbody>
                      </table>
                    </div>
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
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {homeDetailTab === "topics" ? (
                    <div className="table-wrap">
                      <table>
                        <tbody>
                          <tr><th>Observed Provider</th><td>{selectedAlertRouting?.message_bus_provider || "-"}</td></tr>
                          <tr><th>Workflow</th><td>{selectedAlertRouting?.workflow || "-"}</td></tr>
                          <tr><th>Next Action</th><td>{selectedAlertRouting?.next_action || "-"}</td></tr>
                          <tr><th>Execution Mode</th><td>{selectedAlertRouting?.execution_mode || "-"}</td></tr>
                          <tr><th>Risk Tier</th><td>{selectedAlertRouting?.risk_tier || "-"}</td></tr>
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {homeDetailTab === "execution" ? (
                    <div className="table-wrap">
                      <table>
                        <tbody>
                          <tr><th>Action</th><td>{selectedAlertWorkflow?.recommendation?.recommended_action || "-"}</td></tr>
                          <tr><th>Rationale</th><td>{selectedAlertWorkflow?.recommendation?.rationale || "-"}</td></tr>
                          <tr><th>Requires Approval</th><td>{String(selectedAlertRouting?.requires_approval ?? "-")}</td></tr>
                          <tr><th>Commands</th><td>{Array.isArray(selectedAlertWorkflow?.recommendation?.commands) ? selectedAlertWorkflow.recommendation.commands.join(" | ") : "-"}</td></tr>
                        </tbody>
                      </table>
                    </div>
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
                  <div className="stat-card"><strong>Critical</strong><span>{monitorScopedAlerts.filter((row) => String(row?.severity || "").toLowerCase() === "critical").length}</span></div>
                  <div className="stat-card"><strong>High</strong><span>{monitorScopedAlerts.filter((row) => String(row?.severity || "").toLowerCase() === "high").length}</span></div>
                  <div className="stat-card"><strong>Closed Incidents</strong><span>{closedIncidents.rows.length}</span></div>
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
                        </tr>
                      ))}
                      {!monitorScopedIncidentMetadata.length ? (
                        <tr>
                          <td colSpan={5}>No executive rows available for {applicationToMonitor}.</td>
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
                  <button type="button" className={`detail-tab ${adminWorkspace === "users" ? "active" : ""}`} onClick={() => setAdminWorkspace("users")}>User Management</button>
                  <button type="button" className={`detail-tab ${adminWorkspace === "project" ? "active" : ""}`} onClick={() => setAdminWorkspace("project")}>Project Onboarding</button>
                  <button type="button" className={`detail-tab ${adminWorkspace === "alerts" ? "active" : ""}`} onClick={() => setAdminWorkspace("alerts")}>Alerts Onboarding</button>
                </div>

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
                      <div className="panel-head"><h3>Project Onboarding</h3><button type="button" className="button-secondary" onClick={loadOnboardingAdminData}>Refresh</button></div>
                      <form className="form" onSubmit={saveOnboardingConnectivity}>
                        <div className="filter-grid">
                          <label>Project<input value={onboardingForm.name} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, name: e.target.value }))} /></label>
                          <label>Owner Team<input value={onboardingForm.owner_team} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, owner_team: e.target.value }))} /></label>
                          <label>Environment<select value={onboardingForm.environment} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, environment: e.target.value }))}><option value="dev">dev</option><option value="staging">staging</option><option value="prod">prod</option></select></label>
                          <label>Region<input value={onboardingForm.region} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, region: e.target.value }))} /></label>
                        </div>
                        <div className="filter-grid">
                          <label>Deployment Mode
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
                          <label>Prometheus URL<input value={onboardingForm.prometheus_url} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, prometheus_url: e.target.value }))} /></label>
                          <label>New Relic URL<input value={onboardingForm.new_relic_url} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, new_relic_url: e.target.value }))} /></label>
                          <label>Datadog URL<input value={onboardingForm.datadog_url} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, datadog_url: e.target.value }))} /></label>
                          <label>Assign Username<input value={onboardingForm.assignment_username} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, assignment_username: e.target.value }))} /></label>
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
                        <label>Assignment Project<input value={onboardingForm.assignment_project} onChange={(e) => setOnboardingForm((curr) => ({ ...curr, assignment_project: e.target.value }))} /></label>
                        <button className="button-primary" type="submit" disabled={onboardingState.loading}>{onboardingState.loading ? "Saving..." : "Save Onboarding"}</button>
                      </form>
                      {onboardingState.error ? <p className="error">{onboardingState.error}</p> : null}
                      {onboardingState.success ? <p className="subtitle">{onboardingState.success}</p> : null}
                    </article>

                    <article className="panel">
                      <h3>Saved Onboarding State</h3>
                      <div className="table-wrap">
                        <table>
                          <thead><tr><th>Project</th><th>Provider</th><th>Status</th><th>Updated</th></tr></thead>
                          <tbody>
                            {(onboardingState.rows || []).slice(0, 50).map((row, index) => (
                              <tr key={`onboarding-row-${index}`}>
                                <td>{row.project_name || "-"}</td>
                                <td>{row.provider_name || "-"}</td>
                                <td>{row.status || "-"}</td>
                                <td>{row.updated_at || row.created_at || "-"}</td>
                              </tr>
                            ))}
                            {!onboardingState.rows.length ? <tr><td colSpan={4}>No onboarding rows available.</td></tr> : null}
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
                        </tr>
                      ))}
                      {!monitorScopedIncidentMetadata.length && !incidentMetadata.loading ? (
                        <tr>
                          <td colSpan={6}>No incidents available for {applicationToMonitor}. Run one sample flow from Home.</td>
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
                        </tr>
                      ))}
                      {!monitorScopedAlerts.length ? (
                        <tr>
                          <td colSpan={6}>No recent alerts available for {applicationToMonitor}. Run a sample flow from Incident Summary.</td>
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
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPendingApprovals.map((row, index) => {
                        const incidentId = approvalIncidentId(row);
                        const recommendationId = approvalRecommendationId(row);
                        const selected = incidentId && incidentId === selectedApprovalIncidentId;
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
                        </tr>
                      )})}
                      {!filteredPendingApprovals.length ? (
                        <tr>
                          <td colSpan={7}>No pending approvals for this filter and monitor scope.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
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
                      {panelWorkflowUsage.map((row, index) => (
                        <tr key={`${row.task || "task"}-${index}`}>
                          <td>{row.task || "-"}</td>
                          <td>{row.provider || "-"}</td>
                          <td>{row.model || "-"}</td>
                          <td>{row.input_tokens || "-"}</td>
                          <td>{row.output_tokens || "-"}</td>
                          <td>{row.total_cost_usd || "-"}</td>
                        </tr>
                      ))}
                      {!panelWorkflowUsage.length ? (
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
                  <button className="button-secondary" onClick={() => { loadGatewaySummary(); loadGatewayRecent(); }}>
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
