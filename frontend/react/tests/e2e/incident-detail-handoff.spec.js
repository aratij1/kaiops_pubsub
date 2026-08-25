import { expect, test } from "@playwright/test";

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
  await expect(page.getByText(incidentId, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Context agent incident", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/incidents/${incidentId}$`));
  await expect(page.getByRole("heading", { name: "Context agent incident" })).toBeVisible();
  await expect(page.getByText("From signal to verified recovery")).toBeVisible();
  await expect(page.getByText(incidentId, { exact: true })).toBeVisible();
  await expect(page.locator(".ic-command-header")).toContainText("prod");
  await expect(page.locator(".ic-command-header")).toContainText("investigating");
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
