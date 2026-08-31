import { expect, test } from "@playwright/test";

const INCIDENT_ID = "11111111-1111-4111-8111-111111111111";
const ALERT_ID = "66666666-6666-4666-8666-666666666666";
const RECOMMENDATION_ID = "22222222-2222-4222-8222-222222222222";
const APPLICATION_ID = "33333333-3333-4333-8333-333333333333";
const PLAN_ID = "44444444-4444-4444-8444-444444444444";
const PLAN_FINGERPRINT = `sha256:${"a".repeat(64)}`;
const ANALYSIS_REQUEST_ID = "88888888-8888-4888-8888-888888888888";

const json = (payload, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(payload),
});

function incident(overrides = {}) {
  const now = new Date().toISOString();
  return {
    incident_id: INCIDENT_ID,
    alert_id: ALERT_ID,
    recommendation_id: RECOMMENDATION_ID,
    title: "Checkout latency affecting payments",
    summary: "18% of checkout attempts are failing",
    service: "checkout-api",
    application: "KaiOps",
    project_name: "KaiOps",
    environment: "production",
    severity: "critical",
    status: "awaiting_approval",
    approval_status: "pending",
    execution_mode: "human-approval",
    risk_tier: "low",
    origin_system: "prometheus",
    created_at: now,
    updated_at: now,
    latest_event_at: now,
    latest_event_type: "recommendation_ready",
    projection_payload: {
      application: "KaiOps",
      customer_impact: "18% of checkout attempts are failing",
      root_cause: "Database connection pool exhaustion",
      confidence: 0.91,
      owner: "payments-oncall",
      analysis: {
        supporting_signals: ["Connection wait time rose before checkout errors", "Database saturation is isolated to checkout-api"],
        ruled_out: ["No deployment change was recorded"],
      },
      recommendation: {
        id: RECOMMENDATION_ID,
        title: "Restart checkout-api canary pods",
        why: "A bounded restart releases exhausted connections while keeping most production traffic untouched.",
        risk_tier: "low",
        blast_radius: "5% traffic",
        target: "checkout-api production",
        strategy: "canary",
        expected_duration: "3 minutes",
        rollback: "automatic",
        execution_plan: {
          execution_ready: true,
          target: "checkout-api production",
          strategy: "canary",
          expected_duration: "3 minutes",
          rollback: "automatic",
          safety_envelope: {
            allowed_scope: "1 pod",
            traffic_exposure: "5%",
            automatic_stop: "enabled",
            rollback: "enabled",
            approval: "required",
            stop_conditions: ["Error rate exceeds 3%"],
            rollback_conditions: ["Latency fails to improve within 90 seconds"],
          },
        },
      },
      validation: {
        status: "Recovery verified",
        before: { error_rate: "12.4%", p95_latency: "2.9s" },
        after: { error_rate: "0.8%", p95_latency: "640ms" },
        targets: { error_rate: "<1%", p95_latency: "<800ms" },
      },
    },
    ...overrides,
  };
}

