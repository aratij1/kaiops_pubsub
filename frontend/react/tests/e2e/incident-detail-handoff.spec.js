import { expect, test } from "@playwright/test";

test("a policy block awaiting human review does not permanently lock Resolve", async ({ page }) => {
  test.setTimeout(90_000);
  const alertId = "99999999-9999-4999-8999-999999999999";
  const incidentId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const recommendationId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    let body = { data: [], rows: [], summary: {}, items: [] };
    if (path === "/auth/config") body = { mode: "local", local_development_only: true };
    else if (path === "/auth/login") body = { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } };
    else if (path === "/healthz") body = { status: "ok" };
    else if (path.startsWith("/incidents/metadata")) body = { rows: [{ incident_id: incidentId, alert_id: alertId, recommendation_id: recommendationId, title: "Retry blocked incident", service: "orchestrator", environment: "prod", status: "awaiting_approval" }] };
    else if (path.startsWith(`/alerts/${alertId}/processed-result`)) body = { data: {
      alert: { id: alertId, name: "PolicyEngineUnavailable", service: "orchestrator", environment: "prod", severity: "critical" },
      incident: { id: incidentId, service: "orchestrator", environment: "prod", status: "investigating" },
      recommendation: { id: recommendationId, recommended_action: "Restart policy engine", metadata: { execution_plan: { execution_ready: true, commands: ["ansible-playbook playbooks/restart-service.yml -e service=policy-engine -e env=prod"], validation_commands: ["curl -fsS http://policy-engine:8000/healthz"], connection: { connector: { connector_id: "auto-orchestrator", endpoint: "http://api-gateway:8000", secret_ref: "vault://kaiops/prod/default-token" } } } } },
      remediation_action: { id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", action_type: "restart_service", status: "policy_blocked", metadata: { policy_blocked: true, recommendation_id: recommendationId } },
      context: { metadata: {} }, timeline: [],
    } };
    else if (path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/incidents");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.getByRole("button", { name: "Retry blocked incident", exact: true }).click();
  const evidenceTab = page.getByRole("tab", { name: "Evidence, RCA, and impact" });
  await evidenceTab.click();
  await expect(page.getByRole("heading", { name: "Context and evidence" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Leading explanation" })).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Recommendation confidence" })).toBeVisible();
  await page.locator(".context-workspace").screenshot({ path: "artifacts/context-workspace-redesign.png" });
  const resolveTab = page.getByRole("tab", { name: "Resolve incident" });
  await expect(resolveTab).not.toContainText("execution blocked");
  await expect(resolveTab).not.toContainText("policy_blocked");
  await expect(resolveTab).toContainText("Waiting for approval");
  await expect(page.locator(".incident-decision-strip")).toContainText("Manual approval is ready for review");
  await page.getByRole("button", { name: "Review and approve" }).click();
  await expect(page.getByRole("heading", { name: "Remediation recommendation" })).toBeVisible();
  await expect(page.getByText("AI confidence", { exact: true })).toBeVisible();
  await expect(page.getByText("Approval gate", { exact: true })).toBeVisible();
  await page.locator(".resolution-decision-brief").screenshot({ path: "artifacts/resolution-workspace-redesign.png" });
  await expect(page.locator(".cockpit-stage-navigation .detail-tab.active")).toContainText("Resolve");
  await expect(page.getByText("Diagnostic plan — execution unavailable", { exact: true })).toHaveCount(0);
  await page.locator(".remediation-workspace").screenshot({ path: "artifacts/resolution-command-center.png" });
  await page.locator("details.resolution-configuration-details > summary").click();
  await page.locator("details.remediation-editor-panel > summary").click();
  await expect(page.locator(".governed-plan-view pre").filter({ hasText: "ansible-playbook playbooks/restart-service.yml" })).toContainText(
    "-e service=policy-engine -e env=prod",
  );
});

test("incident summary and detail use the same effective lifecycle status", async ({ page }) => {
  test.setTimeout(90_000);
  const alertId = "77777777-7777-4777-8777-777777777777";
  const incidentId = "88888888-8888-4888-8888-888888888888";
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    let body = { data: [], rows: [], summary: {}, items: [] };
    if (path === "/auth/config") body = { mode: "local", local_development_only: true };
    else if (path === "/auth/login") body = { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } };
    else if (path === "/healthz") body = { status: "ok" };
    else if (path.startsWith("/incidents/metadata")) body = { rows: [{ incident_id: incidentId, alert_id: alertId, title: "Status consistency incident", service: "payments", environment: "prod", status: "remediating", approval_status: "approved", projection_payload: { status: "remediating", approval: { status: "approved" } } }] };
    else if (path.startsWith(`/incidents/${incidentId}/stage-completeness`)) body = { incident_id: incidentId, status: "investigating", stages: [] };
    else if (path.startsWith(`/alerts/${alertId}/processed-result`)) body = { data: { alert: { id: alertId, name: "StatusConsistencyAlert", service: "payments", severity: "high" }, incident: { id: incidentId, service: "payments", environment: "prod", status: "investigating" }, approval: { status: "approved" }, context: { metadata: {} }, timeline: [] } };
    else if (path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/incidents");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  const summaryRow = page.getByRole("button", { name: "Status consistency incident", exact: true }).locator("xpath=ancestor::tr");
  await expect(summaryRow.getByText("remediating", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Status consistency incident", exact: true }).click();
  await expect(page.getByRole("heading", { name: "payments: StatusConsistencyAlert" })).toBeVisible();
  await expect(page.locator(".detail-context")).toContainText("Status: Remediating");
});

test("incident detail preserves nested alert identity while details load", async ({ page }) => {
  const alertId = "11111111-1111-4111-8111-111111111111";
  const incidentId = "22222222-2222-4222-8222-222222222222";
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    let body = { data: [], rows: [], summary: {}, items: [] };
    if (path === "/auth/config") body = { mode: "local", local_development_only: true };
    else if (path === "/auth/login") body = { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } };
    else if (path === "/healthz") body = { status: "ok" };
    else if (path.startsWith("/incidents/metadata")) body = { rows: [{ incident_id: incidentId, title: "Context agent incident", service: "kaiops-context-agent", environment: "prod", status: "investigating", projection_payload: { alert_id: alertId, event_payload: { alert_id: alertId, incident_id: incidentId } } }] };
    else if (path.startsWith(`/alerts/${alertId}/processed-result`)) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      body = { data: { alert: { id: alertId, name: "ContextAgentFailure", service: "kaiops-context-agent", severity: "high" }, incident: { id: incidentId, service: "kaiops-context-agent", environment: "prod", status: "investigating" }, context: { metadata: {} }, timeline: [] } };
    } else if (path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/incidents");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("button", { name: "Context agent incident", exact: true })).toBeVisible();
  await expect(page.getByRole("code").filter({ hasText: incidentId })).toBeVisible();
  await page.getByRole("button", { name: "Context agent incident", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`alert_id=${alertId}`));
  await expect(page.getByRole("heading", { name: "Incident Response" })).toBeVisible();
  await expect(page.getByText("Select an alert in Alert Stream to open the detail tabs workspace.")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "kaiops-context-agent: ContextAgentFailure" })).toBeVisible({ timeout: 5000 });
  await expect(page.getByText(incidentId, { exact: true })).toBeVisible();
  await expect(page.locator(".detail-context")).toContainText("Severity: HIGH");
  await expect(page.locator(".detail-context")).toContainText("Status: Investigating");
});

