import { expect, test } from "@playwright/test";

test("discovery is a first-class responsive alert view", async ({ page }) => {
  test.setTimeout(45_000);

  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/login"
      ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
      : path === "/healthz"
        ? { status: "ok", service: "api-gateway" }
        : path.startsWith("/alerts/all")
          ? { data: { rows: [
              { alert_id: "alert-discovery-1", id: "alert-discovery-1", name: "Pod crash loop", service: "user-profile", application: "kaiops-core1", labels: { project_name: "KaiOps" }, severity: "critical", status: "active", source: "email" },
              { alert_id: "alert-telemetry-1", id: "alert-telemetry-1", name: "Telemetry signals missing", service: "astronomy-shop", application: "Telemetry", labels: { project_name: "Telemetry", origin_system: "telemetry", ingestion_channel: "monitoring" }, severity: "warning", status: "active", source: "telemetry" },
            ] } }
          : path === "/applications"
            ? { data: { rows: [
                { id: "project-kaiops", name: "KaiOps", namespace: "kaiops", status: "dashboard_created", metrics_endpoint: "http://api-gateway:8000/metrics" },
                { id: "project-telemetry", name: "Telemetry", namespace: "telemetry", status: "dashboard_created", metrics_endpoint: "http://host.docker.internal:19090/metrics" },
              ] } }
            : path.startsWith("/landing-pad/recent")
              ? { data: { rows: [
                  {
                    file: "checkout-log-alert.json",
                    received_at: "2026-07-25T12:00:00Z",
                    status: "processed",
                    source: "opensearch-log-alert",
                    name: "Checkout log error burst",
                    service: "checkout-api",
                    application: "KaiOps",
                    project_name: "KaiOps",
                    severity: "high",
                    labels: { project_name: "KaiOps", origin_system: "opensearch", ingestion_channel: "log" },
                  },
                ] } }
            : { data: [], rows: [], summary: {}, items: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("**/monitoring-adapter/**", async (route) => {
    const workflow = {
      alert: { id: "alert-discovery-1", name: "Pod crash loop", service: "user-profile", severity: "critical" },
      incident: { id: "incident-discovery-1", status: "investigating" },
      context: {
        metadata: {
          discovery_report: {
            protocol: "mcp-jsonrpc-2.0",
            retrieval_stages: [
              { stage: "query_planned", status: "completed" },
              { stage: "logs_search", status: "completed", result_count: 2 },
              { stage: "tickets_search", status: "completed", result_count: 1 },
              { stage: "code_search", status: "completed", result_count: 1 },
              { stage: "evidence_correlated", status: "completed", result_count: 4 },
              { stage: "llm_analysis", status: "completed" },
              { stage: "discovery_completed", status: "completed" },
            ],
            evidence: [
              { evidence_id: "LOG-1", source: "log", uri: "log://runtime/app.log#L12", snippet: "Secret lookup failed." },
              { evidence_id: "TICKET-1", source: "ticket", uri: "ticket://OPS-9", snippet: "Previous secret rotation incident." },
              { evidence_id: "CODE-1", source: "code", uri: "code://settings.py#L30", snippet: "Required startup secret validation." },
            ],
            report: {
              model: "gpt",
              summary: "Startup failed after a required secret could not be loaded.",
              insufficient_evidence: false,
              hypotheses: [{ cause: "Missing application secret", confidence: 0.91, supporting_evidence: ["LOG-1", "TICKET-1", "CODE-1"] }],
            },
          },
        },
      },
    };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: { workflow } }) });
  });
  await page.goto("/");
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();

  await expect(page.getByRole("heading", { name: "KaiOps + Telemetry" })).toBeVisible();
  await expect(page.getByText("Pod crash loop", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".source-email").filter({ hasText: "Email" }).first()).toBeVisible();
  await expect(page.getByText("Checkout log error burst", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".source-log").filter({ hasText: "Logs / OpenSearch" }).first()).toBeVisible();
  const telemetryProject = page.getByRole("button", { name: /Telemetry telemetry namespace/ });
  await expect(telemetryProject).toBeVisible();
  await expect(page.getByText("Telemetry signals missing", { exact: true })).toHaveCount(0);
  await telemetryProject.click();
  await expect(page.getByText("Telemetry signals missing", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Pod crash loop", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: /KaiOps kaiops namespace/ }).click();

  const firstAlert = page.locator("table tbody tr").filter({ hasText: "Pod crash loop" }).first();
  await expect(firstAlert).toBeVisible({ timeout: 30_000 });
  await firstAlert.locator("button").first().click();

  await expect(page.getByRole("heading", { name: "Signal to Recovery", exact: true })).toBeVisible();
  await expect(page.locator(".unified-incident-timeline")).toBeVisible();
  await expect(page.getByText("Context retrieved from", { exact: true })).toBeVisible();

  const discoveryTab = page.getByRole("button", { name: "Discovery + Context", exact: true });
  await expect(discoveryTab).toBeVisible();
  await discoveryTab.click();
  await expect(page.getByRole("heading", { name: "Discovery + Context Intelligence", exact: true })).toBeVisible();
  await expect(page.locator(".combined-analysis-page")).toBeVisible();

  const desktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(desktopOverflow).toBeFalsy();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".combined-analysis-page")).toBeVisible();
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(mobileOverflow).toBeFalsy();
});