async function installScenario(page, options = {}) {
  let currentIncident = options.incident || incident();
  let governedPlanReady = options.approvalPlan !== false;
  const approvalReadiness = options.approvalReadiness || {
    state: "execution_eligible",
    missing: [],
    decision_id: "readiness-decision-1",
    signature: "hmac-sha256:signed-readiness",
    plan_id: PLAN_ID,
    plan_fingerprint: PLAN_FINGERPRINT,
    recommendation_id: RECOMMENDATION_ID,
  };
  const application = {
    id: APPLICATION_ID,
    name: "Checkout Platform",
    tenant_id: "default",
    owner_team: "payments-oncall",
    owner_email: "payments@example.com",
    environment: "prod",
    namespace: "payments",
    region: "us-east-1",
    technology: "kubernetes",
    metrics_endpoint: "https://metrics.example.com/checkout",
    monitoring_platform: "prometheus",
    status: "dashboard_created",
  };
  const onboardingEvents = [
    "application.onboard.requested",
    "application.discovery.completed",
    "application.metrics.validated",
    "application.rules.generated",
    "application.prometheus.updated",
    "application.validation.completed",
    "application.dashboard.created",
  ].map((event_type, index) => ({ event_type, created_at: new Date(Date.now() - (7 - index) * 60_000).toISOString() }));

  await page.route("**/api-gateway/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api-gateway/, "");
    const method = route.request().method();

    if (path === "/auth/config") return route.fulfill(json({ mode: "local", local_development_only: true }));
    if (path === "/auth/login") return route.fulfill(json({ access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }));
    if (path === "/healthz") return route.fulfill(json({ status: "ok", service: "api-gateway" }));
    if (path === "/model/providers/status") {
      if (options.modelUnavailable) return route.fulfill(json({ detail: "provider status unavailable" }, 503));
      return route.fulfill(json({ data: { status: "healthy", providers: { "azure-openai": { configured: true, healthy: true, circuit_open: false, model: "gpt-4o" } } } }));
    }
    if (path.startsWith("/observability/summary") || path.startsWith("/observability/recent")) {
      if (options.trustUnavailable) return route.fulfill(json({ detail: "trust integration unavailable" }, 503));
      return route.fulfill(json(path.includes("summary") ? { total_events: 3, allowed: 2, review: 1, blocked: 0 } : { events: [] }));
    }
    if (path === "/applications") return route.fulfill(json({ data: { rows: options.withApplication ? [application] : [] } }));
    if (path === `/applications/${APPLICATION_ID}/history`) return route.fulfill(json({ rows: onboardingEvents }));
    if (path === `/applications/${APPLICATION_ID}/validations`) return route.fulfill(json({ rows: [{ status: "passed", created_at: new Date().toISOString() }] }));
    if (path === `/applications/${APPLICATION_ID}/dashboards`) return route.fulfill(json({ rows: [{ title: "Checkout golden signals" }] }));
    if (path === "/incidents/inbox/feed") {
      if (options.unifiedPages) {
        const selectedPage = url.searchParams.get("cursor") === "page-2" ? options.unifiedPages[1] : options.unifiedPages[0];
        return route.fulfill(json({ data: selectedPage }));
      }
      const incidentRows = [...(options.incidents || [currentIncident])].reduce((rows, row) => {
        const key = row.correlation_id || row.incident_id;
        const existing = rows.find((candidate) => (candidate.correlation_id || candidate.incident_id) === key);
        if (existing) existing.total_occurrence_count = Number(existing.total_occurrence_count || 1) + 1;
        else rows.push({ ...row, total_occurrence_count: Number(row.total_occurrence_count || 1) });
        return rows;
      }, []);
      const alertRows = (options.alerts || []).filter((row) => !row.incident_id);
      return route.fulfill(json({ data: {
        rows: [
          ...incidentRows.map((row, index) => ({ record_type: "incident", score: 100 - index, row })),
          ...alertRows.map((row, index) => ({ record_type: "alert", score: 50 - index, row })),
        ],
        next_cursor: null,
        previous_cursor: null,
        total_count: incidentRows.length,
        filtered_count: incidentRows.length + alertRows.length,
        view_counts: { all: incidentRows.length + alertRows.length },
      } }));
    }
    if (path.startsWith("/incidents/groups")) {
      const requestedStatus = url.searchParams.get("status");
      const include = !requestedStatus || String(currentIncident.status).toLowerCase().includes(requestedStatus);
      const rows = include ? (options.incidents || [currentIncident]) : [];
      return route.fulfill(json({ data: { rows, total_count: rows.length, filtered_count: rows.length } }));
    }
    if (path.startsWith("/incidents/closed")) return route.fulfill(json({ data: { rows: String(currentIncident.status).toLowerCase() === "recovered" ? [currentIncident] : [] } }));
    if (path === `/incidents/${INCIDENT_ID}/manual-close` && method === "POST") {
      return route.fulfill(json({ data: { status: "closed", closure_kind: "manual", technical_recovery_verified: false, jira: { transitioned: false } } }));
    }
    if (path === `/approval/incident/${INCIDENT_ID}`) return route.fulfill(json({ data: {
      incident_id: INCIDENT_ID,
      recommendation_id: RECOMMENDATION_ID,
      status: currentIncident.status,
      incident_investigation: {
        readiness: { approval_ready: true, blocking_reasons: [] },
        readiness_blocks: [],
      },
      recommendation: {
        id: RECOMMENDATION_ID,
        metadata: governedPlanReady ? {
          execution_plan: {
            tenant_id: "default",
            incident_id: INCIDENT_ID,
            plan_id: PLAN_ID,
            plan_fingerprint: PLAN_FINGERPRINT,
          },
        } : {},
      },
      approval_readiness: approvalReadiness,
    } }));
    if (path === `/analysis/alerts/${ALERT_ID}/regenerate` && method === "POST") {
      governedPlanReady = true;
      return route.fulfill(json({ request_id: ANALYSIS_REQUEST_ID, status: "accepted", delivery: "published", alert_id: ALERT_ID, incident_id: INCIDENT_ID, expected_recommendation_id: RECOMMENDATION_ID, analysis_mode: "fresh", context_strategy: "realtime", poll_after_ms: 1 }));
    }
    if (path === `/analysis/requests/${ANALYSIS_REQUEST_ID}/status`) return route.fulfill(json({ request_id: ANALYSIS_REQUEST_ID, incident_id: INCIDENT_ID, recommendation_id: RECOMMENDATION_ID, status: "complete", ready: true }));
    if (path === "/approval/approve" && method === "POST") {
      const body = route.request().postDataJSON();
      if (body.plan_id !== PLAN_ID || body.plan_fingerprint !== PLAN_FINGERPRINT) {
        return route.fulfill(json({ detail: "Approval is not bound to the current execution plan fingerprint." }, 409));
      }
      currentIncident = incident({ status: "executing", approval_status: "approved", execution_mode: "human-approved" });
      return route.fulfill(json({ data: { id: "55555555-5555-4555-8555-555555555555", incident_id: INCIDENT_ID, recommendation_id: RECOMMENDATION_ID, decision: "approved" } }));
    }
    if (path === "/remediation/execute" && method === "POST") {
      currentIncident = incident({ status: "recovered", approval_status: "approved", execution_mode: "human-approved", latest_event_type: "validation_completed" });
      return route.fulfill(json({ data: { status: "succeeded", incident_id: INCIDENT_ID } }));
    }
    if (path.startsWith("/alerts/all")) return route.fulfill(json({ data: { rows: options.alerts || [] } }));
    if (path.startsWith("/landing-pad/recent")) return route.fulfill(json({ data: { rows: options.landingAlerts || [] } }));
    if (path.startsWith("/alerts/applications")) return route.fulfill(json({ data: { rows: [] } }));
    if (path.startsWith("/operations/queue-health")) return route.fulfill(json({ status: "healthy", healthy: true }));
    return route.fulfill(json({ data: { rows: [] }, rows: [], summary: {}, items: [] }));
  });

  return { updateIncident: (next) => { currentIncident = next; } };
}

