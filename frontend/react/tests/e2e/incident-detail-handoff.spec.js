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

test("durable incident history stays separate from the technical workspace and surfaces missing identities", async ({ page }) => {
  const incidentId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const alertId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  const valid = { incident_id: incidentId, alert_id: alertId, title: "Durable navigation incident", service: "api-gateway", environment: "prod", status: "investigating", projection_payload: { alert_id: alertId } };
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/config"
      ? { mode: "local", local_development_only: true }
      : path === "/auth/login"
        ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
        : path.startsWith("/incidents/metadata")
          ? { rows: [valid] }
          : path.startsWith("/alerts/all")
            ? { data: { rows: [{ id: alertId, alert_id: alertId, incident_id: incidentId, name: "GatewayFailure", service: "api-gateway" }] } }
            : path.startsWith(`/alerts/${alertId}/processed-result`)
              ? { data: { alert: { id: alertId, name: "GatewayFailure", service: "api-gateway" }, incident: valid, context: { metadata: {} }, timeline: [] } }
              : { data: { rows: [] }, rows: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.getByRole("button", { name: /Durable navigation incident/ }).first().click();
  await expect(page).toHaveURL(new RegExp(`/incidents/${incidentId}$`));
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
  await page.goForward();
  await expect(page).toHaveURL(new RegExp(`/incidents/${incidentId}$`));
  await page.reload();
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Durable navigation incident" })).toBeVisible();

  await page.getByRole("button", { name: "Open full investigation" }).click();
  await expect(page).toHaveURL(new RegExp(`workspace=alert&alert_id=${alertId}`));

  await page.goto("/incidents/%20");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByText("Incident not found", { exact: true })).toBeVisible();
  await expect(page.getByText("No role-authorized incident record matches")).toBeVisible();
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
  await expect(page.locator(".kai-navigation")).toHaveCount(1);
  await expect(page.locator(".sidebar-panel")).toHaveCount(0);
  await page.reload();
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "kaiops-api-gateway: ReloadedAlert" })).toBeVisible();
  await expect(page.locator(".kai-navigation")).toHaveCount(1);
  await expect(page.locator(".sidebar-panel")).toHaveCount(0);
  await expect(page.getByText("Select an alert in Alert Stream to open the detail tabs workspace.")).toHaveCount(0);
});

