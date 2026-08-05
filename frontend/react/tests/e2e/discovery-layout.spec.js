import { expect, test } from "@playwright/test";

test("discovery is a first-class responsive alert view", async ({ page }) => {
  test.setTimeout(90_000);
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
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
    recommendation: {
      id: "22222222-2222-4222-8222-222222222222",
      root_cause: "Given the evidence:\\n```json\\n{\"root_cause\":\"Memory pressure in user-profile\",\"evidence_used\":[\"Container memory limit reached\"],\"missing_evidence\":[\"Heap profile\"],\"confidence_score\":0.72}\\n```",
      impact: "```json\\n{\"impacted_services\":[\"user-profile\"],\"customer_impact\":\"Intermittent profile failures\",\"blast_radius\":\"Single service\",\"confidence_score\":0.64}\\n```",
      recommended_action: "Restart the affected pod after approval and validate memory.",
      confidence: 0.72,
      metadata: {
        rca_analysis: {
          root_cause: "Memory pressure in user-profile",
          evidence_used: ["LOG-1", "TICKET-1", "CODE-1"],
          missing_evidence: ["Heap profile"],
          confidence_score: 0.72,
        },
      },
    },
  };

  let sawLandingPadRequest = false;
  let sawArchivedLandingPadRequest = false;
  let alertsAllRequestCount = 0;
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/login"
      ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
      : path === "/healthz"
        ? { status: "ok", service: "api-gateway" }
          : path.endsWith("/processed-result")
            ? { data: { workflow } }
          : path.startsWith("/evaluations/by-recommendation/")
            ? { data: { updated: true } }
          : path.startsWith("/alerts/all")
          ? (() => {
            alertsAllRequestCount += 1;
            return { data: { rows: [
              { alert_id: "11111111-1111-4111-8111-111111111111", id: "11111111-1111-4111-8111-111111111111", name: "Pod crash loop", service: "user-profile", application: "kaiops-core1", environment: "production", labels: { project_name: "KaiOps", alert_fingerprint: "email-pod-crash-1", environment: "production" }, severity: "critical", status: "active", source: "email" },
              { alert_id: "alert-log-1", id: "alert-log-1", name: "Checkout log error burst", service: "checkout-api", application: "KaiOps", labels: { project_name: "KaiOps", origin_system: "opensearch", ingestion_channel: "log" }, severity: "high", status: "active", source: "opensearch-log-alert" },
              { alert_id: "alert-telemetry-1", id: "alert-telemetry-1", name: "Telemetry signals missing", service: "astronomy-shop", application: "Telemetry", labels: { project_name: "Telemetry", origin_system: "telemetry", ingestion_channel: "monitoring" }, severity: "warning", status: "active", source: "telemetry" },
            ] } };
          })()
          : path === "/applications"
            ? { data: { rows: [
                { id: "project-kaiops", name: "KaiOps", namespace: "kaiops", status: "dashboard_created", metrics_endpoint: "http://api-gateway:8000/metrics" },
                { id: "project-telemetry", name: "Telemetry", namespace: "telemetry", status: "dashboard_created", metrics_endpoint: "http://host.docker.internal:19090/metrics" },
              ] } }
            : path.startsWith("/landing-pad/recent")
              ? (() => {
                sawLandingPadRequest = true;
                if (new URL(route.request().url()).searchParams.get("include_archive") === "true") {
                  sawArchivedLandingPadRequest = true;
                }
                return { data: { rows: [
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
                  {
                    file: "email-pod-crash-duplicate.eml",
                    received_at: "2026-07-25T12:01:00Z",
                    status: "processed",
                    source: "email",
                    name: "Pod crash loop",
                    service: "user-profile",
                    application: "KaiOps",
                    project_name: "KaiOps",
                    severity: "critical",
                    labels: { project_name: "KaiOps", origin_system: "email", ingestion_channel: "email", alert_fingerprint: "email-pod-crash-1" },
                  },
                  {
                    file: "jira-resolved.json",
                    received_at: "2026-07-25T12:02:00Z",
                    status: "processed",
                    alert_status: "inactive",
                    source: "jira",
                    name: "Checkout incident resolved",
                    service: "checkout-api",
                    application: "KaiOps",
                    severity: "info",
                    labels: { project_name: "KaiOps", origin_system: "jira", ingestion_channel: "ticket", alert_status: "inactive" },
                  },
                ] } };
              })()
            : { data: [], rows: [], summary: {}, items: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("**/monitoring-adapter/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: { workflow } }) });
  });
  await page.goto("/");
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();

  await expect(page.getByRole("heading", { name: "KaiOps + Telemetry" })).toBeVisible();
  await expect(page.getByText("Administrator dashboard", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Platform attention", exact: true })).toBeVisible();
  const globalOperations = page.getByLabel("Global operational capabilities");
  await globalOperations.getByRole("searchbox", { name: "Global search" }).fill("Pod crash");
  await expect(globalOperations.getByRole("list", { name: "Global search results" })).toContainText("Alert: Pod crash loop");
  await globalOperations.getByRole("tab", { name: /My Work/ }).click();
  await expect(globalOperations.getByText("Collaboration unavailable", { exact: true })).toBeVisible();
  await expect(globalOperations.getByRole("button", { name: "Add note / watcher unavailable" })).toBeDisabled();
  await globalOperations.getByRole("tab", { name: /Notifications/ }).click();
  await expect(globalOperations.getByText("Delivery preferences unavailable", { exact: true })).toBeVisible();
  await expect(globalOperations.getByRole("button", { name: "Configure delivery unavailable" })).toBeDisabled();
  await globalOperations.screenshot({ path: "artifacts/phase10-global-operations.png" });
  await globalOperations.getByRole("tab", { name: "Search", exact: true }).click();
  await globalOperations.getByRole("searchbox", { name: "Global search" }).fill("");
  await page.screenshot({ path: "artifacts/phase6-administrator-dashboard.png", fullPage: true });
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toContainText("Operations");
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toContainText("Intelligence");
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toContainText("Governance");
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toContainText("Platform");
  await page.screenshot({ path: "artifacts/phase4-authoritative-navigation.png", fullPage: true });
  await page.getByRole("button", { name: "Live Alerts", exact: true }).click();
  await expect(page).toHaveURL(/\/alerts$/);
  await expect(page.getByRole("heading", { name: "Alert Ingestion Stream", exact: true })).toBeVisible();
  await expect.poll(() => sawLandingPadRequest).toBe(true);
  expect(sawArchivedLandingPadRequest).toBe(false);
  await expect(page.getByRole("button", { name: /Email/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Logs \/ OpenSearch/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Prometheus/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Tickets \/ Jira/ })).toBeVisible();
  await expect(page.getByRole("tablist", { name: "Alert lifecycle sections" }).getByRole("tab")).toHaveCount(4);
  await expect(page.getByLabel("Saved view").locator("option")).toHaveCount(5);
  await expect(page.getByText(/Updated exactly:/)).toBeVisible();
  await page.getByRole("button", { name: "Pause live" }).click();
  await expect(page.getByText("Live updates paused", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Resume live" }).click();
  await expect(page.locator(".ingestion-event.channel-email").filter({ hasText: "Pod crash loop" }).first()).toBeVisible();
  await expect(page.getByText("Checkout log error burst", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".ingestion-event.channel-email").filter({ hasText: "Occurrences" }).first()).toBeVisible();
  await page.screenshot({ path: "artifacts/phase7-alert-ingestion-controls.png", fullPage: true });
  await page.getByRole("tab", { name: "Resolved" }).click();
  await page.getByRole("button", { name: /Tickets \/ Jira/ }).click();
  await expect(page.getByText("Checkout incident resolved", { exact: true })).toBeVisible();
  await expect(page.locator(".ingestion-event").filter({ hasText: "inactive" })).toBeVisible();
  await page.getByTitle("Dashboard", { exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "KaiOps + Telemetry" })).toBeVisible();
  await expect(page.getByText("Pod crash loop", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Open alert 11111111-1111-4111-8111-111111111111" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Open alert email-pod-crash-duplicate.eml" })).toHaveCount(0);
  await expect(page.locator(".source-email").filter({ hasText: "Email" }).first()).toBeVisible();
  await expect(page.getByText("Checkout log error burst", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".source-log").filter({ hasText: "Logs / OpenSearch" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Open alert 11111111-1111-4111-8111-111111111111" }).click();
  await expect(page.getByRole("heading", { name: "Alert Details Cockpit" })).toBeVisible();
  const telemetryProject = page.getByRole("button", { name: /Telemetry telemetry namespace/ });
  await expect(telemetryProject).toBeVisible();
  await expect(page.getByText("Telemetry signals missing", { exact: true })).toHaveCount(0);
  await telemetryProject.click();
  await expect(page.getByText("Telemetry signals missing", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Pod crash loop", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: /KaiOps kaiops namespace/ }).click();
  expect(alertsAllRequestCount).toBe(1);

  const firstAlert = page.locator("table tbody tr").filter({ hasText: "Pod crash loop" }).first();
  await expect(firstAlert).toBeVisible({ timeout: 30_000 });
  await firstAlert.locator("button").first().click();

  await expect(page.locator(".alert-details-cockpit .detail-context")).toContainText("11111111-1111-4111-8111-111111111111");
  await expect(page.locator(".alert-details-cockpit .detail-context")).not.toContainText("email-pod-crash-duplicate.eml");
  const sectionNavigation = page.getByRole("tablist", { name: "Incident workspace sections" });
  for (const section of ["Overview", "Evidence", "RCA & Impact", "Resolution", "Approval", "Execution", "Audit Trail"]) {
    await expect(sectionNavigation.getByRole("tab", { name: section, exact: true })).toBeVisible();
  }
  await expect(sectionNavigation.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Incident Workspace", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Incident Overview", exact: true })).toBeVisible();
  await expect(page.locator(".unified-incident-timeline")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Previous" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Next" })).toBeVisible();
  await page.screenshot({ path: "artifacts/phase5-progressive-incident-cockpit.png", fullPage: true });

  await sectionNavigation.getByRole("tab", { name: "Audit Trail" }).click();
  await expect(page.getByRole("heading", { name: "Signal to Recovery", exact: true })).toBeVisible();
  await expect(page.locator(".unified-incident-timeline")).toBeVisible();
  await expect(page.locator(".timeline-phase-card")).toHaveCount(6);
  await expect(page.getByText("Evidence", { exact: true }).first()).toBeVisible();
  const detectPhase = page.locator(".timeline-phase-card").filter({ hasText: "Detect" });
  const discoverPhase = page.locator(".timeline-phase-card").filter({ hasText: "Discover" });
  await detectPhase.getByRole("button", { name: "View events" }).click();
  await expect(page.locator(".timeline-event-panel")).toHaveCount(1);
  await expect(page.getByText("Detect events", { exact: true })).toBeVisible();
  await discoverPhase.getByRole("button", { name: "View events" }).click();
  await expect(page.locator(".timeline-event-panel")).toHaveCount(1);
  await expect(page.getByText("Discover events", { exact: true })).toBeVisible();
  await page.locator(".timeline-event-panel").getByRole("button", { name: "Close" }).click();
  await expect(page.locator(".timeline-event-panel")).toHaveCount(0);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.locator(".alert-details-cockpit .detail-context")).toContainText("alert-log-1");
  await expect(sectionNavigation.getByRole("tab", { name: "Audit Trail" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Previous" }).click();
  await expect(page.locator(".alert-details-cockpit .detail-context")).toContainText("11111111-1111-4111-8111-111111111111");

  const discoveryTab = sectionNavigation.getByRole("tab", { name: "RCA & Impact", exact: true });
  await expect(discoveryTab).toBeVisible();
  await discoveryTab.click();
  await expect(page.getByRole("heading", { name: "Discovery + Context", exact: true })).toBeVisible();
  expect(pageErrors).toEqual([]);
  await page.getByRole("button", { name: /^Evidence \(/ }).click();
  await expect(page.locator(".investigation-story")).toContainText("Alert becomes a search plan");
  await expect(page.locator(".investigation-story")).toContainText("Tools return source facts");
  await expect(page.locator(".investigation-story")).toContainText("Facts are connected to operations");
  await expect(page.locator(".investigation-story")).toContainText("RCA and impact are derived");
  await expect(page.locator(".investigation-story")).toContainText("Evidence becomes an action");
  const [completeDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download complete investigation" }).click(),
  ]);
  expect(completeDownload.suggestedFilename()).toBe("kaiops-complete-investigation.json");
  const [evidenceDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download evidence & logs" }).click(),
  ]);
  expect(evidenceDownload.suggestedFilename()).toBe("kaiops-02-discover.json");
  await expect(page.getByText("Memory pressure in user-profile", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Evidence used", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/```json/)).toHaveCount(0);
  await page.getByRole("button", { name: "Technical analysis", exact: true }).click();
  await expect(page.locator(".combined-analysis-grid")).toBeVisible();
  await expect(page.getByText("Missing application secret", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: /^Evidence \(/ }).click();
  await expect(page.getByRole("heading", { name: "Why KaiOps reached this recommendation", exact: true })).toBeVisible();
  for (const label of ["Direct observation", "AI inference", "Cached context", "Fresh discovery", "Conflicting evidence", "Missing evidence"]) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
  }
  await expect(page.getByText("Model / provider", { exact: true })).toBeVisible();
  await expect(page.getByText("Fallback model", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Helpful", exact: true }).click();
  await expect(page.getByText("Feedback recorded: helpful.", { exact: true })).toBeVisible();
  await page.addStyleTag({ content: ".incident-sticky-header,.incident-section-navigation{position:static!important}" });
  await page.locator(".ai-trust-panel").screenshot({ path: "artifacts/phase9-ai-trust-evidence.png" });

  await sectionNavigation.getByRole("tab", { name: "Approval" }).click();
  await expect(page.getByText("Direct Evidence", { exact: true })).toBeVisible();
  await expect(page.getByText("Exact Planned Change", { exact: true })).toBeVisible();
  await expect(page.getByText("Missing Evidence", { exact: true })).toBeVisible();
  await sectionNavigation.getByRole("tab", { name: "Execution" }).click();
  await expect(page.getByText("Dangerous production action", { exact: true })).toBeVisible();
  await expect(page.getByText(/Type EXECUTE USER-PROFILE/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Execute Approved Plan" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Emergency stop unavailable" })).toBeDisabled();
  await page.locator(".remediation-workspace").screenshot({ path: "artifacts/phase8-guarded-production-execution.png" });

  const desktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(desktopOverflow).toBeFalsy();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".remediation-workspace")).toBeVisible();
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(mobileOverflow).toBeFalsy();
});