test("incident without an alert id opens a focused incident details fallback", async ({ page }) => {
  const incidentId = "77777777-7777-4777-8777-777777777777";
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    let body = { data: [], rows: [], summary: {}, items: [] };
    if (path === "/auth/config") body = { mode: "local", local_development_only: true };
    else if (path === "/auth/login") body = { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } };
    else if (path === "/healthz") body = { status: "ok" };
    else if (path.startsWith("/incidents/metadata")) body = { rows: [{ incident_id: incidentId, title: "Legacy projection incident", service: "payments", environment: "prod", status: "investigating" }] };
    else if (path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] }, rows: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/incidents");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  const row = page.locator("tbody tr").filter({ hasText: incidentId });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "View details" }).click();
  await expect(page).toHaveURL(new RegExp(`/incidents\\?incident_id=${incidentId}&stage=`));
  await expect(page.locator(".incident-detail-view")).toBeVisible();
  await expect(page.getByRole("radio", { name: /Back to inbox/ })).toBeVisible();
  await expect(page.getByRole("code").filter({ hasText: incidentId })).toBeVisible();
  await page.getByRole("button", { name: "Open correlation workspace" }).click();
  await expect(page.getByRole("radio", { name: /Correlation Timeline/ })).toBeChecked();
  await expect(page.locator(".incident-lifecycle")).toBeVisible();
});

