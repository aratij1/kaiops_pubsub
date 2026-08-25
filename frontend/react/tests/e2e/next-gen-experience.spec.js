import { expect, test } from "@playwright/test";

const INCIDENT_ID = "11111111-1111-4111-8111-111111111111";
const RECOMMENDATION_ID = "22222222-2222-4222-8222-222222222222";
const APPLICATION_ID = "33333333-3333-4333-8333-333333333333";

const json = (payload, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(payload),
});

function incident(overrides = {}) {
  const now = new Date().toISOString();
  return {
    incident_id: INCIDENT_ID,
    alert_id: "ALERT-NEXT-1",
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
    if (path.startsWith("/incidents/metadata")) {
      const requestedStatus = url.searchParams.get("status");
      const include = !requestedStatus || String(currentIncident.status).toLowerCase().includes(requestedStatus);
      return route.fulfill(json({ data: { rows: include ? [currentIncident] : [] } }));
    }
    if (path.startsWith("/incidents/closed")) return route.fulfill(json({ data: { rows: String(currentIncident.status).toLowerCase() === "recovered" ? [currentIncident] : [] } }));
    if (path === `/approval/incident/${INCIDENT_ID}`) return route.fulfill(json({ data: { incident_id: INCIDENT_ID, recommendation_id: RECOMMENDATION_ID, status: currentIncident.status } }));
    if (path === "/approval/approve" && method === "POST") {
      currentIncident = incident({ status: "executing", approval_status: "approved", execution_mode: "human-approved" });
      return route.fulfill(json({ data: { id: "44444444-4444-4444-8444-444444444444", incident_id: INCIDENT_ID, recommendation_id: RECOMMENDATION_ID, decision: "approved" } }));
    }
    if (path === "/remediation/execute" && method === "POST") {
      currentIncident = incident({ status: "recovered", approval_status: "approved", execution_mode: "human-approved", latest_event_type: "validation_completed" });
      return route.fulfill(json({ data: { status: "succeeded", incident_id: INCIDENT_ID } }));
    }
    if (path.startsWith("/alerts/all")) return route.fulfill(json({ data: { rows: options.alerts || [] } }));
    if (path.startsWith("/landing-pad/recent") || path.startsWith("/alerts/applications")) return route.fulfill(json({ data: { rows: [] } }));
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
  await expect(page.getByRole("heading", { level: 2, name: "Integration Launchpad" })).toBeVisible();
  await expect(page.locator(".integration-launchpad .execution-stepper li.is-complete")).toHaveCount(4);
  await expect(page.locator(".integration-launchpad .execution-stepper")).toContainText("Activate");
});
