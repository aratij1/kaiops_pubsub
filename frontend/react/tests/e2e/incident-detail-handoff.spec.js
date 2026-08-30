import { expect, test } from "@playwright/test";

async function signInIfNeeded(page) {
  const username = page.getByLabel("Username");
  if (await username.waitFor({ state: "visible", timeout: 8000 }).then(() => true).catch(() => false)) {
    await username.fill("admin");
    await page.getByLabel("Password").fill("Admin@123456");
    await page.getByRole("button", { name: "Sign In" }).click();
  }
}

test("incident detail preserves nested alert identity while details load", async ({ page }) => {
  const alertId = "11111111-1111-4111-8111-111111111111";
  const incidentId = "22222222-2222-4222-8222-222222222222";
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    let body = { data: [], rows: [], summary: {}, items: [] };
    if (path === "/auth/config") body = { mode: "local", local_development_only: true };
    else if (path === "/auth/login") body = { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } };
    else if (path === "/healthz") body = { status: "ok" };
    else if (path.startsWith("/incidents/groups")) body = { data: { rows: [{ incident_id: incidentId, title: "Context agent incident", service: "kaiops-context-agent", environment: "prod", status: "investigating", projection_payload: { alert_id: alertId, event_payload: { alert_id: alertId, incident_id: incidentId } } }], total_count: 1, filtered_count: 1 } };
    else if (path === `/incidents/${incidentId}`) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      body = { data: { incident_id: incidentId, alert_id: alertId, title: "Context agent incident", service: "kaiops-context-agent", environment: "prod", status: "investigating", projection_payload: { alert_id: alertId } } };
    }
    else if (path.startsWith(`/alerts/${alertId}/processed-result`)) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      body = { data: { alert: { id: alertId, name: "ContextAgentFailure", service: "kaiops-context-agent", severity: "high" }, incident: { id: incidentId, service: "kaiops-context-agent", environment: "prod", status: "investigating" }, context: { metadata: {} }, timeline: [] } };
    } else if (path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto(`/incidents/${incidentId}`);
  await signInIfNeeded(page);
  await expect(page).toHaveURL(new RegExp(`/incidents/${incidentId}$`));
  await expect(page.getByRole("heading", { name: "Context agent incident" })).toBeVisible();
  await expect(page.getByText("From signal to verified recovery")).toBeVisible();
  await expect(page.getByText(incidentId, { exact: true })).toBeVisible();
  await expect(page.locator(".ic-command-header")).toContainText("prod");
  await expect(page.locator(".ic-command-header")).toContainText("investigating");
});