test("detail URL reconstructs the selected alert after a page refresh", async ({ page }) => {
  const alertId = "33333333-3333-4333-8333-333333333333";
  const incidentId = "44444444-4444-4444-8444-444444444444";
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    let body = { data: [], rows: [], summary: {}, items: [] };
    if (path === "/auth/config") body = { mode: "local", local_development_only: true };
    else if (path === "/auth/login") body = { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } };
    else if (path === "/healthz") body = { status: "ok" };
    else if (path.startsWith(`/alerts/${alertId}/processed-result`)) body = { data: { alert: { id: alertId, name: "ReloadedAlert", service: "kaiops-api-gateway", severity: "critical" }, incident: { id: incidentId, status: "investigating", service: "kaiops-api-gateway" }, context: { metadata: {} }, timeline: [] } };
    else if (path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent") || path.startsWith("/incidents/metadata") || path === "/applications") body = { data: { rows: [] }, rows: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto(`/?workspace=alert&alert_id=${alertId}`);
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "kaiops-api-gateway: ReloadedAlert" })).toBeVisible();
  await page.reload();
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "kaiops-api-gateway: ReloadedAlert" })).toBeVisible();
  await expect(page.getByText("Select an alert in Alert Stream to open the detail tabs workspace.")).toHaveCount(0);
});

test("incident summary connects source application and Prometheus to KaiOps processing", async ({ page }) => {
  const alertId = "55555555-5555-4555-8555-555555555555";
  const incidentId = "66666666-6666-4666-8666-666666666666";
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    let body = { data: [], rows: [], summary: {}, items: [] };
    if (path === "/auth/config") body = { mode: "local", local_development_only: true };
    else if (path === "/auth/login") body = { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } };
    else if (path.startsWith("/incidents/metadata")) body = { rows: [{ incident_id: incidentId, alert_id: alertId, title: "httpbin-failure-lab: ExternalApplicationUnavailable", service: "httpbin-failure-lab", environment: "public-internet", status: "awaiting_approval", ticket_id: "KAN-1376", source: "public-internet-blackbox", projection_payload: { context_source: "realtime_collection", event_payload: { labels: { application: "httpbin-failure-lab", project_name: "KaiOps", instance: "https://httpbin.org/status/503", alertname: "ExternalApplicationUnavailable", job: "blackbox", transport: "alertmanager", environment: "public-internet" } } } }] };
    else if (path.startsWith("/alerts/all")) body = { data: { rows: [{ id: alertId, name: "ExternalApplicationUnavailable", service: "httpbin-failure-lab", source: "public-internet-blackbox", starts_at: "2026-08-11T15:23:20Z", trace_id: "trace-httpbin-503", description: "HTTPS probe failed for https://httpbin.org/status/503 in public-internet.", labels: { application: "httpbin-failure-lab", project_name: "KaiOps", instance: "https://httpbin.org/status/503", alertname: "ExternalApplicationUnavailable", job: "blackbox", transport: "alertmanager", alert_status: "firing", ingestion_channel: "monitoring" }, annotations: { generatorURL: "http://prometheus:9090/graph?g0.expr=probe_success" } }] } };
    else if (path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/incidents");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.getByRole("radio", { name: /Correlation Timeline/ }).click();
  await expect(page.getByLabel("Application: httpbin-failure-lab")).toBeVisible();
  await expect(page.getByLabel("Signal: https://httpbin.org/status/503")).toBeVisible();
  await expect(page.getByLabel("Prometheus: ExternalApplicationUnavailable")).toBeVisible();
  await expect(page.getByLabel(/Alert landing:/)).toBeVisible();
  await expect(page.getByLabel("Jira: KAN-1376")).toBeVisible();
  await page.getByLabel("Application: httpbin-failure-lab").click();
  await expect(page.getByText("No application log captured for this alert")).toBeVisible();
  await expect(page.getByText("HTTPS probe failed for https://httpbin.org/status/503 in public-internet.").first()).toBeVisible();
  await expect(page.getByText("trace-httpbin-503").first()).toBeVisible();
  await expect(page.getByText(alertId).first()).toBeVisible();
});