test("fresh RCA analysis stays authenticated and renders the persisted resolution", async ({ page }) => {
  const alertId = "77777777-7777-4777-8777-777777777777";
  const incidentId = "88888888-8888-4888-8888-888888888888";
  const protectedRequests = [];
  let analysisComplete = false;

  const alert = {
    id: alertId,
    alert_id: alertId,
    name: "HighRequestLatency",
    service: "api-gateway",
    application: "KaiMS",
    environment: "prod",
    severity: "critical",
    status: "active",
  };
  const incident = {
    id: incidentId,
    incident_id: incidentId,
    alert_id: alertId,
    service: "api-gateway",
    environment: "prod",
    status: "investigating",
  };
  const evidence = [{
    evidence_id: "metric-latency-1",
    source: "prometheus-metrics",
    summary: "Request latency rose immediately after the connection-pool saturation event.",
    citation: "prometheus://api-gateway/http_request_duration_seconds",
    timestamp: "2026-08-26T05:30:00Z",
    cached: false,
  }];
  const analyzedWorkflow = () => ({
    alert,
    incident,
    context: {
      tenant_id: "default",
      incident_id: incidentId,
      alert,
      metadata: {
        context_quality: { contract_version: "kaiops.context-quality.v1", quality_score: 0.94, coverage_score: 0.92, freshness_score: 0.98, provenance_score: 0.93, evidence_count: 1, reusable: true },
        discovery_report: { evidence },
      },
    },
    recommendation: {
      id: analysisComplete ? "88888888-8888-5888-8888-888888888888" : "recommendation-previous-1",
      tenant_id: "default",
      incident_id: incidentId,
      root_cause: analysisComplete ? "API connection-pool saturation caused request queueing." : "Previous cached hypothesis.",
      confidence: 0.94,
      impact: "API requests exceeded the latency SLO.",
      recommended_action: "Increase the API connection pool and recycle saturated workers through the governed rollout.",
      severity: "critical",
      rationale: "Request latency and queue depth rose together after connection-pool exhaustion.",
      metadata: {
        rca_analysis: { root_cause: analysisComplete ? "API connection-pool saturation caused request queueing." : "Previous cached hypothesis.", causal_chain: "Pool exhaustion increased queue depth and request latency.", confidence_score: 0.94, evidence_used: ["metric-latency-1"] },
        impact_analysis: { impact_summary: "API requests exceeded the latency SLO.", customer_impact: "Customers experienced delayed API responses.", impacted_services: ["api-gateway"], evidence_used: ["metric-latency-1"] },
        remediation_analysis: { recommended_action: "Increase the API connection pool and recycle saturated workers through the governed rollout." },
        investigation_report: { status: "conclusive", conclusive: true, conclusion: { confidence: 0.94 } },
      },
    },
    timeline: [],
  });

  await page.route("**/api-gateway/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api-gateway/, "");
    const isProtected = path.startsWith(`/alerts/${alertId}/processed-result`)
      || path.startsWith(`/alerts/${alertId}/linked-documents`)
      || path.startsWith("/analysis/");
    if (isProtected) {
      protectedRequests.push({ path, authorization: request.headers().authorization || "" });
    }

    let body = { data: [], rows: [], summary: {}, items: [] };
    if (path === "/auth/config") body = { mode: "local", local_development_only: true };
    else if (path === "/auth/login") body = { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } };
    else if (path === "/healthz") body = { status: "ok" };
    else if (path.startsWith(`/alerts/${alertId}/processed-result`)) body = { data: analyzedWorkflow() };
    else if (path.startsWith(`/alerts/${alertId}/linked-documents`)) body = { data: { canonical_alert: alert, linked_documents: analysisComplete ? evidence : [] } };
    else if (path === `/analysis/alerts/${alertId}/regenerate`) {
      analysisComplete = true;
      return route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({
        request_id: "99999999-9999-4999-8999-999999999999",
        status: "accepted",
        delivery: "published",
        alert_id: alertId,
        incident_id: incidentId,
        previous_recommendation_id: "recommendation-previous-1",
        expected_recommendation_id: "88888888-8888-5888-8888-888888888888",
        analysis_mode: "fresh",
        context_strategy: "realtime",
        poll_after_ms: 10,
      }) });
    } else if (path.startsWith("/analysis/requests/99999999-9999-4999-8999-999999999999/status")) {
      body = {
        request_id: "99999999-9999-4999-8999-999999999999",
        incident_id: incidentId,
        recommendation_id: "88888888-8888-5888-8888-888888888888",
        status: "complete",
        ready: true,
      };
    } else if (path === "/analysis/resolution-catalog/relevant") body = { data: { rows: [] } };
    else if (path.startsWith("/incidents/metadata")) body = { rows: [{ ...incident, title: "api-gateway: HighRequestLatency", projection_payload: { alert_id: alertId } }] };
    else if (path.startsWith("/alerts/all")) body = { data: { rows: [alert] } };
    else if (path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto(`/?workspace=alert&alert_id=${alertId}`);
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "api-gateway: HighRequestLatency" })).toBeVisible();

  const tabs = page.getByRole("tablist", { name: "Incident workspace sections" });
  await tabs.getByRole("tab", { name: "Evidence, RCA, and impact" }).click();
  await page.getByRole("button", { name: /Fresh context/ }).click();
  await page.getByRole("button", { name: "Run fresh analysis" }).click();

  await expect(page.getByText(`Fresh context and RCA analysis completed for alert ${alertId}.`)).toBeVisible();
  await expect(page.getByText("API connection-pool saturation caused request queueing.").first()).toBeVisible();
  await expect(page.getByText("Increase the API connection pool and recycle saturated workers through the governed rollout.").first()).toBeVisible();
  await expect(page.getByText(/HTTP 401|Not authenticated/)).toHaveCount(0);
  expect(protectedRequests.some(({ path }) => path === `/analysis/alerts/${alertId}/regenerate`)).toBeTruthy();
  const orchestrationRequests = protectedRequests.filter(({ path }) => path === `/analysis/alerts/${alertId}/regenerate`
    || path === "/analysis/context/collect"
    || path === "/analysis/resolution/resolve");
  expect(orchestrationRequests).toHaveLength(1);
  expect(protectedRequests.filter(({ path }) => path.includes("processed-result")).length).toBeGreaterThanOrEqual(2);
  expect(protectedRequests.every(({ authorization }) => authorization === "Bearer admin-token")).toBeTruthy();
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

  await page.goto("/alerts");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.getByRole("radio", { name: /Correlation Timeline/ }).click();
  await expect(page.getByLabel("Application: httpbin-failure-lab")).toBeVisible();
  await expect(page.getByLabel("Signal: https://httpbin.org/status/503")).toBeVisible();
  await expect(page.getByLabel("Prometheus: ExternalApplicationUnavailable")).toBeVisible();
  await expect(page.getByLabel(/Alert landing:/)).toBeVisible();
  await expect(page.getByLabel("Jira: KAN-1376")).toBeVisible();
  await page.getByRole("button", { name: "View details" }).click();
  await page.getByRole("button", { name: "Create alert" }).click();
  await expect(page.getByText("HTTPS probe failed for https://httpbin.org/status/503 in public-internet.").first()).toBeVisible();
  await expect(page.getByText("trace-httpbin-503").first()).toBeVisible();
  await expect(page.getByText(alertId).first()).toBeVisible();
  await expect(page.locator(".metric-handoff")).toContainText(incidentId);
  await expect(page.locator(".metric-handoff")).toContainText("KAN-1376");
});
