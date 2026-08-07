# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: accessibility.spec.js >> login and primary workspace have no serious or critical accessibility violations
- Location: tests/e2e/accessibility.spec.js:29:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: 'Dashboard', level: 1 })
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for getByRole('heading', { name: 'Dashboard', level: 1 })

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

```
Error: apiRequestContext._wrapApiCall: ENOMEM: not enough memory, read
```