test("manual approval does not dispatch a plan with missing evidence and rollback", async ({ page }) => {
  test.setTimeout(90_000);
  const alertId = "12121212-1212-4212-8212-121212121212";
  const incidentId = "34343434-3434-4434-8434-343434343434";
  const recommendationId = "56565656-5656-4656-8656-565656565656";
  const approvalId = "78787878-7878-4878-8878-787878787878";
  let executionRequest = null;
  await page.route("**/api-gateway/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api-gateway/, "");
    let body = { data: [], rows: [], summary: {}, items: [] };
    if (path === "/auth/config") body = { mode: "local", local_development_only: true };
    else if (path === "/auth/login") body = { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } };
    else if (path === "/healthz") body = { status: "ok" };
    else if (path.startsWith("/incidents/metadata")) body = { rows: [{ incident_id: incidentId, alert_id: alertId, recommendation_id: recommendationId, title: "Ready dev remediation", service: "checkout-api", environment: "dev", status: "awaiting_approval", approval_status: "pending", risk_tier: "low", execution_mode: "human-approval" }] };
    else if (path.startsWith(`/incidents/${incidentId}/stage-completeness`)) body = { incident_id: incidentId, status: "awaiting_approval", stages: [] };
    else if (path.startsWith(`/alerts/${alertId}/processed-result`)) body = { data: {
      alert: { id: alertId, name: "CheckoutUnavailable", service: "checkout-api", environment: "dev", severity: "warning" },
      incident: { id: incidentId, service: "checkout-api", environment: "dev", status: "awaiting_approval" },
      approval: { status: "pending", required: true },
      decision: { risk_tier: "low", execution_mode: "human-approval", requires_approval: true },
      recommendation: { id: recommendationId, recommended_action: "Restart checkout-api", metadata: { execution_plan: { execution_ready: true, commands: ["ansible-playbook playbooks/restart-service.yml -e service=checkout-api -e env=dev"], validation_commands: ["curl -fsS http://checkout-api:8080/healthz"] } } },
      context: { metadata: {} }, timeline: [],
    } };
    else if (path === "/approval/approve") body = { id: approvalId, incident_id: incidentId, recommendation_id: recommendationId, decision: "approved", status: "approved" };
    else if (path === "/remediation/execute") {
      executionRequest = request.postDataJSON();
      body = { id: "90909090-9090-4090-8090-909090909090", incident_id: incidentId, action_type: "restart_service", target: "checkout-api", status: "dispatching" };
    } else if (path.startsWith(`/remediation/actions/by-incident/${incidentId}/latest`)) body = { incident_id: incidentId, status: "dispatching" };
    else if (path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/incidents");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.getByRole("button", { name: "Ready dev remediation", exact: true }).click();
  await page.getByRole("tab", { name: "Resolve incident" }).click();
  const approvalButton = page.getByRole("button", { name: "Approve and continue" });
  await expect(approvalButton).toBeVisible();
  await expect(page.getByRole("region", { name: "Approval eligibility" })).toContainText("Not ready");
  expect(executionRequest).toBeNull();
});