async function signIn(page, path) {
  await page.goto(path);
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.locator(".kai-shell")).toBeVisible({ timeout: 30_000 });
}

test("unified inbox combines incidents and unlinked signals without losing source-specific triage", async ({ page }) => {
  test.setTimeout(90_000);
  const now = new Date().toISOString();
  await installScenario(page, { alerts: [{
    id: "ALERT-UNLINKED-2",
    alert_id: "ALERT-UNLINKED-2",
    name: "Payment gateway error-rate spike",
    description: "The payment gateway crossed its error-rate threshold.",
    service: "payments-api",
    application: "KaiOps",
    project_name: "KaiOps",
    environment: "production",
    severity: "high",
    status: "active",
    origin_system: "prometheus",
    incident_disposition: "unique",
    created_at: now,
    received_at: now,
  }] });
  await signIn(page, "/incidents");

  await expect(page.locator(".incident-list-heading").getByRole("heading", { name: "Unified Inbox" })).toBeVisible();
  const sourceTabs = page.getByRole("tablist", { name: "Inbox source" });
  await expect(sourceTabs.getByRole("tab", { name: /All activity/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".unified-inbox-card")).toHaveCount(2);
  await expect(page.locator(".unified-inbox-card").first()).toContainText("Checkout latency affecting payments");
  await expect(page.locator(".unified-inbox-card.is-signal")).toContainText("Payment gateway error-rate spike");
  await expect(page.locator(".unified-inbox-card.is-signal")).toContainText("Awaiting correlation");

  await sourceTabs.getByRole("tab", { name: /Signals/ }).click();
  await expect(page.getByRole("table")).toContainText("Payment gateway error-rate spike");
  await expect(page.getByRole("table")).not.toContainText("Checkout latency affecting payments");
  await sourceTabs.getByRole("tab", { name: /^Incidents\b/ }).click();
  await expect(page.getByRole("table")).toContainText("Checkout latency affecting payments");

  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("signal to RCA to approval to canary validation and closure remains evidence-backed", async ({ page }) => {
  await installScenario(page);
  await signIn(page, `/incidents/${INCIDENT_ID}`);

  await expect(page.getByRole("heading", { name: "Checkout latency affecting payments" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Database connection pool exhaustion" })).toBeVisible();
  await expect(page.getByText("91%", { exact: true })).toBeVisible();
  await expect(page.getByText("5% traffic", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Review safety preview" }).click();
  await expect(page.getByText("Error rate exceeds 3%", { exact: true })).toBeVisible();

  const approve = page.getByRole("button", { name: "Approve & let Kai resolve" });
  await expect(approve).toBeEnabled();
  await approve.click();
  await expect(page.locator(".ic-kai-state")).toContainText("Recovery recorded", { timeout: 30_000 });
  await expect(page.locator(".ic-validation")).toContainText("Recovery verified");
  await expect(page.locator(".ic-validation")).toContainText("12.4%");
  await expect(page.locator(".ic-validation")).toContainText("0.8%");
});

test("unified inbox retains KaiMS signals hidden by Live Alerts presentation filters", async ({ page }) => {
  const now = new Date().toISOString();
  await page.addInitScript(() => window.localStorage.setItem("kaiops.ui.preferences.v1", JSON.stringify({
    applicationToMonitor: "KaiOps",
    ingestionStreamSection: "active",
    ingestionStreamFilters: { timeRange: "all", severity: "info", application: "selected", environment: "all" },
  })));
  await installScenario(page, { alerts: [{
    id: "77777777-7777-4777-8777-777777777777", alert_id: "77777777-7777-4777-8777-777777777777",
    name: "KaiMSFreshSignal", service: "kaims-api", application: "KaiOps", project_name: "KaiOps",
    environment: "production", severity: "critical", status: "active", incident_disposition: "unique",
    created_at: now, received_at: now,
  }] });
  await signIn(page, "/alerts");
  await expect(page.getByText("No alerts match this view")).toBeVisible();
  await page.locator(".operations-workflow-nav button").filter({ hasText: "Unified Inbox" }).click();
  await expect(page.locator(".unified-inbox-card.is-signal")).toContainText("KaiMSFreshSignal");
});

test("legacy approval can generate a fresh governed plan before approval", async ({ page }) => {
  test.setTimeout(90_000);
  await page.addInitScript(() => window.localStorage.setItem("kaiops.ui.preferences.v1", JSON.stringify({ applicationToMonitor: "KaiOps" })));
  await installScenario(page, { approvalPlan: false, approvalReadiness: { state: "blocked", missing: ["valid_plan"], decision_id: "legacy-plan", signature: "hmac-sha256:legacy" } });
  await signIn(page, "/approvals");
  await page.locator(".approval-ticket").click();
  await expect(page.getByText("Fresh governed plan required")).toBeVisible();
  await page.getByRole("button", { name: "Generate governed plan" }).click();
  await expect(page.getByText(PLAN_ID, { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("body")).not.toContainText("Approval unavailable");
});

test("approval queue keeps every decision packet legible when the list scrolls", async ({ page }) => {
  const incidents = Array.from({ length: 12 }, (_, index) => incident({
    incident_id: `11111111-1111-4111-8111-${String(index + 1).padStart(12, "0")}`,
    service: index < 6 ? "remediation-engine" : "api-gateway",
    environment: "production",
    risk_tier: "high",
  }));
  await installScenario(page, { incidents });
  await page.setViewportSize({ width: 1040, height: 580 });
  await signIn(page, "/approvals");

  const tickets = page.locator(".approval-ticket");
  await expect(tickets).toHaveCount(12);
  const geometry = await tickets.evaluateAll((rows) => rows.slice(0, 8).map((row) => {
    const bounds = row.getBoundingClientRect();
    const children = Array.from(row.children).map((child) => child.getBoundingClientRect());
    return {
      top: bounds.top,
      bottom: bounds.bottom,
      height: bounds.height,
      childrenContained: children.every((child) => child.top >= bounds.top && child.bottom <= bounds.bottom),
    };
  }));
  expect(geometry.every((row) => row.height >= 76 && row.childrenContained)).toBeTruthy();
  expect(geometry.slice(1).every((row, index) => row.top >= geometry[index].bottom)).toBeTruthy();
  await expect(page.getByLabel("Queue filter")).toBeVisible();
});

test("a newer live occurrence retains its canonical incident link into Unified Inbox", async ({ page }) => {
  test.setTimeout(90_000);
  const fingerprint = "linked-alert-fingerprint";
  const now = Date.now();
  await installScenario(page, {
    alerts: [{
      id: ALERT_ID, alert_id: ALERT_ID, incident_id: INCIDENT_ID,
      name: "CheckoutLatencyHigh", service: "checkout-api", application: "KaiOps", environment: "production",
      severity: "critical", created_at: new Date(now - 60_000).toISOString(),
      labels: { alertname: "CheckoutLatencyHigh", alert_fingerprint: fingerprint, service: "checkout-api", application: "KaiOps" },
    }],
    landingAlerts: [{
      file: "20260826T050115Z_checkout_latency.json", name: "CheckoutLatencyHigh", service: "checkout-api",
      severity: "critical", received_at: new Date(now).toISOString(),
      labels: { alertname: "CheckoutLatencyHigh", alert_fingerprint: fingerprint, service: "checkout-api", application: "KaiOps" },
    }],
  });
  await signIn(page, "/alerts");

  const linkedAction = page.getByRole("button", { name: "Open in Unified Inbox" });
  await expect(linkedAction).toBeVisible();
  await linkedAction.click();
  await expect(page).toHaveURL(new RegExp(`/incidents/${INCIDENT_ID}$`));
  await expect(page.getByRole("heading", { name: "Unified Inbox" })).toBeVisible();
  await expect(page.getByText("Checkout latency affecting payments", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Incident inbox" }).click();
  await expect(page.locator(".unified-inbox-card.is-incident")).toHaveCount(1);
  await expect(page.locator(".unified-inbox-card.is-signal")).toHaveCount(0);
});

test("Unified Inbox collapses incident projections with the same durable correlation", async ({ page }) => {
  const correlationId = "4759f3fa-970d-4cd4-b888-6f513fbf4297";
  const fingerprint = "8c86631aff1f2ce527dddb7d27eed7e3468eb38a1f7d4b0d7dbc4b65fb3a82ab";
  const first = incident({
    incident_id: "1e6e0b97-cbcc-4c28-a60e-fbeccdbba930",
    alert_id: "a9b53b21-c9c0-4807-9826-c4d00fb83b24",
    title: "KaiOpsHighLatencyP99",
    service: "api-gateway",
    correlation_id: correlationId,
    fingerprint,
  });
  const second = incident({
    incident_id: "c74f3fe4-8cfd-4b64-9bc9-f19131177438",
    alert_id: "0a4599b4-c54d-41a4-bf81-528f338450a0",
    title: "KaiOpsHighLatencyP99",
    service: "api-gateway",
    correlation_id: correlationId,
    fingerprint,
  });
  await installScenario(page, { incidents: [first, second] });
  await signIn(page, "/incidents");

  await expect(page.locator(".unified-inbox-card.is-incident")).toHaveCount(1);
  await expect(page.getByText("2 occurrences", { exact: true })).toBeVisible();
});

test("separate recurrence ownership remains separate and an active incident is not hidden by terminal history", async ({ page }) => {
  const fingerprint = "recurring-checkout-latency";
  const recovered = incident({
    incident_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    alert_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    title: "Recovered checkout recurrence",
    correlation_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    fingerprint,
    status: "resolved",
  });
  const active = incident({
    incident_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    alert_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    title: "Active checkout recurrence",
    correlation_id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
    fingerprint,
    status: "investigating",
  });
  await installScenario(page, { incidents: [recovered, active] });
  await signIn(page, "/incidents");
  await page.getByRole("tab", { name: /^Incidents/ }).click();

  await expect(page.getByRole("button", { name: "Recovered checkout recurrence" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Active checkout recurrence" })).toBeVisible();
  await expect(page.locator(".incident-summary-table tbody tr")).toHaveCount(2);
});

test("unified feed cursor pagination preserves totals without repeating alerts", async ({ page }) => {
  const firstAlert = { id: "alert-page-1", name: "First paged signal", service: "checkout-api", severity: "high", status: "active" };
  const secondAlert = { id: "alert-page-2", name: "Second paged signal", service: "payments-api", severity: "critical", status: "active" };
  const pageShape = { total_count: 11, filtered_count: 11, view_counts: { all: 11 } };
  await installScenario(page, { unifiedPages: [
    { ...pageShape, rows: [{ record_type: "alert", score: 10, row: firstAlert }], next_cursor: "page-2", previous_cursor: null },
    { ...pageShape, rows: [{ record_type: "alert", score: 9, row: secondAlert }], next_cursor: null, previous_cursor: "page-1" },
  ] });
  await signIn(page, "/incidents");

  await expect(page.getByText("First paged signal", { exact: true })).toBeVisible();
  await expect(page.getByText("Showing 1-10 of 11", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Second paged signal", { exact: true })).toBeVisible();
  await expect(page.getByText("Showing 11-11 of 11", { exact: true })).toBeVisible();
  await expect(page.getByText("First paged signal", { exact: true })).toHaveCount(0);
  await expect(page.locator(".unified-inbox-card.is-signal")).toHaveCount(1);
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByText("First paged signal", { exact: true })).toBeVisible();
  await expect(page.getByText("Second paged signal", { exact: true })).toHaveCount(0);
});

test("Full investigation retains the clicked incident while alert details hydrate", async ({ page }) => {
  await installScenario(page);
  await signIn(page, `/incidents/${INCIDENT_ID}`);

  await page.getByRole("button", { name: "Open full investigation" }).click();
  await expect(page).toHaveURL(new RegExp(`workspace=alert&alert_id=${ALERT_ID}`));
  await expect(page.locator(".alert-details-cockpit").getByRole("heading", { name: "Incident Response" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Alert Details Cockpit" })).toHaveCount(0);
});

test("signed backend readiness blocks diagnostic plans from approval", async ({ page }) => {
  await installScenario(page, {
    approvalReadiness: {
      state: "blocked",
      missing: ["current_credentials", "rollback_readiness", "policy_acceptance", "evidence_threshold"],
      decision_id: "readiness-decision-blocked",
      signature: "hmac-sha256:signed-blocked-readiness",
    },
  });
  await signIn(page, `/incidents/${INCIDENT_ID}`);

  await expect(page.getByRole("button", { name: "Approve & let Kai resolve" })).toBeDisabled();
});

test("autonomous resolution exposes the active execution state without a false approval", async ({ page }) => {
  await installScenario(page, { incident: incident({ status: "remediating", approval_status: "not_required", execution_mode: "autonomous" }) });
  await signIn(page, `/incidents/${INCIDENT_ID}`);
  await expect(page.locator(".ic-journey li.is-current")).toContainText("Executing");
  await expect(page.locator(".ic-kai-state")).toContainText("remediating");
  await expect(page.getByRole("button", { name: "Approve & let Kai resolve" })).toHaveCount(0);
});

test("failed remediation presents failure evidence and rollback truth", async ({ page }) => {
  const failed = incident({
    status: "rollback_failed",
    approval_status: "approved",
    projection_payload: { ...incident().projection_payload, failure_reason: "Canary error rate crossed the automatic stop threshold" },
  });
  await installScenario(page, { incident: failed });
  await signIn(page, `/incidents/${INCIDENT_ID}`);
  await expect(page.getByRole("alert")).toContainText("automatic stop threshold");
  await expect(page.locator(".ic-journey li.is-failed")).toContainText("Executing");
  await expect(page.getByRole("button", { name: "Rollback unavailable" })).toBeDisabled();
});

test("human control remains available through the governed technical workspace", async ({ page }) => {
  await installScenario(page, { incident: incident({ status: "remediating", approval_status: "approved" }) });
  await signIn(page, `/incidents/${INCIDENT_ID}`);
  await expect(page.getByRole("heading", { name: "Stay in command" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Take control in governed workspace" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Rollback unavailable" })).toBeDisabled();
});

test("RCA visibly changes after newly published evidence is refreshed", async ({ page }) => {
  const scenario = await installScenario(page);
  await signIn(page, `/incidents/${INCIDENT_ID}`);
  await expect(page.getByRole("heading", { name: "Database connection pool exhaustion" })).toBeVisible();
  scenario.updateIncident(incident({ projection_payload: { ...incident().projection_payload, root_cause: "A leaked database session in checkout-api" }, latest_event_type: "new_evidence_received" }));
  await page.getByRole("button", { name: "Refresh incident" }).click();
  await expect(page.getByRole("heading", { name: "A leaked database session in checkout-api" })).toBeVisible();
});

test("integration telemetry outage degrades the Trust Center without enabling controls", async ({ page }) => {
  await installScenario(page, { trustUnavailable: true });
  await signIn(page, "/automation");
  await expect(page.getByText("Trust telemetry is partially unavailable")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Emergency stop unavailable" })).toBeDisabled();
});

test("model outage is globally visible while deterministic operations remain available", async ({ page }) => {
  await installScenario(page, { modelUnavailable: true });
  await signIn(page, "/");
  const status = page.getByRole("status").filter({ hasText: "AI capability degraded" });
  await expect(status).toContainText("deterministic monitoring remains active", { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Operations Overview" })).toBeVisible();
});

test("production approval remains usable on a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installScenario(page);
  await signIn(page, `/incidents/${INCIDENT_ID}`);
  await expect(page.getByText("production", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve & let Kai resolve" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("onboarding evidence drives readiness and activation without estimated capabilities", async ({ page }) => {
  await installScenario(page, { withApplication: true });
  await signIn(page, "/applications");
  await page.getByRole("button", { name: "Inspect" }).click();
  const readiness = page.locator(".k-readiness");
  await expect(readiness).toContainText("Operational readiness");
  await expect(readiness).toContainText("100%");
  await expect(readiness.getByText("Knowledge").locator("..")).toContainText("—");

  await page.getByRole("button", { name: "Integrations", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Integrations" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Provider connections" })).toBeVisible();
  await expect(page.getByLabel("Project ID")).toHaveValue("demo-project");
  await expect(page.getByRole("button", { name: "Add simulator connection" })).toBeEnabled();
  await expect(page.locator("body")).not.toContainText(/estimated/i);
});

test("manual closure sends only operator intent while identity remains server-derived", async ({ page }) => {
  await installScenario(page);
  await signIn(page, `/incidents?incident_id=${INCIDENT_ID}`);

  await expect(page.getByRole("heading", { name: "Close incident with audit comment" })).toBeVisible();
  const comment = "Evidence remains inconclusive; close administratively without a recovery claim.";
  await page.getByLabel("Closure comment").fill(comment);
  const requestPromise = page.waitForRequest((request) => (
    request.method() === "POST"
    && new URL(request.url()).pathname.endsWith(`/incidents/${INCIDENT_ID}/manual-close`)
  ));
  await page.getByRole("button", { name: "Close incident and update Jira" }).click();
  const request = await requestPromise;

  expect(request.postDataJSON()).toEqual({ comment });
  expect(request.headers().authorization).toBe("Bearer admin-token");
  await expect(page.getByText("Incident closed; no linked Jira ticket required an update.")).toBeVisible();
});