test("diagnostic recommendation does not expose execution controls", async ({ page }) => {
  const alertId = "12121212-1212-4212-8212-121212121212";
  const incidentId = "34343434-3434-4434-8434-343434343434";
  const row = {
    incident_id: incidentId,
    alert_id: alertId,
    title: "Insufficient evidence incident",
    service: "mysql",
    environment: "prod",
    status: "investigating",
    confidence: 0,
    recommendation: {
      root_cause: "Investigation inconclusive.",
      recommended_action: "Collect telemetry and rerun resolution.",
      confidence: 0,
      metadata: {
        execution_plan: {
          execution_ready: false,
          readiness_blocks: ["Missing evidence source: telemetry"],
        },
      },
    },
  };
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/config"
      ? { mode: "local", local_development_only: true }
      : path === "/auth/login"
        ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
        : path.startsWith("/incidents/groups")
          ? { data: { rows: [row], total_count: 1, filtered_count: 1 } }
          : path === `/incidents/${incidentId}`
            ? { data: row }
            : { data: { rows: [] }, rows: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto(`/incidents/${incidentId}`);
  await signInIfNeeded(page);
  const executionButton = page.getByRole("button", { name: "Execution unavailable — collect evidence" });
  await expect(executionButton).toBeVisible();
  await expect(executionButton).toBeDisabled();
  await expect(page.getByRole("button", { name: "No execution to control" })).toBeDisabled();
  await expect(page.getByRole("button", { name: /Approve & let Kai resolve/ })).toHaveCount(0);
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
        : path.startsWith("/incidents/groups")
          ? { data: { rows: [valid], total_count: 1, filtered_count: 1 } }
          : path === `/incidents/${incidentId}`
            ? { data: valid }
            : path.startsWith("/alerts/all")
              ? { data: { rows: [{ id: alertId, alert_id: alertId, incident_id: incidentId, name: "GatewayFailure", service: "api-gateway" }] } }
              : path.startsWith(`/alerts/${alertId}/processed-result`)
                ? { data: { alert: { id: alertId, name: "GatewayFailure", service: "api-gateway" }, incident: valid, context: { metadata: {} }, timeline: [] } }
                : { data: { rows: [] }, rows: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/");
  await signInIfNeeded(page);
  await page.getByRole("button", { name: /Durable navigation incident/ }).first().click();
  await expect(page).toHaveURL(new RegExp(`/incidents/${incidentId}$`));
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
  await page.goForward();
  await expect(page).toHaveURL(new RegExp(`/incidents/${incidentId}$`));
  await page.reload();
  await signInIfNeeded(page);
  await expect(page.getByRole("heading", { name: "Durable navigation incident" })).toBeVisible();

  await page.getByRole("button", { name: "Open full investigation" }).click();
  await expect(page).toHaveURL(new RegExp(`workspace=alert&alert_id=${alertId}`));

  await page.goto("/incidents/%20");
  await signInIfNeeded(page);
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
  await signInIfNeeded(page);
  await expect(page.getByRole("heading", { name: "kaiops-api-gateway: ReloadedAlert" })).toBeVisible();
  await expect(page.locator(".kai-navigation")).toHaveCount(1);
  await expect(page.locator(".sidebar-panel")).toHaveCount(0);
  await page.reload();
  await signInIfNeeded(page);
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
  let integrityMismatch = false;
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
    investigation_integrity: analysisComplete
      ? integrityMismatch
        ? { status: "fingerprint_mismatch", verified: false, blocking_reasons: ["context fingerprint does not match"] }
        : { status: "verified", verified: true, blocking_reasons: [] }
      : { status: "missing_recommendation", verified: false, blocking_reasons: ["analysis pending"] },
    incident_investigation: analysisComplete ? {
      contract_version: "kaiops.incident-investigation.v1", tenant_id: "default", project_id: "KaiMS",
      incident_id: incidentId, alert_id: alertId,
      analysis_request_id: "99999999-9999-4999-8999-999999999999",
      context_snapshot_id: "77777777-7777-4777-8777-777777777777",
      context_fingerprint: "a".repeat(64), context_contract_version: "kaiops.context.v2",
      context_collected_at: "2026-08-26T05:30:00Z", context_expires_at: "2026-08-28T05:30:00Z",
      context_quality: { evidence_count: 1, category_coverage: 1, freshness_score: 1, provenance_score: 1, independent_source_count: 1, direct_observation_count: 1, valid: true, blocking_reasons: [] },
      context_sources: [],
      context_evidence: [{ evidence_id: "metric-latency-1", category: "metrics", source_id: "prometheus-metrics", connector: "prometheus", tenant_id: "default", project_id: "KaiMS", service: "api-gateway", observed_at: "2026-08-26T05:30:00Z", collected_at: "2026-08-26T05:30:00Z", freshness: "fresh", provenance: {}, citation: "prometheus://api-gateway/http_request_duration_seconds", epistemic_role: "current_observation", current_observation: true }],
      investigation_id: "66666666-6666-4666-8666-666666666667", investigation_status: "conclusive", investigation_conclusive: true,
      rca_version: 1, rca_status: "grounded", accepted_evidence_ids: ["metric-latency-1"], missing_evidence: [], conflicting_evidence: [],
      recommendation_id: "88888888-8888-5888-8888-888888888888", resolution_plan_id: "55555555-5555-4555-8555-555555555557",
      plan_fingerprint: `sha256:${"b".repeat(64)}`, execution_ready: true, readiness_blocks: [], approval_status: "pending",
      remediation_status: "not_started", validation_status: "pending",
      readiness: { investigation_ready: true, rca_ready: true, resolution_ready: true, execution_ready: true, blocking_reasons: [] },
    } : null,
    context: {
      tenant_id: "default",
      incident_id: incidentId,
      alert,
      metadata: {
        context_quality: { contract_version: "kaiops.context-quality.v1", quality_score: analysisComplete ? 0.94 : 0, coverage_score: analysisComplete ? 0.92 : 0, freshness_score: analysisComplete ? 0.98 : 0, provenance_score: analysisComplete ? 0.93 : 0, evidence_count: analysisComplete ? 1 : 0, reusable: analysisComplete },
        context_evidence: analysisComplete ? { metrics: evidence.map((item) => ({ ...item, source_id: item.source, observed_at: item.timestamp, freshness: "fresh", current_observation: true })) } : {},
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
        rca_status: analysisComplete ? "grounded" : "insufficient_evidence",
        rca_analysis: { root_cause: analysisComplete ? "API connection-pool saturation caused request queueing." : "Previous cached hypothesis.", causal_chain: "Pool exhaustion increased queue depth and request latency.", confidence_score: analysisComplete ? 0.94 : 0, evidence_used: analysisComplete ? ["metric-latency-1"] : [] },
        impact_analysis: { impact_summary: "API requests exceeded the latency SLO.", customer_impact: "Customers experienced delayed API responses.", impacted_services: ["api-gateway"], evidence_used: ["metric-latency-1"] },
        remediation_analysis: { recommended_action: "Increase the API connection pool and recycle saturated workers through the governed rollout." },
        investigation_report: { status: "conclusive", conclusive: true, conclusion: { confidence: 0.94 } },
        execution_plan: analysisComplete ? { plan_id: "55555555-5555-4555-8555-555555555557", plan_fingerprint: `sha256:${"b".repeat(64)}`, execution_ready: true, mutating: true, readiness_blocks: [] } : {},
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
    } else if (path === "/analysis/resolution-catalog/relevant") body = { data: { rows: [{ id: "catalog-plan-1", title: "Scale API pool", risk: "medium" }] } };
    else if (path === "/analysis/resolution-catalog/select") body = { data: { selected: { id: "catalog-plan-1", title: "Scale API pool", execution_eligible: false } } };
    else if (path.startsWith("/incidents/metadata")) body = { rows: [{ ...incident, title: "api-gateway: HighRequestLatency", projection_payload: { alert_id: alertId } }] };
    else if (path.startsWith("/alerts/all")) body = { data: { rows: [alert] } };
    else if (path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto(`/?workspace=alert&alert_id=${alertId}`);
  await signInIfNeeded(page);
  await expect(page.getByRole("heading", { name: "api-gateway: HighRequestLatency" })).toBeVisible();
  await expect(page.getByText("0 linked record(s) · RCA and impact")).toBeVisible();
  await expect(page.getByText("0% Ungrounded")).toBeVisible();

  const tabs = page.getByRole("tablist", { name: "Incident workspace sections" });
  await tabs.getByRole("tab", { name: "Evidence, RCA, and impact" }).click();
  await page.getByRole("button", { name: /Fresh context/ }).click();
  await page.getByRole("button", { name: "Run fresh analysis" }).click();

  await expect(page.getByText(`Fresh context and RCA analysis completed for alert ${alertId}.`)).toBeVisible();
  await expect(page.getByText("API connection-pool saturation caused request queueing.").first()).toBeVisible();
  await expect(page.getByText("Increase the API connection pool and recycle saturated workers through the governed rollout.").first()).toBeVisible();
  await expect(page.getByText("1 linked record(s) · RCA and impact")).toBeVisible();
  await tabs.getByRole("tab", { name: "Resolve incident" }).click();
  await expect(page.getByRole("heading", { name: "Resolution command center" })).toBeVisible();
  integrityMismatch = true;
  await page.reload();
  await signInIfNeeded(page);
  await page.getByRole("tablist", { name: "Incident workspace sections" }).getByRole("tab", { name: "Evidence, RCA, and impact" }).click();
  await expect(page.getByText("Investigation integrity error: fingerprint mismatch. Resolution is blocked.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Plan blocked by readiness" })).toBeDisabled();
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
    else if (path.startsWith("/incidents/groups")) body = { data: { rows: [{ incident_id: incidentId, alert_id: alertId, title: "httpbin-failure-lab: ExternalApplicationUnavailable", service: "httpbin-failure-lab", environment: "public-internet", status: "awaiting_approval", ticket_id: "KAN-1376", source: "public-internet-blackbox", projection_payload: { context_source: "realtime_collection", event_payload: { labels: { application: "httpbin-failure-lab", project_name: "KaiOps", instance: "https://httpbin.org/status/503", alertname: "ExternalApplicationUnavailable", job: "blackbox", transport: "alertmanager", environment: "public-internet" } } } }], total_count: 1, filtered_count: 1 } };
    else if (path.startsWith("/alerts/all")) body = { data: { rows: [{ id: alertId, name: "ExternalApplicationUnavailable", service: "httpbin-failure-lab", source: "public-internet-blackbox", starts_at: "2026-08-11T15:23:20Z", trace_id: "trace-httpbin-503", description: "HTTPS probe failed for https://httpbin.org/status/503 in public-internet.", labels: { application: "httpbin-failure-lab", project_name: "KaiOps", instance: "https://httpbin.org/status/503", alertname: "ExternalApplicationUnavailable", job: "blackbox", transport: "alertmanager", alert_status: "firing", ingestion_channel: "monitoring" }, annotations: { generatorURL: "http://prometheus:9090/graph?g0.expr=probe_success" } }] } };
    else if (path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/alerts");
  await signInIfNeeded(page);
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
