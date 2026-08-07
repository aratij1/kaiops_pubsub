# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: navigation-routing.spec.js >> legacy bookmarks, canonical navigation and scroll state survive route changes
- Location: tests/e2e/navigation-routing.spec.js:3:1

# Error details

```
Error: expect(page).toHaveTitle(expected) failed

Expected: "Approvals | KaiOps"
Received: "Operational Workspace | KaiOps"
Timeout:  5000ms

Call log:
  - Expect "toHaveTitle" with timeout 5000ms
    8 × unexpected value "Operational Workspace | KaiOps"

```

```yaml
- main:
  - link "Skip to workspace content":
    - /url: "#workspace-content"
  - complementary:
    - paragraph: KaiOps
    - heading "Operations" [level=2]
    - paragraph: Monitor, investigate, and resolve.
    - heading "Monitor" [level=3]
    - text: Application
    - combobox "Application":
      - option "Real Use Cases" [selected]
      - option "Test Use Cases"
    - text: api-gateway is ok
    - group: Display preferences +
    - navigation "Primary navigation":
      - heading "Operations" [level=3]
      - button "Dashboard"
      - button "Live Alerts"
      - button "Incidents"
      - button "Approvals"
      - heading "Intelligence" [level=3]
      - button "Copilot"
      - button "Agent Flow"
      - button "Knowledge"
      - heading "Governance" [level=3]
      - button "Gateway Safety"
      - button "Audit"
      - button "Closed Incidents"
      - heading "Platform" [level=3]
      - button "Applications"
      - button "Integrations"
      - button "Admin"
    - button "Refresh"
    - button "Health"
  - paragraph: Operations
  - heading "Operational Workspace" [level=1]
  - paragraph: home · health · attention
  - navigation "Breadcrumb":
    - list:
      - listitem: Operations
      - listitem: /Dashboard
  - text: "api-gateway is ok Monitoring: Real Use Cases Signed in: admin (Administrator)"
  - button "Logout"
  - group "Global operational capabilities":
    - text: Search & personal work Find records, assignments, and notifications ⌄
    - tablist "Global operations":
      - tab "Search" [selected]
      - tab "My Work (0)"
      - tab "Notifications (0)"
    - text: Global search
    - searchbox "Global search"
    - paragraph: Searches currently loaded, role-authorized operational records.
  - article:
    - text: Administrator dashboard
    - heading "Platform attention" [level=2]
    - paragraph: Connector, queue, agent, workflow, and telemetry health.
    - text: Current operational window
    - strong: Asia/Kolkata (IST)
    - text: current data
    - article:
      - text: Connector Health
      - strong: 0/0
      - paragraph: Registered monitoring applications without a failed health status.
      - button "View records"
    - article:
      - text: Queue Health
      - strong: Unknown
      - paragraph: Configured deployment message-bus provider; queue age is unavailable in this UI contract.
      - button "View records"
    - article:
      - text: Agent Health
      - strong: "0"
      - paragraph: Persisted agent or trace events for the selected alert.
      - button "View records"
    - article:
      - text: Workflow Health
      - strong: Clear
      - paragraph: Selected workflow events containing failed or error state.
      - button "View records"
    - article:
      - text: Telemetry
      - strong: "0"
      - paragraph: API gateway telemetry events in the current loaded window.
      - button "View records"
    - group: Metric definitions and data quality
  - article:
    - text: Monitoring projects
    - heading "KaiOps + Telemetry" [level=2]
    - paragraph: Select a project to scope alerts, incidents, discovery evidence, and timeline events.
    - button "Refresh Projects"
    - button "KO KaiOps kaiops namespace API Gateway metrics registered":
      - text: KO
      - strong: KaiOps
      - text: kaiops namespace
      - code: API Gateway metrics
      - text: registered
    - button "OT Telemetry telemetry namespace Prometheus :19090 registered":
      - text: OT
      - strong: Telemetry
      - text: telemetry namespace
      - code: Prometheus :19090
      - text: registered
  - article:
    - heading "Workflow Health & Next Action" [level=2]
    - paragraph: Fast status across intake, resolution, approval, and remediation.
    - strong: Alert Intake
    - text: IDLE
    - paragraph: No open alerts in the current monitoring scope.
    - strong: Approval Queue
    - text: CLEAR
    - paragraph: No incidents are waiting for human approval.
    - strong: Resolution Intelligence
    - text: ATTENTION
    - paragraph: No resolution trace detected for selected alert yet.
    - strong: Remediation Automation
    - text: ATTENTION
    - paragraph: No remediation execution trace detected yet.
    - paragraph: "Recommended next step: Generate or ingest a fresh alert to validate the end-to-end agent workflow."
  - article:
    - heading "Alert Stream" [level=2]
    - text: Show
    - combobox "Show alerts":
      - option "25" [selected]
      - option "50"
      - option "100"
      - option "200"
    - text: alerts
    - button "Refresh"
    - group "Alert triage focus":
      - button "Ops 0"
      - button "All 0"
      - button "Critical 0"
      - button "High 0"
      - button "Awaiting 0"
      - button "Active 0"
      - button "Closed 0"
      - button "Test 0"
    - textbox "Search alert name, service, app, id"
    - paragraph: Showing 0 of 0 alerts for Real Use Cases.
    - group "Filter dashboard alerts by source":
      - button "All 0" [pressed]
      - button "Prometheus 0"
      - button "Telemetry 0"
      - button "Email 0"
      - button "Ticket 0"
      - button "Logs 0"
    - paragraph: L2/L3/Admin can set future severity overrides by alert name + service + environment.
    - region "Alert stream table":
      - table:
        - rowgroup:
          - row "Alert ID Time (UTC) Name Rule Application Service Source Severity Tier Status Action":
            - columnheader "Alert ID"
            - columnheader "Time (UTC)"
            - columnheader "Name"
            - columnheader "Rule"
            - columnheader "Application"
            - columnheader "Service"
            - columnheader "Source"
            - columnheader "Severity"
            - columnheader "Tier"
            - columnheader "Status"
            - columnheader "Action"
        - rowgroup:
          - row "No alerts match current filters for Real Use Cases.":
            - cell "No alerts match current filters for Real Use Cases."
  - article:
    - paragraph: Select an alert in Alert Stream to open the detail tabs workspace.
```

# Test source

```ts
  1  | import { expect, test } from "@playwright/test";
  2  | 
  3  | test("legacy bookmarks, canonical navigation and scroll state survive route changes", async ({ page }) => {
  4  |   test.setTimeout(90_000);
  5  |   await page.route("**/api-gateway/**", async (route) => {
  6  |     const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
  7  |     const body = path === "/auth/config"
  8  |       ? { mode: "local", local_development_only: true }
  9  |       : path === "/auth/login"
  10 |       ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
  11 |       : path === "/healthz"
  12 |         ? { status: "ok", service: "api-gateway" }
  13 |         : path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent") || path === "/applications"
  14 |           ? { data: { rows: [] } }
  15 |           : { data: [], rows: [], summary: {}, items: [] };
  16 |     await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  17 |   });
  18 | 
  19 |   await page.goto("/approval-queue-legacy");
  20 |   await expect(page).toHaveURL(/\/approvals$/, { timeout: 30_000 });
  21 |   await page.getByLabel("Username").fill("admin");
  22 |   await page.getByLabel("Password").fill("Admin@123456");
  23 |   await page.getByRole("button", { name: "Sign In" }).click();
  24 | 
> 25 |   await expect(page).toHaveTitle("Approvals | KaiOps");
     |                      ^ Error: expect(page).toHaveTitle(expected) failed
  26 |   await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Operations");
  27 |   await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Approvals");
  28 |   await expect(page.getByRole("button", { name: "Approvals", exact: true })).toHaveAttribute("aria-current", "page");
  29 | 
  30 |   await page.getByRole("button", { name: "Dashboard", exact: true }).click();
  31 |   await expect(page).toHaveURL(/\/$/);
  32 |   await expect(page.getByRole("heading", { name: "KaiOps + Telemetry" })).toBeVisible();
  33 |   await page.evaluate(() => window.scrollTo(0, 500));
  34 |   const savedDashboardScroll = await page.evaluate(() => window.scrollY);
  35 |   expect(savedDashboardScroll).toBeGreaterThan(0);
  36 | 
  37 |   await page.getByRole("button", { name: "Live Alerts", exact: true }).click();
  38 |   await expect(page).toHaveURL(/\/alerts$/);
  39 |   await expect(page).toHaveTitle("Live Alerts | KaiOps");
  40 |   await page.getByRole("button", { name: "Dashboard", exact: true }).click();
  41 |   await expect(page.getByRole("heading", { name: "KaiOps + Telemetry" })).toBeVisible();
  42 |   await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThanOrEqual(savedDashboardScroll - 2);
  43 | 
  44 |   await page.setViewportSize({ width: 390, height: 844 });
  45 |   const mobileNavigation = page.getByLabel("Navigate to");
  46 |   await expect(mobileNavigation).toBeVisible();
  47 |   await mobileNavigation.selectOption("/applications");
  48 |   await expect(page).toHaveURL(/\/applications$/);
  49 |   await expect(page).toHaveTitle("Applications | KaiOps");
  50 |   await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Platform");
  51 |   await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Applications");
  52 | });
  53 | 
  54 | test("a restricted deep link redirects with a clear role explanation", async ({ page }) => {
  55 |   await page.route("**/api-gateway/**", async (route) => {
  56 |     const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
  57 |     const body = path === "/auth/config"
  58 |       ? { mode: "local", local_development_only: true }
  59 |       : path === "/auth/login"
  60 |       ? { access_token: "operator-token", refresh_token: "refresh-token", user: { id: 2, username: "operator", role_name: "L1 Operator" } }
  61 |       : path === "/healthz"
  62 |         ? { status: "ok", service: "api-gateway" }
  63 |         : { data: { rows: [] }, rows: [] };
  64 |     await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  65 |   });
  66 | 
  67 |   await page.goto("/admin");
  68 |   await page.getByLabel("Username").fill("operator");
  69 |   await page.getByLabel("Password").fill("Operator@123456");
  70 |   await page.getByRole("button", { name: "Sign In" }).click();
  71 |   await expect(page).toHaveURL(/\/\?access=restricted&destination=Admin/);
  72 |   await expect(page.getByRole("status")).toContainText("Admin is not available to your current role");
  73 |   await expect(page.getByRole("navigation", { name: "Primary navigation" })).not.toContainText("Platform");
  74 | });
  75 | 
```